"""Custom async agent with native streaming and confirmation support."""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, AsyncGenerator

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

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


# ConfirmationRequired exception removed - using direct callbacks now


class AsyncCommandTool:
    """Async command execution tool with direct confirmation support."""

    def __init__(self, session: CodeSession, agent):
        self.name = "execute_command"
        self.description = """Execute shell/bash commands with automatic user confirmation.

Input should be a JSON string with:
- command: The command to execute
- explanation: Brief explanation of what the command does
- reasoning: Why this command is needed
- working_directory: Directory to run command in (optional)
- related_files: List of files this command affects (optional)

Example: {"command": "ls -la", "explanation": "List directory contents", "reasoning": "User wants to see files"}

The tool will request user confirmation before executing any command."""
        self.session = session
        self.agent = agent

    async def execute(self, input_data: str) -> str:
        """Execute command with direct confirmation callback."""
        try:
            # Parse input
            logger.debug(f"Tool input received: {repr(input_data)}")

            if isinstance(input_data, str):
                try:
                    params = json.loads(input_data)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error for tool input: {e}")
                    logger.warning(f"Raw input: {repr(input_data)}")

                    # Better fallback: if input looks like JSON but is malformed, try to extract command
                    if input_data.strip().startswith('{') and '"command"' in input_data:
                        # Try to extract command from malformed JSON
                        import re
                        command_match = re.search(r'"command"\s*:\s*"([^"]*)"', input_data)
                        if command_match:
                            extracted_command = command_match.group(1)
                            logger.info(f"Extracted command from malformed JSON: {extracted_command}")
                            params = {"command": extracted_command, "explanation": "Extracted from malformed JSON"}
                        else:
                            return f"Error: Malformed JSON input and couldn't extract command: {input_data[:100]}"
                    else:
                        # Treat entire input as command (old fallback behavior)
                        params = {"command": input_data, "explanation": "Direct command input"}
            else:
                params = input_data

            command = params.get("command", "").strip()
            if not command:
                logger.error(f"No command found in params: {params}")
                logger.error(f"Original input_data: {repr(input_data)}")
                return "Error: No command provided"

            # Debug log the parsed command
            logger.debug(f"Parsed command: {repr(command)}")

            # Create command execution record
            execution = CommandExecution(
                command=command,
                explanation=params.get("explanation", ""),
                working_directory=params.get("working_directory", self.session.working_directory),
                agent_reasoning=params.get("reasoning", ""),
                related_files=params.get("related_files", [])
            )

            # Use direct callback - much simpler!
            if self.agent.confirmation_handler:
                confirmation_response = await self.agent.confirmation_handler(execution)
                if not confirmation_response:
                    execution.update_status(CommandStatus.DENIED)
                    self.session.add_execution(execution)
                    return "❌ Command execution cancelled - no response received"

                # Handle the response directly
                return await self._handle_confirmation_response(execution, confirmation_response)
            else:
                # No confirmation handler, execute directly (for testing)
                return await self._execute_approved_command(execution)

        except Exception as e:
            logger.error(f"Error in command execution tool: {e}")
            return f"Error executing command: {str(e)}"

    async def _handle_confirmation_response(self, execution: CommandExecution, confirmation_response) -> str:
        """Handle confirmation response and execute command."""
        # Use enum values for consistent comparison
        choice = confirmation_response.choice.lower()

        if choice == UserResponse.YES.value:
            return await self._execute_approved_command(execution)
        elif choice == UserResponse.NO.value:
            execution.update_status(CommandStatus.DENIED)
            self.session.add_execution(execution)
            return "❌ Command execution cancelled by user"
        elif choice == UserResponse.MODIFY.value:
            if confirmation_response.modified_command:
                execution.command = confirmation_response.modified_command
                execution.user_modifications = confirmation_response.modified_command
            return await self._execute_approved_command(execution)
        elif choice == UserResponse.EXPLAIN.value:
            execution.update_status(CommandStatus.DENIED)
            self.session.add_execution(execution)
            return f"❓ Command explanation requested: {execution.command}"
        else:
            execution.update_status(CommandStatus.DENIED)
            self.session.add_execution(execution)
            return f"❌ Unknown confirmation choice: {confirmation_response.choice}"

    async def _execute_approved_command(self, execution: CommandExecution) -> str:
        """Execute an approved command."""
        import subprocess
        import os

        try:
            execution.update_status(CommandStatus.APPROVED)

            # Execute the command
            start_time = time.time()

            result = subprocess.run(
                execution.command,
                shell=True,
                cwd=execution.working_directory,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
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
                    # Show full output for shorter results, truncate longer ones intelligently
                    stdout = result.stdout.strip()
                    if len(stdout) <= 2000:
                        output += f"Output:\n{stdout}"
                    else:
                        output += f"Output:\n{stdout[:2000]}...\n(truncated - showing first 2000 chars)"
                else:
                    output += "No output"
                return output
            else:
                execution.update_status(CommandStatus.FAILED)
                self.session.add_execution(execution)

                output = f"❌ Command failed\n"
                output += f"Exit code: {result.returncode}\n"
                if result.stderr:
                    stderr = result.stderr.strip()
                    if len(stderr) <= 1000:
                        output += f"Error:\n{stderr}"
                    else:
                        output += f"Error:\n{stderr[:1000]}...\n(truncated - showing first 1000 chars)"
                else:
                    output += "No error output"
                return output

        except subprocess.TimeoutExpired:
            execution.update_status(CommandStatus.TIMEOUT)
            execution.timeout_seconds = 300
            self.session.add_execution(execution)
            return "⏰ Command timed out after 5 minutes"

        except Exception as e:
            execution.update_status(CommandStatus.FAILED)
            execution.stderr = str(e)
            self.session.add_execution(execution)
            return f"❌ Command execution failed: {str(e)}"


# AsyncEventEmitter removed - using direct callbacks now for much simpler flow!


class CustomAsyncAgent(AgentInterface):
    """Custom async agent with native streaming and confirmation support."""

    def __init__(self, config: AgentConfig, session: CodeSession):
        """Initialize the custom async agent."""
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

        # Simple callback for confirmations - no complex event system needed
        self.confirmation_handler = None

        # Initialize tools
        self.tools = self._create_tools()

        logger.info("Custom async agent initialized successfully")

    def _create_tools(self) -> Dict[str, Any]:
        """Create async tools with modern 2025 patterns."""
        tools = {}

        # Command execution tool with direct agent reference
        tools["execute_command"] = AsyncCommandTool(self.session, self)

        # Modern tool suite: todo, web search, file search, and time
        modern_tools = create_all_tools(self.session.working_directory)
        tools.update(modern_tools)

        # Add MCP server tools
        mcp_tools = self._create_mcps()
        tools.update(mcp_tools)

        return tools

    def _create_mcps(self) -> Dict[str, Any]:
        """Create MCP server tools from session configuration."""
        mcp_tools = {}

        if not self.session.mcp_servers:
            logger.info("No MCP servers configured in session")
            return mcp_tools

        logger.info(f"Loading {len(self.session.mcp_servers)} MCP servers")

        for mcp_server in self.session.mcp_servers:
            try:
                # Create tools for each MCP server
                for tool_name in mcp_server.tools:
                    mcp_tool_name = f"{mcp_server.name}_{tool_name}"
                    mcp_tools[mcp_tool_name] = self._create_mcp_tool(mcp_server, tool_name)
                    logger.info(f"Added MCP tool: {mcp_tool_name} from {mcp_server.name}")

            except Exception as e:
                logger.error(f"Failed to load MCP server {mcp_server.name}: {e}")
                continue

        logger.info(f"Successfully loaded {len(mcp_tools)} MCP tools")
        return mcp_tools

    def _create_mcp_tool(self, mcp_server, tool_name: str):
        """Create a tool that calls an MCP server."""
        from langchain.tools import Tool
        import httpx

        async def call_mcp_tool(tool_input: str) -> str:
            """Call MCP server tool via HTTP."""
            try:
                # Parse tool input as JSON if possible
                try:
                    import json
                    arguments = json.loads(tool_input) if tool_input.strip().startswith('{') else {"input": tool_input}
                except json.JSONDecodeError:
                    arguments = {"input": tool_input}

                # Call MCP server
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{mcp_server.url}/mcp/call/{tool_name}",
                        json={"arguments": arguments}
                    )
                    response.raise_for_status()

                    result = response.json()
                    if result.get("isError", False):
                        return f"❌ MCP Error: {result.get('content', [{}])[0].get('text', 'Unknown error')}"

                    content = result.get("content", [])
                    if content:
                        return content[0].get("text", "No response")
                    else:
                        return "No response from MCP server"

            except httpx.TimeoutException:
                return f"❌ MCP server timeout: {mcp_server.url}"
            except httpx.RequestError as e:
                return f"❌ MCP server connection error: {str(e)}"
            except Exception as e:
                return f"❌ MCP tool error: {str(e)}"

        # For async tools, we need to handle them properly in the agent execution
        def sync_wrapper(tool_input: str) -> str:
            """Sync wrapper for async MCP calls."""
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(call_mcp_tool(tool_input))
            except RuntimeError:
                # If no event loop is running, create one
                return asyncio.run(call_mcp_tool(tool_input))

        return Tool(
            name=f"{mcp_server.name}_{tool_name}",
            description=f"{tool_name} tool from {mcp_server.name} MCP server at {mcp_server.url}",
            func=sync_wrapper
        )

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        context_parts = []

        # Add project context
        if self.session.project_context:
            context_parts.append(f"Project: {self.session.project_context.project_name}")
            if self.session.project_context.description:
                context_parts.append(f"Description: {self.session.project_context.description}")

        # Add working directory
        context_parts.append(f"Working Directory: {self.session.working_directory}")

        context = "\n".join(context_parts) if context_parts else "No additional context available."

        tools_desc = "\n".join([f"- {name}: {tool.description}" for name, tool in self.tools.items()])

        return f"""You are da_code, an AI coding assistant with access to tools for command execution.

CONTEXT:
{context}

AVAILABLE TOOLS:
{tools_desc}

INSTRUCTIONS:
1. Use ReAct pattern: Think, Act, Observe, repeat until you have the final answer
2. When you need to execute commands, use the execute_command tool with proper JSON input
3. Commands are automatically handled with user confirmation - DO NOT ask for additional confirmation
4. Be cautious with destructive operations
5. Provide clear reasoning for each action
6. Give a comprehensive final answer when the task is complete

TODO MANAGEMENT:
- ALWAYS use the todo_file_manager tool to track work items for complex multi-step tasks
- Read existing todos at the start: {{"operation": "read"}}
- Create/update todos when planning work: {{"operation": "create", "content": "markdown todo list"}}
- Use proper markdown format with checkboxes: `- [ ] Task description`
- Mark completed items: `- [x] Completed task`
- Proactively manage todos throughout the conversation to keep track of progress

FORMAT:
Think: [Your reasoning about what to do next]
Action: [tool_name]
Action Input: [JSON input for the tool]
Observation: [Result from the tool]
... (repeat as needed)
Final Answer: [Your final response to the user]

Remember: Use proper JSON format for Action Input, and always provide clear explanations."""

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

        # Set the confirmation handler for this execution
        self.confirmation_handler = confirmation_handler

        with PerformanceTracker(self.telemetry, "custom_async", "execute_task_stream") as tracker:
            # Emit execution start event
            yield ExecutionEvent(
                event_type=EventType.EXECUTION_START,
                framework="custom_async",
                content=f"Starting task: {task[:50]}..."
            )

            try:
                # Add user message to chat history
                chat_history = self.memory_manager.get_chat_history()
                chat_history.add_message(HumanMessage(content=task))

                # Execute task directly - much simpler!
                final_response = await self._execute_task_with_history(task)

                # Track successful execution
                await self.telemetry.track_framework_call(
                    framework="custom_async",
                    prompt=task,
                    response=final_response,
                    tokens_used=0,  # TODO: Track actual tokens
                    execution_time_ms=tracker.get_duration_ms(),
                    success=True
                )

                # Save session
                await da_mongo.save_session(self.session)

                # Emit final response event
                yield ExecutionEvent(
                    event_type=EventType.FINAL_RESPONSE,
                    framework="custom_async",
                    content=final_response
                )

            except Exception as e:
                # Track failed execution
                await self.telemetry.track_framework_call(
                    framework="custom_async",
                    prompt=task,
                    response="",
                    tokens_used=0,
                    execution_time_ms=tracker.get_duration_ms(),
                    success=False,
                    error_message=str(e)
                )

                # Emit error event
                yield ExecutionEvent(
                    event_type=EventType.ERROR,
                    framework="custom_async",
                    error_message=str(e),
                    content=f"Execution failed: {str(e)}"
                )

                logger.error(f"Custom async agent execution failed: {e}")

            finally:
                # Clean up
                self.confirmation_handler = None

