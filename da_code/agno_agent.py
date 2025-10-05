import os
from dotenv import load_dotenv
load_dotenv(".env")

import asyncio
import httpx
from agno.agent import Agent, RunEvent
from agno.models.azure import AzureOpenAI
from agno.models.azure import AzureAIFoundry
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.tools.reasoning import ReasoningTools
from agno.tools.duckduckgo import DuckDuckGoTools
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
    handle_todo_operation, execute_command, web_search, file_tool,
    file_search, current_time, python_executor, git_operations, http_fetch
)

agno_agent_tools = [
    handle_todo_operation,
    execute_command,
    file_tool,
    current_time,
    python_executor,
    git_operations,
    http_fetch,
    DuckDuckGoTools(),
    ReasoningTools(
            enable_think=True,
            enable_analyze=True,
            add_instructions=True,
            add_few_shot=True,
    ),
]


class AgnoAgent():
    """Agno agent with correct async HIL pattern."""

    def __init__(self, code_session: CodeSession):
        """Initialize the Agno agent."""
        
        self.code_session = code_session

        logging.debug("Creating context loader")
        self.working_dir = os.getcwd()
        self.context_ldr = ContextLoader()
        self.context = self.context_ldr.load_project_context()
        mcp_servers = self.context_ldr.load_mcp_servers()
        logging.debug("Initialized context loader")

        logging.debug("Creating agent config")
        self.config = ConfigManager().create_agent_config()
        logging.debug("Initialized Agent config")

        # 1. Configure the Azure OpenAI model
        
        SSL_CA_CERTS = "/etc/ca-certificates"
        self.http =  httpx.AsyncClient(verify=SSL_CA_CERTS)
        # Agno uses the AzureOpenAI class to interface with Azure's service
        #self.llm = AzureAIFoundry(
        self.llm = AzureOpenAI(
            #id=self.config.deployment_name,
            id="gpt-5-mini",
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            azure_endpoint=self.config.azure_endpoint,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            timeout=self.config.agent_timeout,
            max_retries=self.config.max_retries,
            #http_client=self.http,
        )
        
        self.reasoning = AzureAIFoundry(
            id="gpt-5-mini", #TODO, add reasoning model to agent config
            api_key=self.config.api_key,
            azure_endpoint=self.config.azure_endpoint,
            timeout=self.config.agent_timeout,
            max_retries=self.config.max_retries,
            http_client=self.http,
            
        )
        # try to connect to postgre, fallback to sqllite
        try:
            db = PostgresDb(db_url=os.getenv("POSTGRES_CHAT_URL"))
        except:
            logging.warning("Postgre init failed, failing back to sqlite :-(")
            db = SqliteDb(session_table="agno_agent_sessions", db_file=f"da_sessions{os.sep}sqlite.db")

        self.agent = Agent(
            model=self.llm,
            #reasoning_model=self.reasoning,
            db=db,
            session_id=str(code_session.id),
            description=self._build_system_prompt(),
            markdown=True,
            #reasoning=True,
            add_history_to_context=True,
            add_datetime_to_context=True,
            tools=agno_agent_tools,
            debug_mode=False, # Display the agent's thought process
        )

        # Confirmation handler callback
        self.confirmation_handler = None

        logger.info("Agno agent initialized successfully")

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the agent."""
        context_parts = []

        if self.code_session.project_context:
            context_parts.append(f"Project: {self.code_session.project_context.project_name}")
            if self.code_session.project_context.description:
                context_parts.append(f"Description: {self.code_session.project_context.description}")

        context_parts.append(f"Working Directory: {self.code_session.working_directory}")
        context = "\n".join(context_parts) if context_parts else "No additional context available."

        return f"""You are da_code, an AI coding assistant with access to tools for command execution and file operations.

CONTEXT:
{context}

INSTRUCTIONS:
1. Use the available tools to help users with their coding tasks
2. For command execution, use the execute_command tool - user confirmation is handled automatically
4. Be thorough but efficient in your approach
5. Provide clear explanations for your actions
6. Always use proper tool arguments as specified in the tool descriptions

TODO MANAGEMENT:
- Use the todo_file_manager tool to track work items for complex multi-step tasks
- Read existing todos at the start: {{"operation": "read"}}
- Create/update todos when planning work: {{"operation": "create", "content": "markdown todo list"}}
- Use proper markdown format with checkboxes: `- [ ] Task description`
- Mark completed items: `- [x] Completed task`

"""

    async def arun(self, task: str, confirmation_handler: callable, tg: asyncio.TaskGroup, status_queue: asyncio.Queue, output_queue: asyncio.Queue) -> str:
        """
        Execute a task with streaming events and confirmation support.
        """
        logging.debug("Entering arun")
        self.confirmation_handler = confirmation_handler

        content_started = False

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

    def get_session_info(self) -> Dict[str, Any]:
        """Get current session information."""
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
