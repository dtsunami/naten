import os
from dotenv import load_dotenv
load_dotenv(".env")

import asyncio

# Agno MCP infrastructure removed - using custom MCP implementation
from datetime import timedelta
import httpx
from agno.agent import Agent, RunEvent
from agno.models.azure import AzureOpenAI
from agno.models.azure import AzureAIFoundry
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.tools.reasoning import ReasoningTools
from agno.tools.duckduckgo import DuckDuckGoTools
# Agno MCPTools removed - will implement custom MCP solution

#from agno.tools.duckduckgo import DuckDuckGoTools

import logging
logger = logging.getLogger(__name__)


from .models import (
    AgentConfig, CodeSession, CommandExecution, CommandStatus,
    LLMCall, LLMCallStatus, ToolCall, ToolCallStatus, UserResponse, da_mongo
)

from typing import Any, Dict, Optional, AsyncGenerator
from .execution_events import ExecutionEvent, ConfirmationResponse

from .config import ConfigManager, setup_logging
from .context import ContextLoader
from .execution_events import ExecutionEvent, EventType, ConfirmationResponse
from .telemetry import TelemetryManager, PerformanceTracker
from .agno_tools import (
    TodoTool, CommandTool, WebSearchTool, FileTool,
    TimeTool, PythonTool, GitTool, HttpTool
)
from .mcp_tool import mcp2tool

agno_agent_tools = [
    TodoTool(),
    CommandTool(),
    WebSearchTool(),
    FileTool(),
    TimeTool(),
    PythonTool(),
    GitTool(),
    HttpTool(),
    ReasoningTools(
            enable_think=True,
            enable_analyze=True,
            add_instructions=True,
            add_few_shot=True,
    ),
]