# Old confirmation methods removed - now handled directly in the tool

    async def _execute_task_with_history(self, task: str) -> str:
        """Execute task with chat history management."""
        # Get chat history
        chat_history = self.memory_manager.get_chat_history()

        # Note: The user message is already added in the main execute_task_stream method
        # We just need to ensure the final response gets saved

        # Create system message
        system_prompt = self._build_system_prompt()

        # Start the ReAct loop
        final_response = await self._react_loop(task, system_prompt)

        # Add final AI response to chat history (this is the key fix)
        chat_history.add_message(AIMessage(content=final_response))

        return final_response

    async def _react_loop(self, task: str, system_prompt: str) -> str:
        """Execute the ReAct loop with streaming events."""
        max_iterations = 10
        iteration = 0

        # Get chat history from memory manager
        chat_history = self.memory_manager.get_chat_history()

        # Build conversation from chat history
        messages = [SystemMessage(content=system_prompt)]

        # Add previous conversation from memory
        for message in chat_history.messages:
            messages.append(message)

        conversation_history = ""

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"ReAct iteration {iteration}")

            # Note: Event emission removed - using direct callback pattern now

            # Get AI response
            start_time = time.time()

            # Build prompt with conversation history
            current_prompt = f"{conversation_history}\n\nUser: {task}" if iteration == 1 else conversation_history

            llm_call = LLMCall(
                model_name=self.config.deployment_name,
                provider="azure_openai",
                prompt=current_prompt,
                status=LLMCallStatus.PENDING
            )

            try:
                response = await self.llm.ainvoke(messages)
                response_text = response.content

                llm_call.response = response_text
                llm_call.status = LLMCallStatus.SUCCESS
                llm_call.response_time_ms = (time.time() - start_time) * 1000

                # Note: Event emission removed - using direct callback pattern now

            except Exception as e:
                llm_call.status = LLMCallStatus.FAILED
                llm_call.error_message = str(e)
                llm_call.response_time_ms = (time.time() - start_time) * 1000
                raise
            finally:
                self.session.add_llm_call(llm_call)

            # Parse the response for actions
            conversation_history += f"\nAssistant: {response_text}"

            # Check if this is a final answer
            if "Final Answer:" in response_text:
                final_answer = response_text.split("Final Answer:")[-1].strip()
                logger.info("Found final answer, ending ReAct loop")
                return final_answer

            # Parse for actions
            action_match = re.search(r"Action:\s*(\w+)", response_text)

            # Better parsing for Action Input - handle multi-line JSON and various formats
            action_input_match = re.search(r"Action Input:\s*(.+?)(?=\n(?:Think:|Action:|Observation:|Final Answer:)|$)", response_text, re.DOTALL)

            if action_match and action_input_match:
                action_name = action_match.group(1).strip()
                raw_action_input = action_input_match.group(1).strip()

                logger.debug(f"Raw action input before cleaning: {repr(raw_action_input)}")

                # Clean up JSON formatting - handle various code block formats
                action_input = raw_action_input
                if action_input.startswith('```json'):
                    action_input = action_input.replace('```json', '').replace('```', '').strip()
                elif action_input.startswith('```'):
                    action_input = action_input.replace('```', '').strip()

                # Remove any trailing whitespace or newlines
                action_input = action_input.strip()

                logger.info(f"Executing action: {action_name} with input: {action_input[:100]}...")
                logger.debug(f"Full cleaned action input: {repr(action_input)}")

                # Execute the action
                if action_name in self.tools:
                    tool = self.tools[action_name]

                    # Note: Event emission removed - using direct callback pattern now

                    # Track tool call
                    tool_call = ToolCall(
                        server_name="internal",  # Internal tools
                        tool_name=action_name,
                        arguments={"input": action_input},
                        status=ToolCallStatus.PENDING
                    )

                    try:
                        # Handle different tool interfaces
                        if hasattr(tool, 'execute'):
                            # AsyncCommandTool with async execute method
                            observation = await tool.execute(action_input)
                        elif hasattr(tool, 'func'):
                            # LangChain Tool with sync func method
                            observation = tool.func(action_input)
                        else:
                            raise AttributeError(f"Tool {action_name} has no execute() or func() method")

                        tool_call.result = {"output": observation}
                        tool_call.status = ToolCallStatus.SUCCESS

                        # Note: Event emission removed - using direct callback pattern now

                    except Exception as e:
                        # All exceptions are handled as tool failures now - no special confirmation handling
                        observation = f"Error executing {action_name}: {str(e)}"
                        tool_call.status = ToolCallStatus.FAILED
                        tool_call.result = {"error": str(e)}
                        logger.error(f"Tool execution failed: {e}")
                    finally:
                        self.session.add_tool_call(tool_call)

                    # Add observation to conversation
                    conversation_history += f"\nObservation: {observation}"

                    # Update messages for next iteration
                    ai_message = AIMessage(content=response_text)
                    observation_message = HumanMessage(content=f"Observation: {observation}")

                    messages.append(ai_message)
                    messages.append(observation_message)

                else:
                    error_msg = f"Unknown tool: {action_name}"
                    conversation_history += f"\nObservation: {error_msg}"

                    ai_message = AIMessage(content=response_text)
                    observation_message = HumanMessage(content=f"Observation: {error_msg}")

                    messages.append(ai_message)
                    messages.append(observation_message)

            else:
                # No clear action found, treat as final answer
                logger.warning(f"No valid action found in AI response: {repr(response_text[:500])}")
                logger.debug(f"Action match: {action_match}")
                logger.debug(f"Action input match: {action_input_match}")
                logger.info("No action found, treating as final answer")
                return response_text

        # Max iterations reached
        logger.warning(f"Max iterations ({max_iterations}) reached")
        return f"I've reached the maximum number of iterations ({max_iterations}) but haven't completed the task. The last response was: {conversation_history.split('Assistant:')[-1] if 'Assistant:' in conversation_history else 'No response available'}"

    def get_framework_name(self) -> str:
        """Return the framework identifier."""
        return "custom_async"

    def get_session_info(self) -> Dict[str, Any]:
        """Get current session information."""
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

        # Add memory info
        if self.memory_manager:
            info["memory_info"] = self.memory_manager.get_memory_info()

        # Add framework metrics
        framework_metrics = self.telemetry.get_framework_metrics("custom_async")
        if framework_metrics:
            info["framework_metrics"] = framework_metrics

        return info

    def clear_memory(self) -> None:
        """Clear agent conversation memory."""
        try:
            if self.memory_manager:
                chat_history = self.memory_manager.get_chat_history()
                chat_history.clear()
            logger.info("Custom async agent memory cleared")
        except Exception as e:
            logger.error(f"Failed to clear memory: {e}")
            raise

    async def get_metrics(self) -> Dict[str, Any]:
        """Get custom async agent metrics."""
        base_metrics = await super().get_metrics()

        # Add custom async specific metrics
        custom_metrics = self.telemetry.get_framework_metrics("custom_async")
        base_metrics.update({
            "custom_async_metrics": custom_metrics,
            "memory_info": self.memory_manager.get_memory_info() if self.memory_manager else None,
            "model_name": self.config.deployment_name,
            "temperature": self.config.temperature
        })

        return base_metrics