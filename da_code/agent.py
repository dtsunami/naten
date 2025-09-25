"""LangChain agent with Azure OpenAI integration."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import Tool
from .chat_memory import create_chat_memory_manager
from langchain_openai import AzureChatOpenAI

from .models import AgentConfig, CodeSession, CommandExecution, CommandStatus, MCPServerInfo, ProjectContext
from .shell import ShellExecutor

logger = logging.getLogger(__name__)


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
            result = asyncio.run(self.shell_executor.execute_with_confirmation(execution))

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


class MCPTool:
    """Tool for interacting with MCP servers."""

    def __init__(self, mcp_servers: List[MCPServerInfo], session: CodeSession):
        """Initialize MCP tool."""
        self.mcp_servers = mcp_servers
        self.session = session

    def create_tool(self) -> Tool:
        """Create LangChain tool for MCP operations."""
        return Tool(
            name="call_mcp_server",
            description="""Call tools on MCP servers for specialized operations.

            Available MCP servers and their tools:
            """ + self._format_mcp_servers() + """

            Input should be a JSON string with these fields:
            - server: Name of MCP server to call (required)
            - tool: Name of tool to call on the server (required)
            - arguments: Dictionary of arguments for the tool (required)

            Example: {"server": "fileio", "tool": "read_file", "arguments": {"path": "/path/to/file"}}
            """,
            func=self._call_mcp_server
        )

    def _format_mcp_servers(self) -> str:
        """Format MCP servers list for tool description."""
        if not self.mcp_servers:
            return "No MCP servers available"

        formatted = ""
        for server in self.mcp_servers:
            formatted += f"\\n- {server.name}: {server.description}"
            if server.tools:
                formatted += f" (tools: {', '.join(server.tools)})"

        return formatted

    async def _call_mcp_server_async(self, tool_input: str) -> str:
        """Call MCP server tool - async version."""
        try:
            import json

            params = json.loads(tool_input)
            server_name = params.get("server")
            tool_name = params.get("tool")
            arguments = params.get("arguments", {})

            # Find server
            server = next((s for s in self.mcp_servers if s.name == server_name), None)
            if not server:
                return f"Error: MCP server '{server_name}' not found"

            # Make MCP call
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            result = await self._make_mcp_request(server.url, payload)

            # Save tool call to session
            from .models import ToolCall, ToolCallStatus, da_mongo
            tool_call = ToolCall(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                result={"response": result},
                status=ToolCallStatus.SUCCESS
            )
            self.session.add_tool_call(tool_call)

            # Save session asynchronously
            await da_mongo.save_session(self.session)

            return result

        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return f"Error calling MCP server: {str(e)}"

    def _call_mcp_server(self, tool_input: str) -> str:
        """Call MCP server tool - sync wrapper for LangChain."""
        try:
            # Use thread pool executor to run async code in a separate thread
            import concurrent.futures

            def run_async_in_thread():
                """Run async function in new thread with its own event loop."""
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(self._call_mcp_server_async(tool_input))
                finally:
                    loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async_in_thread)
                return future.result(timeout=30)  # 30 second timeout

        except Exception as e:
            logger.error(f"Error in MCP call wrapper: {e}")
            return f"Error calling MCP server: {str(e)}"

    async def _make_mcp_request(self, url: str, payload: Dict[str, Any]) -> str:
        """Make async request to MCP server."""
        try:
            import json
            import aiohttp
            async with aiohttp.ClientSession() as session:
                mcp_url = f"{url.rstrip('/')}/mcp"
                async with session.post(mcp_url, json=payload, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get('result', {})
                        return json.dumps(result, indent=2)
                    else:
                        return f"MCP server error: HTTP {response.status}"

        except Exception as e:
            return f"MCP request failed: {str(e)}"


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
                timeout=self.config.timeout,
                max_retries=self.config.max_retries
            )

            # Initialize chat memory manager
            self.memory_manager = create_chat_memory_manager(self.session.session_id)

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
        from .todo_tool import create_todo_tool
        todo_tool = create_todo_tool(self.session.working_directory)
        tools.append(todo_tool)

        # MCP server tool (excluding todo since we have direct integration)
        if self.session.mcp_servers:
            # Filter out todo MCP server since we have direct integration
            mcp_servers = [s for s in self.session.mcp_servers if s.name != 'todo']
            if mcp_servers:
                mcp_tool = MCPTool(mcp_servers, self.session)
                tools.append(mcp_tool.create_tool())

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

    async def chat(self, message: str) -> str:
        """Chat with the agent."""
        try:
            logger.debug(f"User message: {message}")

            # Add user message to chat history
            from langchain_core.messages import HumanMessage, AIMessage
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
                # Suppress LangChain verbose output during execution
                import io
                from contextlib import redirect_stdout, redirect_stderr

                # Capture stdout/stderr to suppress chain traces
                captured_output = io.StringIO()

                with redirect_stdout(captured_output), redirect_stderr(captured_output):
                    # Run agent with timeout
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.agent_executor.invoke,
                            {"input": message}
                        ),
                        timeout=60.0  # 60 second timeout
                    )

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
            from .models import da_mongo
            await da_mongo.save_session(self.session)

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