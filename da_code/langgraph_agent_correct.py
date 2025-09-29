"""Correct LangGraph agent with proper async HIL pattern."""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, AsyncGenerator

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import Tool
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver

from .agent_interface import AgentInterface
from .models import (
    AgentConfig, CodeSession, CommandExecution, CommandStatus,
    LLMCall, LLMCallStatus, ToolCall, ToolCallStatus, UserResponse, da_mongo
)
from .execution_events import ExecutionEvent, EventType, ConfirmationResponse
from .chat_memory import create_chat_memory_manager
from .telemetry import TelemetryManager, PerformanceTracker
from .tools import create_all_tools

logger = logging.getLogger(__name__)


class CorrectLangGraphAgent(AgentInterface):
    """LangGraph agent with correct async HIL pattern."""

    def __init__(self, config: AgentConfig, session: CodeSession):
        """Initialize the correct LangGraph agent."""
        super().__init__(config, session)

        # Initialize telemetry manager
        self.telemetry = TelemetryManager(session)

        # Initialize Azure OpenAI
        self.llm = AzureChatOpenAI(
            azure_endpoint=config.azure_endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
            azure_deployment=config.deployment_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.agent_timeout,
            max_retries=config.max_retries
        )

        # Initialize chat memory manager
        self.memory_manager = create_chat_memory_manager(session.session_id)

        # Confirmation handler callback
        self.confirmation_handler = None

        # Initialize tools
        self.tools = self._create_tools()

        # Create the graph with correct HIL pattern
        self.graph = self._create_graph()

        logger.info("Correct LangGraph agent initialized successfully")

    def _create_tools(self) -> Dict[str, Tool]:
        """Create tools for the agent."""
        agent_tools = {}

        # Get standard tools
        modern_tools = create_all_tools(self.session.working_directory)
        for name, tool in modern_tools.items():
            agent_tools[name] = tool

        # Add execute_command tool
        execute_command_tool = Tool(
            name="execute_command",
            description="""Execute shell/bash commands with automatic user confirmation.

Input should be a JSON string with:
- command: The command to execute (required)
- explanation: Brief explanation of what the command does (optional)
- reasoning: Why this command is needed (optional)
- working_directory: Directory to run command in (optional)
- related_files: List of files this command affects (optional)

Example: {"command": "ls -la", "explanation": "List directory contents", "reasoning": "User wants to see files"}

The tool will request user confirmation before executing any command.""",
            func=self._execute_command_sync_wrapper
        )
        agent_tools["execute_command"] = execute_command_tool

        # Add MCP server tools
        mcp_tools = self._create_mcps()
        agent_tools.update(mcp_tools)

        return agent_tools

    def _execute_command_sync_wrapper(self, tool_input: str) -> str:
        """Sync wrapper for execute_command tool - used by LangGraph's sync tool interface."""
        try:
            # Parse tool input
            if tool_input.strip().startswith('{'):
                try:
                    params = json.loads(tool_input)
                except json.JSONDecodeError:
                    return f"Error: Invalid JSON format: {tool_input[:100]}"
            else:
                params = {"command": tool_input}

            command = params.get("command", "").strip()
            if not command:
                return "Error: No command provided"

            # Create a fake tool_call dict for compatibility with _execute_command_tool
            tool_call = {
                "args": params,
                "id": "sync_wrapper"
            }

            # Run the async method in the current event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context, create a task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, self._execute_command_tool(tool_call))
                        return future.result()
                else:
                    return loop.run_until_complete(self._execute_command_tool(tool_call))
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(self._execute_command_tool(tool_call))

        except Exception as e:
            logger.error(f"Error in command sync wrapper: {e}")
            return f"Error executing command: {str(e)}"

    def _create_mcps(self) -> Dict[str, Tool]:
        """Create MCP server tools from session configuration."""
        mcp_tools = {}

        if not self.session.mcp_servers:
            return mcp_tools

        for mcp_server in self.session.mcp_servers:
            try:
                for tool_name in mcp_server.tools:
                    mcp_tool_name = f"{mcp_server.name}_{tool_name}"
                    mcp_tools[mcp_tool_name] = self._create_mcp_tool(mcp_server, tool_name)
                    logger.info(f"Added MCP tool: {mcp_tool_name} from {mcp_server.name}")
            except Exception as e:
                logger.error(f"Failed to load MCP server {mcp_server.name}: {e}")
                continue

        return mcp_tools

    def _create_mcp_tool(self, mcp_server, tool_name: str) -> Tool:
        """Create a tool that calls an MCP server."""
        import httpx

        def sync_mcp_call(tool_input: str) -> str:
            try:
                try:
                    parsed_input = json.loads(tool_input) if tool_input.strip().startswith('{') else {"input": tool_input}

                    # Handle LangChain's __arg1 format when called via bind_tools()
                    if "__arg1" in parsed_input:
                        # For clipboard tools, map __arg1 to the expected argument name
                        if tool_name == "write_text":
                            arguments = {"text": parsed_input["__arg1"]}
                        elif tool_name == "read_text":
                            arguments = {}  # read_text takes no arguments
                        elif tool_name == "write_image":
                            arguments = {
                                "image_data": parsed_input["__arg1"],
                                "format": parsed_input.get("format", "PNG")
                            }
                        elif tool_name == "read_image":
                            arguments = {"format": parsed_input.get("format", "PNG")}
                        else:
                            # For other tools, use generic mapping
                            arguments = {"input": parsed_input["__arg1"]}
                    else:
                        arguments = parsed_input
                except json.JSONDecodeError:
                    arguments = {"input": tool_input}

                logger.debug(f"MCP tool {tool_name} called with arguments: {arguments}")

                # Additional debug for image tools
                if tool_name in ["write_image", "read_image"]:
                    if "image_data" in arguments:
                        logger.debug(f"Image data length: {len(arguments['image_data'])} characters")
                    logger.debug(f"Full MCP call URL: {mcp_server.url}/mcp/call/{tool_name}")

                async def call_mcp():
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        payload = {"arguments": arguments}
                        logger.debug(f"MCP payload for {tool_name}: {payload if tool_name != 'write_image' else {k: f'<{len(v)} chars>' if k == 'arguments' and 'image_data' in str(v) else v for k, v in payload.items()}}")

                        response = await client.post(
                            f"{mcp_server.url}/mcp/call/{tool_name}",
                            json=payload
                        )
                        response.raise_for_status()
                        result = response.json()

                        logger.debug(f"MCP response for {tool_name}: {result}")

                        if result.get("isError", False):
                            error_content = result.get('content', [{}])
                            error_text = error_content[0].get('text', 'Unknown error') if error_content else 'Unknown error'
                            return f"❌ MCP Error: {error_text}"
                        content = result.get("content", [])
                        return content[0].get("text", "No response") if content else "No response from MCP server"

                try:
                    # Try to get the current event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context - use ThreadPoolExecutor to run async code
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, call_mcp())
                            result = future.result()
                            logger.debug(f"MCP tool {tool_name} result: {result}")
                            return result
                    except RuntimeError:
                        # No running loop - safe to use asyncio.run
                        result = asyncio.run(call_mcp())
                        logger.debug(f"MCP tool {tool_name} result: {result}")
                        return result
                except Exception as async_error:
                    logger.error(f"Async execution error for MCP tool {tool_name}: {async_error}")
                    return f"❌ MCP async error: {str(async_error)}"

            except Exception as e:
                return f"❌ MCP tool error: {str(e)}"

        # Create more descriptive tool descriptions based on tool name and server
        tool_description = f"{tool_name} tool from {mcp_server.name} MCP server"

        # Enhanced descriptions for clipboard tools
        if mcp_server.name == "clipboard":
            if tool_name == "write_text":
                tool_description = "Write text to Windows clipboard. Use this for copying text to clipboard instead of shell commands."
            elif tool_name == "read_text":
                tool_description = "Read text from Windows clipboard. Use this to get clipboard contents."
            elif tool_name == "write_image":
                tool_description = "Write base64 image to Windows clipboard. Use this for copying images to clipboard."
            elif tool_name == "read_image":
                tool_description = "Read image from Windows clipboard as base64. Use this to get clipboard images."

        return Tool(
            name=f"{mcp_server.name}_{tool_name}",
            description=tool_description,
            func=sync_mcp_call
        )

    def _create_graph(self):
        """Create the LangGraph workflow with correct HIL pattern."""
        workflow = StateGraph(MessagesState)

        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._tools_node)

        # Add edges
        workflow.add_edge(START, "agent")

        # Conditional edge: continue to tools or end
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END
            }
        )

        # After tools, go back to agent
        workflow.add_edge("tools", "agent")

        # Compile with interrupt before tools for confirmation
        return workflow.compile(
            checkpointer=MemorySaver(),
            interrupt_before=["tools"]
        )

    async def _agent_node(self, state: MessagesState):
        """The main agent reasoning node."""
        system_prompt = self._build_system_prompt()
        messages = [SystemMessage(content=system_prompt)] + state["messages"]

        # Bind tools to LLM
        llm_with_tools = self.llm.bind_tools(list(self.tools.values()))

        # Get response from LLM
        start_time = time.time()
        try:
            response = await llm_with_tools.ainvoke(messages)

            # Track LLM call
            llm_call = LLMCall(
                model_name=self.config.deployment_name,
                provider="azure_openai",
                prompt=str(messages[-1].content) if messages else "",
                response=response.content if response.content else "[Tool calls requested]",
                status=LLMCallStatus.SUCCESS,
                response_time_ms=(time.time() - start_time) * 1000
            )
            self.session.add_llm_call(llm_call)

            return {"messages": [response]}

        except Exception as e:
            llm_call = LLMCall(
                model_name=self.config.deployment_name,
                provider="azure_openai",
                prompt=str(messages[-1].content) if messages else "",
                response="",
                status=LLMCallStatus.FAILED,
                error_message=str(e),
                response_time_ms=(time.time() - start_time) * 1000
            )
            self.session.add_llm_call(llm_call)
            raise

    async def _tools_node(self, state: MessagesState):
        """Execute tools - called after interrupt/confirmation."""
        messages = state["messages"]
        last_message = messages[-1]

        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return {"messages": []}

        tool_messages = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]

            if tool_name in self.tools:
                tool = self.tools[tool_name]

                # Track tool call
                tool_call_record = ToolCall(
                    server_name="internal",
                    tool_name=tool_name,
                    arguments=tool_call["args"],
                    status=ToolCallStatus.PENDING
                )

                try:
                    # Handle execute_command specially
                    if tool_name == "execute_command":
                        result = await self._execute_command_tool(tool_call)
                    else:
                        # Execute other tools normally
                        if hasattr(tool, 'func'):
                            tool_input = json.dumps(tool_call["args"]) if isinstance(tool_call["args"], dict) else str(tool_call["args"])
                            result = tool.func(tool_input)
                        elif hasattr(tool, 'execute'):
                            result = await tool.execute(json.dumps(tool_call["args"]))
                        else:
                            result = f"Error: Tool {tool_name} has no callable method"

                    tool_call_record.result = {"output": result}
                    tool_call_record.status = ToolCallStatus.SUCCESS

                except Exception as e:
                    result = f"Error executing {tool_name}: {str(e)}"
                    tool_call_record.status = ToolCallStatus.FAILED
                    tool_call_record.result = {"error": str(e)}

                finally:
                    self.session.add_tool_call(tool_call_record)

                tool_messages.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call["id"]
                    )
                )
            else:
                tool_messages.append(
                    ToolMessage(
                        content=f"Error: Unknown tool {tool_name}",
                        tool_call_id=tool_call["id"]
                    )
                )

        return {"messages": tool_messages}

    async def _execute_command_tool(self, tool_call: Dict[str, Any]) -> str:
        """Execute command with confirmation handling."""
        try:
            args = tool_call["args"]

            # Handle LangChain's tool argument format
            if isinstance(args, dict) and "__arg1" in args:
                try:
                    args = json.loads(args["__arg1"])
                except json.JSONDecodeError:
                    args = {"command": args["__arg1"]}

            # Parse command input
            if isinstance(args, dict):
                command = args.get("command", "")
                explanation = args.get("explanation", "")
                reasoning = args.get("reasoning", "")
                working_directory = args.get("working_directory", self.session.working_directory)
                related_files = args.get("related_files", [])
            else:
                # Fallback if args is a string
                try:
                    parsed = json.loads(str(args))
                    command = parsed.get("command", str(args))
                    explanation = parsed.get("explanation", "")
                    reasoning = parsed.get("reasoning", "")
                    working_directory = parsed.get("working_directory", self.session.working_directory)
                    related_files = parsed.get("related_files", [])
                except:
                    command = str(args)
                    explanation = ""
                    reasoning = ""
                    working_directory = self.session.working_directory
                    related_files = []

            if not command.strip():
                return "Error: No command provided"

            # Create command execution record
            execution = CommandExecution(
                command=command,
                explanation=explanation,
                working_directory=working_directory,
                agent_reasoning=reasoning,
                related_files=related_files
            )

            # The HIL confirmation happens BEFORE this node is called via LangGraph interrupt
            # So if we get here, the command was already approved - just execute it

            # Execute the approved command
            return await self._execute_approved_command(execution)

        except Exception as e:
            logger.error(f"Error in command execution: {e}")
            return f"Error executing command: {str(e)}"

    async def _execute_approved_command(self, execution: CommandExecution) -> str:
        """Execute an approved command."""
        import subprocess

        try:
            execution.update_status(CommandStatus.APPROVED)
            start_time = time.time()

            result = subprocess.run(
                execution.command,
                shell=True,
                cwd=execution.working_directory,
                capture_output=True,
                text=True,
                timeout=300
            )

            execution.exit_code = result.returncode
            execution.stdout = result.stdout
            execution.stderr = result.stderr
            execution.execution_time = time.time() - start_time

            if result.returncode == 0:
                execution.update_status(CommandStatus.SUCCESS)
                self.session.add_execution(execution)

                output = f"✅ Command executed successfully\n"
                if result.stdout:
                    stdout = result.stdout.strip()
                    output += f"Output:\n{stdout[:2000]}" + ("...\n(truncated)" if len(stdout) > 2000 else "")
                else:
                    output += "No output"
                return output
            else:
                execution.update_status(CommandStatus.FAILED)
                self.session.add_execution(execution)

                output = f"❌ Command failed (exit code: {result.returncode})\n"
                if result.stderr:
                    stderr = result.stderr.strip()
                    output += f"Error:\n{stderr[:1000]}" + ("...\n(truncated)" if len(stderr) > 1000 else "")
                return output

        except subprocess.TimeoutExpired:
            execution.update_status(CommandStatus.TIMEOUT)
            self.session.add_execution(execution)
            return "⏰ Command timed out after 5 minutes"
        except Exception as e:
            execution.update_status(CommandStatus.FAILED)
            execution.stderr = str(e)
            self.session.add_execution(execution)
            return f"❌ Command execution failed: {str(e)}"

    def _should_continue(self, state: MessagesState) -> str:
        """Decide whether to continue to tools or end."""
        messages = state["messages"]
        last_message = messages[-1]

        # Check if there are tool calls
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "continue"

        # No tool calls, end the conversation
        return "end"


    async def execute_task(self, task: str) -> str:
        """Execute a task and return the response (legacy method)."""
        final_response = None
        async for event in self.execute_task_stream(task):
            if event.event_type == EventType.FINAL_RESPONSE:
                final_response = event.content
                break
        return final_response or "No response generated"

    async def execute_task_stream(self, task: str, confirmation_handler=None) -> AsyncGenerator[ExecutionEvent, ConfirmationResponse]:
        """Execute a task with streaming events and confirmation support."""

        self.confirmation_handler = confirmation_handler

        with PerformanceTracker(self.telemetry, "langgraph", "execute_task_stream") as tracker:
            yield ExecutionEvent(
                event_type=EventType.EXECUTION_START,
                framework="langgraph",
                content=f"Starting task: {task[:50]}..."
            )

            try:
                # Create config with thread ID for checkpointing
                config = {"configurable": {"thread_id": self.session.session_id}}

                # Initial state with user message
                initial_state = {"messages": [HumanMessage(content=task)]}

                # Execute the graph and handle interrupts
                final_state = None
                interrupted_state = None

                # First execution - may hit interrupt
                async for event in self.graph.astream(initial_state, config=config):
                    logger.debug(f"Graph event: {event}")
                    final_state = event

                    # Check if we hit an interrupt (before tools node)
                    if "__interrupt__" in event:
                        logger.info("Graph interrupted before tools - confirmation needed")
                        interrupted_state = event
                        break  # Stop streaming, handle interrupt

                # If we hit an interrupt, we need to get the current state to find tool calls
                if interrupted_state:
                    logger.info(f"Processing interrupt state: {interrupted_state.keys()}")

                    # Get the current state of the graph to find tool calls
                    current_state = self.graph.get_state(config)
                    logger.info(f"Current graph state values: {list(current_state.values.keys()) if hasattr(current_state, 'values') else 'No values'}")

                    # Extract tool calls from the current state
                    tool_calls_to_confirm = []
                    safe_tool_calls = []

                    # Define dangerous tools that require confirmation
                    dangerous_tools = {"execute_command"}

                    # Check if current_state has values (messages)
                    if hasattr(current_state, 'values') and 'messages' in current_state.values:
                        messages = current_state.values['messages']
                        logger.info(f"Checking {len(messages)} messages from current state")

                        for msg in messages:
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                logger.info(f"Found {len(msg.tool_calls)} tool calls in message")
                                for tool_call in msg.tool_calls:
                                    tool_name = tool_call['name']
                                    logger.info(f"Tool call: {tool_name}")

                                    if tool_name in dangerous_tools:
                                        logger.info(f"Found dangerous tool requiring confirmation: {tool_name}")
                                        tool_calls_to_confirm.append(tool_call)
                                    else:
                                        logger.info(f"Found safe tool (auto-approved): {tool_name}")
                                        safe_tool_calls.append(tool_call)

                    logger.info(f"Found {len(tool_calls_to_confirm)} dangerous tools requiring confirmation")
                    logger.info(f"Found {len(safe_tool_calls)} safe tools (auto-approved)")
                    logger.info(f"Confirmation handler available: {self.confirmation_handler is not None}")

                    # Process confirmations for execute_command tools
                    confirmed_calls = []
                    for tool_call in tool_calls_to_confirm:
                        if self.confirmation_handler:
                            # Create CommandExecution for confirmation
                            args = tool_call["args"]

                            # Handle LangChain's tool argument format
                            if "__arg1" in args:
                                # Parse the JSON string in __arg1
                                try:
                                    args = json.loads(args["__arg1"])
                                except json.JSONDecodeError:
                                    # Fallback to treating as plain command
                                    args = {"command": args["__arg1"]}

                            execution = CommandExecution(
                                command=args.get("command", ""),
                                explanation=args.get("explanation", ""),
                                working_directory=args.get("working_directory", self.session.working_directory),
                                agent_reasoning=args.get("reasoning", ""),
                                related_files=args.get("related_files", [])
                            )

                            # Get user confirmation
                            confirmation_response = await self.confirmation_handler(execution)

                            if confirmation_response and confirmation_response.choice.lower() == UserResponse.YES.value:
                                if (confirmation_response.choice.lower() == UserResponse.MODIFY.value and
                                    confirmation_response.modified_command):
                                    # Update the tool call with modified command
                                    tool_call["args"]["command"] = confirmation_response.modified_command
                                confirmed_calls.append(tool_call)
                            else:
                                # User denied, don't execute
                                logger.info(f"Command execution denied: {execution.command}")

                    # Resume execution if we have safe tools OR confirmed dangerous tools
                    should_resume = len(safe_tool_calls) > 0 or len(confirmed_calls) > 0

                    if should_resume:
                        logger.info(f"Resuming execution: {len(safe_tool_calls)} safe tools + {len(confirmed_calls)} confirmed dangerous tools")
                        # Resume the graph from the interrupt
                        async for event in self.graph.astream(None, config=config):
                            logger.debug(f"Resumed graph event: {event}")
                            final_state = event
                    else:
                        # No safe tools and no confirmed dangerous tools - create cancellation response
                        logger.info("No tools to execute - user cancelled dangerous tools and no safe tools present")
                        final_state = {
                            "agent": {
                                "messages": [AIMessage(content="Command execution was cancelled by user.")]
                            }
                        }

                # Extract final response from the last state
                final_response = "Task completed"

                # If final_state only contains __interrupt__, get the actual graph state
                if final_state and "__interrupt__" in final_state and len(final_state) == 1:
                    logger.debug("Final state is interrupt only, getting graph state directly")
                    graph_state = self.graph.get_state(config)
                    if hasattr(graph_state, 'values') and 'messages' in graph_state.values:
                        messages = graph_state.values['messages']
                        logger.debug(f"Found {len(messages)} messages in graph state")
                        # Get the last AI message
                        for i, msg in enumerate(reversed(messages)):
                            logger.debug(f"Graph message {i}: {type(msg).__name__}: {msg.content[:100] if hasattr(msg, 'content') and msg.content else 'No content'}...")
                            if isinstance(msg, AIMessage) and msg.content:
                                final_response = msg.content
                                logger.info(f"Found final AI response from graph state: {final_response[:100]}...")
                                break
                elif final_state:
                    logger.debug(f"Final state keys: {list(final_state.keys())}")
                    logger.debug(f"Final state structure: {final_state}")

                    for node_name, node_state in final_state.items():
                        logger.debug(f"Processing node: {node_name}")
                        if node_name != "__interrupt__" and "messages" in node_state:
                            messages = node_state["messages"]
                            logger.debug(f"Found {len(messages)} messages in node {node_name}")
                            # Get the last AI message
                            for i, msg in enumerate(reversed(messages)):
                                logger.debug(f"Message {i}: {type(msg).__name__}: {msg.content[:100] if hasattr(msg, 'content') and msg.content else 'No content'}...")
                                if isinstance(msg, AIMessage) and msg.content:
                                    final_response = msg.content
                                    logger.info(f"Found final AI response: {final_response[:100]}...")
                                    break

                # Add conversation to chat history
                chat_history = self.memory_manager.get_chat_history()

                # Add the user message first
                chat_history.add_message(HumanMessage(content=task))

                # Add all relevant messages from the conversation (except system messages)
                if final_state:
                    all_conversation_messages = []
                    for node_name, node_state in final_state.items():
                        if node_name != "__interrupt__" and "messages" in node_state:
                            for msg in node_state["messages"]:
                                # Skip the initial system message and user message (already added)
                                if not isinstance(msg, (SystemMessage, HumanMessage)):
                                    all_conversation_messages.append(msg)

                    # Add all AI and tool messages to maintain proper sequence
                    for msg in all_conversation_messages:
                        chat_history.add_message(msg)
                else:
                    # Fallback: just add the final response as AI message
                    chat_history.add_message(AIMessage(content=final_response))

                # Track successful execution
                await self.telemetry.track_framework_call(
                    framework="langgraph",
                    prompt=task,
                    response=final_response,
                    tokens_used=0,
                    execution_time_ms=tracker.get_duration_ms(),
                    success=True
                )

                await da_mongo.save_session(self.session)

                yield ExecutionEvent(
                    event_type=EventType.FINAL_RESPONSE,
                    framework="langgraph",
                    content=final_response
                )

            except Exception as e:
                await self.telemetry.track_framework_call(
                    framework="langgraph",
                    prompt=task,
                    response="",
                    tokens_used=0,
                    execution_time_ms=tracker.get_duration_ms(),
                    success=False,
                    error_message=str(e)
                )

                yield ExecutionEvent(
                    event_type=EventType.ERROR,
                    framework="langgraph",
                    error_message=str(e),
                    content=f"Execution failed: {str(e)}"
                )

                logger.error(f"Correct LangGraph agent execution failed: {e}")

            finally:
                self.confirmation_handler = None

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        context_parts = []

        if self.session.project_context:
            context_parts.append(f"Project: {self.session.project_context.project_name}")
            if self.session.project_context.description:
                context_parts.append(f"Description: {self.session.project_context.description}")

        context_parts.append(f"Working Directory: {self.session.working_directory}")
        context = "\n".join(context_parts) if context_parts else "No additional context available."

        tools_desc = "\n".join([f"- {name}: {tool.description}" for name, tool in self.tools.items()])

        # Check if clipboard tools are available
        has_clipboard_tools = any("clipboard_" in name for name in self.tools.keys())
        clipboard_instruction = ""
        if has_clipboard_tools:
            clipboard_instruction = "\n3. CLIPBOARD OPERATIONS: When user asks to copy text, data, or files to clipboard, ALWAYS use clipboard_write_text tool instead of echo, cat, or shell commands"

        return f"""You are da_code, an AI coding assistant with access to tools for command execution and file operations.

CONTEXT:
{context}

AVAILABLE TOOLS:
{tools_desc}

INSTRUCTIONS:
1. Use the available tools to help users with their coding tasks
2. For command execution, use the execute_command tool - user confirmation is handled automatically{clipboard_instruction}
4. Be thorough but efficient in your approach
5. Provide clear explanations for your actions
6. Always use proper tool arguments as specified in the tool descriptions

TODO MANAGEMENT:
- Use the todo_file_manager tool to track work items for complex multi-step tasks
- Read existing todos at the start: {{"operation": "read"}}
- Create/update todos when planning work: {{"operation": "create", "content": "markdown todo list"}}
- Use proper markdown format with checkboxes: `- [ ] Task description`
- Mark completed items: `- [x] Completed task`

You have access to advanced tools for file operations, web search, and system commands. Use them wisely to complete user requests."""

    def get_framework_name(self) -> str:
        return "langgraph"

    def get_session_info(self) -> Dict[str, Any]:
        info = {
            "framework": self.get_framework_name(),
            "session_id": self.session.session_id,
            "agent_version": "1.0.0",
            "model_name": self.config.deployment_name,
            "temperature": self.config.temperature,
            "total_commands": len(self.session.executions),
            "successful_commands": self.session.successful_commands,
            "failed_commands": self.session.failed_commands,
        }

        if self.memory_manager:
            info["memory_info"] = self.memory_manager.get_memory_info()

        framework_metrics = self.telemetry.get_framework_metrics("langgraph")
        if framework_metrics:
            info["framework_metrics"] = framework_metrics

        return info

    def clear_memory(self) -> None:
        try:
            if self.memory_manager:
                chat_history = self.memory_manager.get_chat_history()
                chat_history.clear()
            logger.info("Correct LangGraph agent memory cleared")
        except Exception as e:
            logger.error(f"Failed to clear memory: {e}")
            raise

    async def get_metrics(self) -> Dict[str, Any]:
        base_metrics = await super().get_metrics()
        langgraph_metrics = self.telemetry.get_framework_metrics("langgraph")
        base_metrics.update({
            "langgraph_metrics": langgraph_metrics,
            "memory_info": self.memory_manager.get_memory_info() if self.memory_manager else None,
            "model_name": self.config.deployment_name,
            "temperature": self.config.temperature
        })
        return base_metrics