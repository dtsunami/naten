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
    LLMCall, LLMCallStatus, ToolCall, ToolCallStatus, da_mongo
)
from .execution_events import ExecutionEvent, EventType, ConfirmationResponse
from .chat_memory import create_chat_memory_manager
from .telemetry import TelemetryManager, PerformanceTracker

logger = logging.getLogger(__name__)


class ConfirmationRequired(Exception):
    """Exception raised when command confirmation is required."""
    pass


class AsyncTool:
    """Base class for async tools."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    async def execute(self, input_data: str) -> str:
        """Execute the tool asynchronously."""
        raise NotImplementedError


class AsyncCommandTool(AsyncTool):
    """Async command execution tool with native confirmation support."""

    def __init__(self, session: CodeSession, event_emitter):
        super().__init__(
            "execute_command",
            """Execute shell/bash commands with automatic user confirmation.

Input should be a JSON string with:
- command: The command to execute
- explanation: Brief explanation of what the command does
- reasoning: Why this command is needed
- working_directory: Directory to run command in (optional)
- related_files: List of files this command affects (optional)

Example: {"command": "ls -la", "explanation": "List directory contents", "reasoning": "User wants to see files"}

The tool will request user confirmation before executing any command."""
        )
        self.session = session
        self.event_emitter = event_emitter

    async def execute(self, input_data: str) -> str:
        """Execute command with real-time confirmation."""
        try:
            # Parse input with better error handling
            logger.info(f"Tool input received: {repr(input_data)}")

            if isinstance(input_data, str):
                try:
                    params = json.loads(input_data)
                    logger.info(f"Successfully parsed JSON: {params}")
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error: {e}. Using input as command: {repr(input_data)}")
                    params = {"command": input_data, "explanation": "Execute shell command"}
            else:
                params = input_data
                logger.info(f"Non-string input received: {params}")

            command = params.get("command", "").strip()
            if not command:
                logger.debug(f"No command found in params: {params}")
                return "Error: No command provided"

            logger.debug(f"Extracted command: {repr(command)}")

            # Create command execution record
            execution = CommandExecution(
                command=command,
                explanation=params.get("explanation", ""),
                working_directory=params.get("working_directory", self.session.working_directory),
                agent_reasoning=params.get("reasoning", ""),
                related_files=params.get("related_files", [])
            )

            # Store this execution globally for the CLI to find
            if not hasattr(self.session, '_current_confirmation'):
                self.session._current_confirmation = None

            self.session._current_confirmation = execution

            # Raise special exception to trigger confirmation flow
            raise ConfirmationRequired(f"Command confirmation needed: {command}")

        except ConfirmationRequired:
            # Re-raise to trigger confirmation
            raise
        except Exception as e:
            logger.error(f"Error in command execution tool: {e}")
            return f"Error executing command: {str(e)}"

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
                output += f"Exit code: {result.returncode}\n"
                if result.stdout:
                    output += f"Output: {result.stdout[:500]}..."
                return output
            else:
                execution.update_status(CommandStatus.FAILED)
                self.session.add_execution(execution)

                output = f"❌ Command failed\n"
                output += f"Exit code: {result.returncode}\n"
                if result.stderr:
                    output += f"Error: {result.stderr[:500]}..."
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


class AsyncEventEmitter:
    """Handles async event emission and confirmation requests."""

    def __init__(self):
        self._event_queue = asyncio.Queue()
        self._pending_confirmations = {}
        self._next_confirmation_id = 0

    async def emit_event(self, event: ExecutionEvent):
        """Emit an event to the queue."""
        await self._event_queue.put(event)

    async def request_confirmation(self, execution: CommandExecution) -> Optional[ConfirmationResponse]:
        """Request confirmation and wait for response."""
        confirmation_id = self._next_confirmation_id
        self._next_confirmation_id += 1

        # Store the execution for later retrieval
        self._pending_confirmations[confirmation_id] = {"execution": execution, "response": None}

        # Emit confirmation event with ID embedded
        event = ExecutionEvent(
            event_type=EventType.COMMAND_CONFIRMATION_NEEDED,
            framework="custom_async",
            execution=execution,
            content=f"Command confirmation needed: {execution.command}",
            metadata={"confirmation_id": confirmation_id}
        )

        await self.emit_event(event)

        # Wait for response using polling instead of futures
        for _ in range(3000):  # 5 minutes with 0.1s intervals
            await asyncio.sleep(0.1)
            if confirmation_id in self._pending_confirmations:
                pending = self._pending_confirmations[confirmation_id]
                if pending["response"] is not None:
                    response = pending["response"]
                    del self._pending_confirmations[confirmation_id]
                    return response
            else:
                # Confirmation was handled and removed
                return None

        # Timeout
        logger.warning(f"Confirmation timeout for command: {execution.command}")
        if confirmation_id in self._pending_confirmations:
            del self._pending_confirmations[confirmation_id]
        return None

    def provide_confirmation_response(self, confirmation_id: int, response: ConfirmationResponse):
        """Provide a confirmation response."""
        if confirmation_id in self._pending_confirmations:
            future = self._pending_confirmations.pop(confirmation_id)
            if not future.done():
                future.set_result(response)
        else:
            logger.warning(f"No pending confirmation found for ID: {confirmation_id}")

    async def get_next_event(self) -> Optional[ExecutionEvent]:
        """Get the next event from the queue."""
        try:
            return await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None


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

        # Initialize event emitter
        self.event_emitter = AsyncEventEmitter()

        # Initialize tools
        self.tools = self._create_tools()

        logger.info("Custom async agent initialized successfully")

    def _create_tools(self) -> Dict[str, AsyncTool]:
        """Create async tools."""
        tools = {}

        # Command execution tool
        tools["execute_command"] = AsyncCommandTool(self.session, self.event_emitter)

        return tools

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

    async def execute_task_stream(self, task: str) -> AsyncGenerator[ExecutionEvent, ConfirmationResponse]:
        """Execute a task with streaming events and confirmation support."""

        with PerformanceTracker(self.telemetry, "custom_async", "execute_task_stream") as tracker:
            # Emit execution start event
            yield ExecutionEvent(
                event_type=EventType.EXECUTION_START,
                framework="custom_async",
                content=f"Starting task: {task[:50]}..."
            )

            try:
                # Clear any previous confirmation
                if hasattr(self.session, '_current_confirmation'):
                    self.session._current_confirmation = None

                # Add user message to chat history at the beginning
                chat_history = self.memory_manager.get_chat_history()
                chat_history.add_message(HumanMessage(content=task))

                # Start the ReAct loop in a background task
                react_task = asyncio.create_task(self._execute_task_with_history(task))

                # Stream events while the task runs
                while not react_task.done():
                    # Check for events in the queue
                    event = await self.event_emitter.get_next_event()
                    if event:
                        if event.event_type == EventType.COMMAND_CONFIRMATION_NEEDED:
                            # Yield the confirmation event and wait for response
                            confirmation_response = yield event
                            logger.info(f"Received confirmation response: {confirmation_response.choice if confirmation_response else 'None'}")

                            # Handle the confirmation response directly
                            if confirmation_response and hasattr(self.session, '_current_confirmation') and self.session._current_confirmation:
                                execution = self.session._current_confirmation
                                result_message = await self._handle_confirmation_directly(execution, confirmation_response)

                                # Store the result for the waiting tool
                                self.session._confirmation_result = result_message

                                # Emit command executed event
                                yield ExecutionEvent(
                                    event_type=EventType.COMMAND_EXECUTED,
                                    framework="custom_async",
                                    execution=execution,
                                    content=result_message
                                )

                                # Clear the confirmation
                                self.session._current_confirmation = None
                        else:
                            # Yield other events
                            yield event

                    # Small delay to prevent busy waiting
                    await asyncio.sleep(0.05)

                # Get the final result
                final_response = await react_task

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

    async def _handle_confirmation_directly(self, execution: CommandExecution, confirmation_response: ConfirmationResponse) -> str:
        """Handle confirmation response and execute command."""
        if confirmation_response.choice == "yes":
            return await self._execute_approved_command(execution)
        elif confirmation_response.choice == "no":
            execution.update_status(CommandStatus.DENIED)
            self.session.add_execution(execution)
            return "❌ Command execution cancelled by user"
        elif confirmation_response.choice == "modify" and confirmation_response.modified_command:
            execution.command = confirmation_response.modified_command
            execution.user_modifications = confirmation_response.modified_command
            return await self._execute_approved_command(execution)
        elif confirmation_response.choice == "explain":
            execution.update_status(CommandStatus.DENIED)
            self.session.add_execution(execution)
            return f"❓ Command explanation requested: {execution.command}"
        else:
            execution.update_status(CommandStatus.DENIED)
            self.session.add_execution(execution)
            return f"❌ Unknown confirmation choice: {confirmation_response.choice}"

    async def _execute_approved_command(self, execution: CommandExecution) -> str:
        """Execute an approved command using config timeout."""
        import subprocess

        try:
            execution.update_status(CommandStatus.APPROVED)

            # Execute the command using timeout from config
            start_time = time.time()

            result = subprocess.run(
                execution.command,
                shell=True,
                cwd=execution.working_directory,
                capture_output=True,
                text=True,
                timeout=self.config.command_timeout
            )

            execution.exit_code = result.returncode
            execution.stdout = result.stdout
            execution.stderr = result.stderr
            execution.execution_time = time.time() - start_time

            if result.returncode == 0:
                execution.update_status(CommandStatus.SUCCESS)
                self.session.add_execution(execution)

                output = f"✅ Command executed successfully\n"
                output += f"Exit code: {result.returncode}\n"
                if result.stdout:
                    output += f"Output: {result.stdout[:500]}..."
                return output
            else:
                execution.update_status(CommandStatus.FAILED)
                self.session.add_execution(execution)

                output = f"❌ Command failed\n"
                output += f"Exit code: {result.returncode}\n"
                if result.stderr:
                    output += f"Error: {result.stderr[:500]}..."
                return output

        except subprocess.TimeoutExpired:
            execution.update_status(CommandStatus.TIMEOUT)
            execution.timeout_seconds = self.config.command_timeout
            self.session.add_execution(execution)
            return f"⏰ Command timed out after {self.config.command_timeout} seconds"

        except Exception as e:
            execution.update_status(CommandStatus.FAILED)
            execution.stderr = str(e)
            self.session.add_execution(execution)
            return f"❌ Command execution failed: {str(e)}"

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

            # Emit thinking event
            await self.event_emitter.emit_event(ExecutionEvent(
                event_type=EventType.LLM_START,
                framework="custom_async",
                content=f"Thinking... (iteration {iteration})"
            ))

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

                # Emit LLM end event
                await self.event_emitter.emit_event(ExecutionEvent(
                    event_type=EventType.LLM_END,
                    framework="custom_async",
                    content="AI response received",
                    tokens_used=0  # TODO: Track actual tokens
                ))

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
            action_input_match = re.search(r"Action Input:\s*(.+?)(?=\n|$)", response_text, re.DOTALL)

            if action_match and action_input_match:
                action_name = action_match.group(1).strip()
                action_input = action_input_match.group(1).strip()

                # Clean up JSON formatting
                if action_input.startswith('```json'):
                    action_input = action_input.replace('```json', '').replace('```', '').strip()

                logger.info(f"Executing action: {action_name} with input: {action_input[:100]}...")

                # Execute the action
                if action_name in self.tools:
                    tool = self.tools[action_name]

                    # Emit tool start event
                    await self.event_emitter.emit_event(ExecutionEvent(
                        event_type=EventType.TOOL_START,
                        framework="custom_async",
                        tool_name=action_name,
                        content=f"Using tool: {action_name}"
                    ))

                    # Track tool call
                    tool_call = ToolCall(
                        server_name="internal",  # Internal tools
                        tool_name=action_name,
                        arguments={"input": action_input},
                        status=ToolCallStatus.PENDING
                    )

                    try:
                        # This is where confirmations happen naturally!
                        observation = await tool.execute(action_input)

                        tool_call.result = {"output": observation}
                        tool_call.status = ToolCallStatus.SUCCESS

                        # Emit tool end event
                        await self.event_emitter.emit_event(ExecutionEvent(
                            event_type=EventType.TOOL_END,
                            framework="custom_async",
                            tool_name=action_name,
                            content=f"Tool completed: {action_name}"
                        ))

                    except ConfirmationRequired as e:
                        # Tool needs confirmation - this will be handled by the CLI
                        logger.info(f"Tool {action_name} requires confirmation: {e}")

                        # Emit confirmation event
                        if hasattr(self.session, '_current_confirmation') and self.session._current_confirmation:
                            await self.event_emitter.emit_event(ExecutionEvent(
                                event_type=EventType.COMMAND_CONFIRMATION_NEEDED,
                                framework="custom_async",
                                execution=self.session._current_confirmation,
                                content=str(e)
                            ))

                        # Wait for the confirmation to be handled and get the real result
                        for _ in range(600):  # Wait up to 60 seconds (0.1s intervals)
                            await asyncio.sleep(0.1)
                            if hasattr(self.session, '_confirmation_result'):
                                observation = self.session._confirmation_result
                                delattr(self.session, '_confirmation_result')  # Clean up
                                break
                        else:
                            # Timeout waiting for confirmation
                            observation = "❌ Confirmation timeout - command was not executed"

                        tool_call.result = {"output": observation}
                        tool_call.status = ToolCallStatus.SUCCESS

                    except Exception as e:
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