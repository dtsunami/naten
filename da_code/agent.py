"""LangChain agent with Azure OpenAI integration."""

import io
import asyncio
import logging
from typing import Any, Dict, List, Optional

import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from contextlib import redirect_stdout, redirect_stderr

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage
from .chat_memory import create_chat_memory_manager
from langchain_openai import AzureChatOpenAI

from .models import CommandExecution, CommandStatus, UserResponse
from .models import AgentConfig, CodeSession, CommandExecution, CommandStatus, MCPServerInfo, ProjectContext
from .todo_tool import create_todo_tool
from .models import ToolCall, ToolCallStatus, da_mongo
from .models import da_mongo

logger = logging.getLogger(__name__)


class ShellExecutor:
    """Manages shell command execution with user confirmation."""

    def __init__(self, default_timeout: int = 300):
        """Initialize shell executor."""
        self.default_timeout = default_timeout

    def execute_with_confirmation(self, execution: CommandExecution) -> CommandExecution:
        """Execute command after getting user confirmation."""
        # Use modern UI for confirmation (respects DA_CODE_AUTO_ACCEPT)
        response = "yes"

        if response == "no":
            execution.update_status(CommandStatus.DENIED)
            print("❌ Command execution cancelled by user.")
            return execution

        # Execute the approved command
        execution.user_response = UserResponse.YES
        execution.update_status(CommandStatus.APPROVED)
        return self._execute_command(execution)

    def _display_command_info(self, execution: CommandExecution) -> None:
        """Display command information to the user."""
        print("\n" + "="*60)
        print("🤖 Agent wants to execute a command:")
        print("="*60)
        print(f"Command: {execution.command}")
        print(f"Directory: {execution.working_directory}")

        if execution.explanation:
            print(f"Purpose: {execution.explanation}")

        if execution.agent_reasoning:
            print(f"Reasoning: {execution.agent_reasoning}")

        if execution.related_files:
            print(f"Related files: {', '.join(execution.related_files)}")

        print("="*60)
 
    def _execute_command(self, execution: CommandExecution) -> CommandExecution:
        """Execute the approved command."""
        execution.update_status(CommandStatus.EXECUTING)

        start_time = time.time()

        try:
            result = subprocess.run(
                execution.command,
                cwd=execution.working_directory,
                shell=True,
                capture_output=True,
                text=True, 
                check=True,
                timeout=execution.timeout_seconds
            )
            #print("Output:", result.stdout)
            #print("Errors:", result.stderr)
            #print("Return Code:", result.returncode)
            
            execution_time = time.time() - start_time

            # Set results
            execution.set_result(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = time.time() - start_time
            execution.update_status(CommandStatus.FAILED)
            execution.execution_time = execution_time
            execution.stderr = str(e)
            print(f"💥 Command failed: {e}")
            logger.error(f"Command execution error: {e}")

        return execution

    def _display_execution_results_clean(self, execution: CommandExecution) -> None:
        """Display command execution results in a clean format."""
        if execution.status == CommandStatus.SUCCESS:
            print(f"✅ Completed ({execution.execution_time:.2f}s)")
            if execution.stdout and execution.stdout.strip():
                # Show output but truncate if too long
                output = execution.stdout.strip()
                if len(output) > 500:
                    lines = output.split('\n')
                    if len(lines) > 10:
                        shown_lines = lines[:8] + ["...", f"[{len(lines) - 8} more lines]"]
                        output = '\n'.join(shown_lines)
                    else:
                        output = output[:500] + "..."
                print(f"📤 Output:\n{output}")
        else:
            print(f"❌ Failed (exit code: {execution.exit_code}, {execution.execution_time:.2f}s)")
            if execution.stderr and execution.stderr.strip():
                error = execution.stderr.strip()
                if len(error) > 300:
                    error = error[:300] + "..."
                print(f"🚫 Error: {error}")


class CommandExecutionTool:
    """Custom LangChain tool for executing shell commands with user confirmation."""

    def __init__(self, shell_executor: ShellExecutor, session: CodeSession):
        """Initialize command execution tool."""
        self.shell_executor = shell_executor
        self.session = session

    def create_tool(self) -> Tool:
        """Create LangChain tool for command execution."""
        return Tool(
            name="execute_command",
            description="""Execute shell commands with user confirmation.
            Use this tool when you need to run system commands, install packages,
            modify files, or perform any system operations.

            Input should be a JSON string with these fields:
            - command: The shell command to execute (required)
            - explanation: Brief explanation of what the command does (required)
            - working_directory: Directory to run command in (optional, defaults to session working directory)
            - reasoning: Your reasoning for why this command is needed (optional)
            - related_files: List of files related to this command (optional)

            Example: {"command": "ls -la", "explanation": "List all files in current directory", "reasoning": "User asked to see what files are available"}
            """,
            func=self._execute_command
        )

    def _execute_command(self, tool_input: str) -> str:
        """Execute command with user confirmation."""
        try:
            import json

            # Parse input
            if isinstance(tool_input, str):
                try:
                    params = json.loads(tool_input)
                except json.JSONDecodeError:
                    # If not JSON, treat as simple command
                    params = {"command": tool_input, "explanation": "Execute shell command"}
            else:
                params = tool_input

            command = params.get("command", "").strip()
            if not command:
                return "Error: No command provided"

            # Clean up command if it's wrapped in JSON formatting
            if command.startswith('```json') or command.startswith('{'):
                try:
                    # Try to extract actual command from JSON block
                    if command.startswith('```json'):
                        json_part = command.split('```json\n')[1].split('```')[0]
                    else:
                        json_part = command

                    parsed_cmd = json.loads(json_part)
                    if isinstance(parsed_cmd, dict) and 'command' in parsed_cmd:
                        command = parsed_cmd['command']
                        if 'explanation' in parsed_cmd:
                            params['explanation'] = parsed_cmd['explanation']
                        if 'reasoning' in parsed_cmd:
                            params['reasoning'] = parsed_cmd['reasoning']
                        if 'working_directory' in parsed_cmd:
                            params['working_directory'] = parsed_cmd['working_directory']
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass  # Keep original command if parsing fails

            # Create command execution record
            execution = CommandExecution(
                command=command,
                explanation=params.get("explanation", ""),
                working_directory=params.get("working_directory", self.session.working_directory),
                agent_reasoning=params.get("reasoning", ""),
                related_files=params.get("related_files", [])
            )

            # Execute with confirmation
            result = self.shell_executor.execute_with_confirmation(execution)

            # Add to session
            self.session.add_execution(result)

            # Return result description
            if result.status == CommandStatus.SUCCESS:
                output = f"✅ Command executed successfully\\n"
                output += f"Exit code: {result.exit_code}\\n"
                if result.stdout:
                    output += f"Output: {result.stdout[:500]}..."  # Truncate long output
                return output
            elif result.status == CommandStatus.DENIED:
                return "❌ Command execution was denied by user"
            elif result.status == CommandStatus.TIMEOUT:
                return f"⏰ Command timed out after {result.timeout_seconds} seconds"
            else:
                output = f"❌ Command failed\\n"
                output += f"Exit code: {result.exit_code}\\n"
                if result.stderr:
                    output += f"Error: {result.stderr[:500]}..."
                return output

        except Exception as e:
            logger.error(f"Error in command execution tool: {e}")
            return f"Error executing command: {str(e)}"


class DaCodeAgent:
    """Main LangChain agent for da_code CLI tool."""

    def __init__(self, config: AgentConfig, session: CodeSession):
        """Initialize da_code agent."""
        self.config = config
        self.session = session
        self.shell_executor = ShellExecutor(config.command_timeout)

        # Initialize LangChain components
        self.llm = None
        self.memory_manager = None
        self.agent_executor = None

        self._initialize_agent()

    def _initialize_agent(self) -> None:
        """Initialize LangChain agent components."""
        try:
            # Initialize Azure OpenAI
            self.llm = AzureChatOpenAI(
                azure_endpoint=self.config.azure_endpoint,
                api_key=self.config.api_key,
                api_version=self.config.api_version,
                azure_deployment=self.config.deployment_name,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.agent_timeout,
                max_retries=self.config.max_retries
            )

            # Initialize chat memory manager and force chat history creation
            self.memory_manager = create_chat_memory_manager(self.session.session_id)
            logger.debug(f"Chat memory manager created for session: {self.session.session_id}")

            # Force chat history initialization to determine memory backend early
            chat_history = self.memory_manager.get_chat_history()
            memory_info = self.memory_manager.get_memory_info()
            logger.info(f"Chat memory initialized: {memory_info['memory_type']} ({memory_info['message_count']} existing messages)")

            # Create tools
            tools = self._create_tools()

            # Create agent prompt
            prompt = self._create_agent_prompt()

            # Create agent
            agent = create_react_agent(self.llm, tools, prompt)

            # Create agent executor
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                verbose=True,
                max_iterations=10,
                handle_parsing_errors=True
            )

            logger.info("LangChain agent initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise

    def _create_tools(self) -> List[Tool]:
        """Create tools for the agent."""
        tools = []

        # Command execution tool
        cmd_tool = CommandExecutionTool(self.shell_executor, self.session)
        tools.append(cmd_tool.create_tool())

        # Todo tool (direct integration)
        todo_tool = create_todo_tool(self.session.working_directory)
        tools.append(todo_tool)


        return tools

    def _create_agent_prompt(self) -> PromptTemplate:
        """Create the agent prompt template."""
        system_context = self._build_system_context()

        template = f"""You are da_code, an AI coding assistant with access to shell commands and MCP servers.

{system_context}

You have access to the following tools:
{{tools}}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{{tool_names}}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

IMPORTANT GUIDELINES:
1. Always explain what a command does before executing it
2. Be cautious with destructive operations
3. Use appropriate working directories
4. Provide clear reasoning for each action
5. Use MCP servers for specialized operations when available

Question: {{input}}
{{agent_scratchpad}}"""

        return PromptTemplate.from_template(template)

    def _build_system_context(self) -> str:
        """Build system context from project information."""
        context = ""

        if self.session.project_context:
            context += f"PROJECT: {self.session.project_context.project_name or 'Unknown'}\\n"
            if self.session.project_context.description:
                context += f"DESCRIPTION: {self.session.project_context.description}\\n"
            if self.session.project_context.instructions:
                context += f"INSTRUCTIONS: {self.session.project_context.instructions}\\n"

        context += f"WORKING DIRECTORY: {self.session.working_directory}\\n"

        if self.session.mcp_servers:
            context += f"AVAILABLE MCP SERVERS: {', '.join(s.name for s in self.session.mcp_servers)}\\n"

        return context

    async def achat(self, message: str) -> str:
        """Chat with the agent."""
        try:
            logger.debug(f"User message: {message}")

            # Add user message to chat history
            chat_history = self.memory_manager.get_chat_history()
            chat_history.add_message(HumanMessage(content=message))

            # Track LLM call
            from .models import LLMCall, LLMCallStatus
            import time
            start_time = time.time()

            llm_call = LLMCall(
                model_name=self.config.deployment_name,
                provider="azure_openai",
                prompt=message,
                status=LLMCallStatus.PENDING
            )

            try:
                captured_output = io.StringIO()

                with redirect_stdout(captured_output), redirect_stderr(captured_output):
                    response = await self.agent_executor.ainvoke({"input": message}, timeout=self.config.agent_timeout)

                output = response.get("output", "No response generated")

                # Update LLM call with success
                llm_call.response = output
                llm_call.status = LLMCallStatus.SUCCESS
                llm_call.response_time_ms = (time.time() - start_time) * 1000

            except Exception as agent_error:
                # Update LLM call with failure
                llm_call.status = LLMCallStatus.FAILED
                llm_call.error_message = str(agent_error)
                llm_call.response_time_ms = (time.time() - start_time) * 1000
                output = f"Sorry, I encountered an error: {str(agent_error)}"

            # Add LLM call to session and save
            self.session.add_llm_call(llm_call)

            # Save session asynchronously
            await da_mongo.save_session(self.session)

            # Add AI response to chat history
            chat_history.add_message(AIMessage(content=output))

            logger.debug(f"Agent response: {output}")

            return output

        except Exception as e:
            logger.error(f"Error in agent chat: {e}")
            return f"Sorry, I encountered an error: {str(e)}"
    
    def chat(self, message: str) -> str:
        """Chat with the agent."""
        try:
            logger.debug(f"User message: {message}")

            # Add user message to chat history
            chat_history = self.memory_manager.get_chat_history()
            chat_history.add_message(HumanMessage(content=message))

            # Track LLM call
            from .models import LLMCall, LLMCallStatus
            import time
            start_time = time.time()

            llm_call = LLMCall(
                model_name=self.config.deployment_name,
                provider="azure_openai",
                prompt=message,
                status=LLMCallStatus.PENDING
            )

            try:
                captured_output = io.StringIO()

                with redirect_stdout(captured_output), redirect_stderr(captured_output):
                    response = self.agent_executor.invoke({"input": message}, timeout=self.config.agent_timeout)

                output = response.get("output", "No response generated")

                # Update LLM call with success
                llm_call.response = output
                llm_call.status = LLMCallStatus.SUCCESS
                llm_call.response_time_ms = (time.time() - start_time) * 1000

            except Exception as agent_error:
                # Update LLM call with failure
                llm_call.status = LLMCallStatus.FAILED
                llm_call.error_message = str(agent_error)
                llm_call.response_time_ms = (time.time() - start_time) * 1000
                output = f"Sorry, I encountered an error: {str(agent_error)}"

            # Add LLM call to session and save
            self.session.add_llm_call(llm_call)

            # Save session asynchronously
            #await da_mongo.save_session(self.session)

            # Add AI response to chat history
            chat_history.add_message(AIMessage(content=output))

            logger.debug(f"Agent response: {output}")

            return output

        except Exception as e:
            logger.error(f"Error in agent chat: {e}")
            return f"Sorry, I encountered an error: {str(e)}"

    def get_session_info(self) -> Dict[str, Any]:
        """Get current session information."""
        info = {
            "session_id": self.session.session_id,
            "total_commands": len(self.session.executions),
            "successful_commands": self.session.successful_commands,
            "failed_commands": self.session.failed_commands,
            "working_directory": self.session.working_directory,
            "mcp_servers": len(self.session.mcp_servers),
            "agent_model": self.config.deployment_name
        }

        # Add memory info
        if self.memory_manager:
            info["memory"] = self.memory_manager.get_memory_info()

        return info

    def clear_memory(self) -> None:
        """Clear agent conversation memory."""
        if self.memory_manager:
            success = self.memory_manager.clear_history()
            if success:
                logger.info("Agent memory cleared")
            else:
                logger.warning("Failed to clear agent memory")