class AgnoAgent():
    """Agno agent with correct async HIL pattern."""

    def __init__(self, code_session: CodeSession, cwd_context: str = None):
        """Initialize the Agno agent."""

        self.code_session = code_session
        self.cwd_context = cwd_context

        logging.debug("Creating context loader")
        self.working_dir = os.getcwd()
        self.context_ldr = ContextLoader()
        self.context = self.context_ldr.load_project_context()
        self.mcp_servers = self.context_ldr.load_mcp_servers()
        logging.info(f"🔌 MCP: Loaded {len(self.mcp_servers)} MCP servers from DA.json")
        for server in self.mcp_servers:
            logging.info(f"🔌 MCP: Found server '{server.name}' at {server.url}")
        logging.debug("Initialized context loader")

        logging.debug("Creating agent config")
        self.config = ConfigManager().create_agent_config()
        logging.debug("Initialized Agent config")

        # try to connect to postgre, fallback to sqllite
        self.db_type = None
        try:
            self.db = PostgresDb(db_url=os.getenv("POSTGRES_CHAT_URL"))
            self.db_type = "postgres"
        except:
            logging.warning("Postgre init failed, failing back to sqlite :-(")
            self.db = SqliteDb(session_table="agno_agent_sessions", db_file=f"da_sessions{os.sep}sqlite.db")
            self.db = PostgresDb(db_url=os.getenv("POSTGRES_CHAT_URL"))
            self.db_type = "sqlite"


        # Load MCP tools from DA.json servers
        self.mcp_server_urls = [server.url for server in self.mcp_servers]
        mcp_tools = []
        for server in self.mcp_servers:
            url = server.url
            tool_name = getattr(server, 'name', None)
            logging.info(f"🔌 MCP: Loading {url} as '{tool_name or 'auto-named'}'")
            try:
                mcp_tool = mcp2tool(url, tool_name)
                if mcp_tool:
                    mcp_tools.append(mcp_tool)
                    actual_name = getattr(mcp_tool, 'name', 'unknown')
                    logging.info(f"✅ MCP: Successfully loaded {url} as '{actual_name}'")
                else:
                    logging.error(f"❌ MCP: Failed to load {url}")
            except Exception as e:
                logging.error(f"❌ MCP: Error loading {url}: {e}")

        # Set up tools list with MCP tools
        self.agent_tools = agno_agent_tools + mcp_tools
        logging.info(f"🔧 Agent: Loaded {len(agno_agent_tools)} built-in tools + {len(mcp_tools)} MCP tools")

        self.system_message = self._build_system_prompt()
        logging.info(f"🔧 Agent: system_mesage\n\n{self.system_message}\n\n")



        # 1. Configure the Azure OpenAI model
        

        
        #SSL_CA_CERTS = "/etc/ca-certificates"
        #self.http =  httpx.AsyncClient(verify=SSL_CA_CERTS)
        # Agno uses the AzureOpenAI class to interface with Azure's service
        #self.llm = AzureAIFoundry(
        logging.info(f"Deployment Name {self.config.deployment_name}")
        self.llm = AzureOpenAI(
            id=self.config.deployment_name,
            #id="gpt-5-mini",
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            azure_endpoint=self.config.azure_endpoint,
            max_tokens=self.config.max_tokens,
            timeout=self.config.agent_timeout,
            max_retries=self.config.max_retries,
            #http_client=self.http,
        )
        
        self.reasoning = None
        if self.config.reasoning_deployment is not None:
            logging.info(f"Reasoning Deployment {self.config.reasoning_deployment}")
            self.reasoning = AzureOpenAI(
                id=self.config.reasoning_deployment,
                api_key=self.config.api_key,
                api_version=self.config.api_version,
                azure_endpoint=self.config.azure_endpoint,
                timeout=self.config.agent_timeout,
                max_tokens=self.config.max_tokens,
                max_retries=self.config.max_retries,
            )

        self.agent = Agent(
            model=self.llm,
            reasoning_model=self.reasoning,
            db=self.db,
            session_id=str(self.code_session.id),
            system_message=self.system_message,
            markdown=True,
            reasoning=True,
            structured_outputs=False,
            add_history_to_context=True,
            add_datetime_to_context=True,
            tools=self.agent_tools,
            debug_mode=False, # Display the agent's thought process
        )

        # Confirmation handler callback
        self.confirmation_handler = None


    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        context_parts = []

        if self.code_session.project_context:
            context_parts.append(f"  + Name: {self.code_session.project_context.project_name}")
            if self.code_session.project_context.description:
                context_parts.append(f"  + Description: {self.code_session.project_context.description}")

        context_parts.append(f"\n\n📂 Working Directory: {self.code_session.working_directory}")

        # Add current directory listing if available
        if self.cwd_context:
            context_parts.append(f"{self.cwd_context}\n\n")

        context = "\n".join(context_parts) if context_parts else "No additional context available."

        return f"""🤖 You are da_code, an AI coding assistant with access to tools for command execution and file operations.

📋 PROJECT CONTEXT:
{context}

⚡ CORE INSTRUCTIONS:

1. 🔧 Use available tools to help with coding tasks - ALWAYS properly **invoke** tools, never give tool inputs back to user
2. 💻 For command execution, use execute_command tool - user confirmation is handled automatically
3. 🚀 Invoke tools as needed WITHOUT prompting user - tools that need confirmation will ask for it themselves
4. ✅ Always track and update todos to ensure you don't lose track of planned items
5. 📝 Always use proper tool arguments as specified in tool descriptions

📌 TODO MANAGEMENT:
  • 📖 Use todo_file_manager tool to track work items for complex multi-step tasks
  • 🔍 Read existing todos at start: {{"operation": "read"}}
  • ✏️  Create/update todos when planning: {{"operation": "create", "content": "markdown todo list"}}
  • ☐ Use proper markdown format with checkboxes: `- [ ] Task description`
  • ✅ Mark completed items: `- [x] Completed task`

"""



    async def arun(self, task: str, confirmation_handler: callable, tg: asyncio.TaskGroup, status_queue: asyncio.Queue, output_queue: asyncio.Queue) -> str:
        """
        Execute a task with streaming events and confirmation support.
        """
        logging.debug("Entering arun")
        self.confirmation_handler = confirmation_handler

        content_started = False


        try:
            async for run_event in self.agent.arun(task, stream=True):

                
                if not run_event.is_paused:

                    if run_event.event in [RunEvent.run_started, RunEvent.run_completed]:
                        logger.warning(f"start/stop run event: {run_event}")
                        await status_queue.put(f"Run: {run_event.event})")
                        #print(f"\nEVENT: {run_event.event}")

                    elif run_event.event in [RunEvent.tool_call_started]:
                        await status_queue.put(f"Tool Started: {run_event.tool.tool_name}({run_event.tool.tool_args})")
                        logger.debug(f"Tool Call started {run_event}")
                        #print(f"\nEVENT: {run_event.event}")
                        #print(f"TOOL CALL: {run_event.tool.tool_name}")  # type: ignore
                        #print(f"TOOL CALL ARGS: {run_event.tool.tool_args}")  # type: ignore

                    elif run_event.event in [RunEvent.tool_call_completed]:
                        logger.debug(f"Tool Call ended {run_event}")
                        await status_queue.put(f"Tool Result: {run_event.tool.tool_name} -> {run_event.tool.result}")
                        # Also send tool result to output queue for user display (consistent with confirmation flow)
                        #await output_queue.put(f"\n🔧 Tool Result:\n{run_event.tool.result}\n")
                        #print(f"\nEVENT: {run_event.event}")
                        #print(f"TOOL CALL: {run_event.tool.tool_name}")  # type: ignore
                        #print(f"TOOL CALL RESULT: {run_event.tool.result}")  # type: ignore

                    elif run_event.event in [RunEvent.run_content]:
                        if not content_started:
                            content_started = True
                        else:
                            await output_queue.put(run_event.content)
                    else:
                        logger.error(f"Unhandled run event!!! {run_event}")

                else:
                    #logger.warning(f"paused run event: {run_event}")
                    try:
                        for tool in run_event.tools_requiring_confirmation:  # type: ignore
                            logger.info(f"Tool {tool} asking for confirmation")

                            confirm_arg = f"Confirm Tool [bold blue]{tool.tool_name}({tool.tool_args})[/] requires confirmation."
                            # Ask for confirmation
                            execution = CommandExecution(
                                command=confirm_arg,
                                explanation=tool.tool_args.get("explanation", ""),
                                working_directory=tool.tool_args.get("working_directory", self.code_session.working_directory),
                                agent_reasoning=tool.tool_args.get("reasoning", ""),
                                related_files=tool.tool_args.get("related_files", [])
                            )

                            # Get user confirmation using the callback
                            logger.warning(f"🔍 EXEC: Requesting confirmation for: {execution.command}")
                            confirmation_response = await self.confirmation_handler(execution)

                            tool.confirmed = False
                            if confirmation_response.choice.lower() == "yes":
                                tool.confirmed = True

                        async for resp in self.agent.acontinue_run(run_id=run_event.run_id, updated_tools=run_event.tools, stream=True):
                            # Handle continuing run events the same way as the main loop
                            logger.debug(f"Continue run event: {resp.event}, paused: {resp.is_paused}")
                            if not resp.is_paused:
                                if resp.event in [RunEvent.tool_call_completed]:
                                    logger.info(f"Tool completed after confirmation: {resp.tool.tool_name} -> {resp.tool.result}")
                                    await status_queue.put(f"Tool Result: {resp.tool.tool_name} -> {resp.tool.result}")
                                    # CRITICAL: Also send tool result to output queue for user display
                                    await output_queue.put(f"\n🔧 Tool Result:\n{resp.tool.result}\n")
                                elif resp.event in [RunEvent.run_content]:
                                    logger.debug(f"Continue run content: {resp.content}")
                                    await output_queue.put(resp.content)
                                else:
                                    await status_queue.put(f"Continue: {resp.event}")

                    except Exception as e:
                        logger.error(f"Confirmation handling error: {type(e).__name__}: {str(e)}", exc_info=True)
                        # Re-raise to let TaskGroup handle it properly
                        raise
        finally:
            pass

    def clear_memory(self) -> None:
        """Clear agent conversation memory."""
        pass

def main():
    agent = AgnoAgent()
    print("Running the news reporter agent...")
    agent.agent.print_response("What is currently happening in the technology industry?")


if __name__ == '__main__':
    #main()
    pass
