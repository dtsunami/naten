import os
from dotenv import load_dotenv
load_dotenv(".env")

import asyncio
from pathlib import Path

# Agno MCP infrastructure removed - using custom MCP implementation
from datetime import timedelta
import httpx
from agno.agent import Agent, RunEvent
from agno.models.azure import AzureOpenAI
from agno.models.openai import OpenAIResponses
from agno.models.azure import AzureAIFoundry
from agno.db.mongo import MongoDb
from agno.db.postgres import PostgresDb
from pymongo import MongoClient
from agno.db.sqlite import SqliteDb
from agno.tools.reasoning import ReasoningTools
from agno.tools.duckduckgo import DuckDuckGoTools
# Agno MCPTools removed - will implement custom MCP solution

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
    TodoTool, CommandTool, FileTool, HttpTool
)
from .mcp_tool import mcp2tool
from .context_telemetry import ModelStatsTracker, wrap_model_with_interceptor

agno_agent_tools = [
    TodoTool(),
    CommandTool(),
    FileTool(),
    HttpTool(),
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
            self.db_type = "postgre"
        except Exception as e:
            logging.warning(f"Postgres init failed, falling back to sqlite: {e}")
            self.db = SqliteDb(session_table="agno_agent_sessions", db_file=f".da{os.sep}sqlite.db")
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
                    logging.error(f"� MCP: Failed to load {url}")
            except Exception as e:
                logging.error(f"� MCP: Error loading {url}: {e}")

        # Set up tools list with MCP tools
        self.agent_tools = agno_agent_tools + mcp_tools
        logging.info(f"🔧 Agent: Loaded {len(agno_agent_tools)} built-in tools + {len(mcp_tools)} MCP tools")

        # Ensure the LLM-facing tool descriptions prefer toolkit-level metadata
        # rather than the bound function docstrings defined on instances. Some
        # Agno Toolkit integrations pick the callable's __doc__ at registration
        # time; to make toolkit metadata primary we copy the class docstring
        # (first line) onto the class member functions before creating the
        # Agent. This ensures the tool description comes from the Toolkit
        # metadata and not an instance-level function docstring.
        def _prefer_toolkit_metadata(tool_obj):
            try:
                cls = tool_obj.__class__
                toolkit_doc = (cls.__doc__ or '').strip().splitlines()[0]
                if not toolkit_doc:
                    return
                for attr in dir(cls):
                    if attr.startswith('_'):
                        continue
                    try:
                        member = getattr(cls, attr, None)
                        if member and callable(member):
                            # Only update if member has a docstring or no docstring
                            orig = (getattr(member, '__doc__', '') or '').strip().splitlines()[0]
                            new = toolkit_doc if toolkit_doc else orig
                            try:
                                setattr(member, '__doc__', new)
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass

        for t in self.agent_tools:
            try:
                _prefer_toolkit_metadata(t)
            except Exception:
                pass

        self.system_message = self._build_system_prompt()
        logging.warning(f"🔧 Agent: system_mesage\n\n{self.system_message}\n\n")

        logging.info(f"Deployment Name {self.config.deployment_name}")

        # Create central tracker for all models
        self.model_stats_tracker = ModelStatsTracker()
        logging.info("📊 Created ModelStatsTracker for multi-model telemetry")

        # Create base model
        base_llm = AzureOpenAI(
            id=self.config.deployment_name,
            api_key=self.config.api_key,
            api_version=self.config.api_version,
            azure_endpoint=self.config.azure_endpoint,
            max_tokens=self.config.max_tokens,
            timeout=self.config.agent_timeout,
            max_retries=self.config.max_retries,
        )

        # Wrap model with interceptor to log messages sent to LLM
        self.llm = wrap_model_with_interceptor(
            base_llm,
            max_tokens=self.config.max_tokens or 128000,
            model_type='main',
            stats_tracker=self.model_stats_tracker
        )
        logging.info("✅ Main model wrapped with interceptor for context telemetry")

        self.reasoning = None
        if self.config.reasoning_deployment is not None:
            logging.info(f"Reasoning Deployment {self.config.reasoning_deployment}")
            base_reasoning = AzureOpenAI(
                id=self.config.reasoning_deployment,
                api_key=self.config.api_key,
                api_version=self.config.api_version,
                azure_endpoint=self.config.azure_endpoint,
                timeout=self.config.agent_timeout,
                max_tokens=self.config.max_tokens,
                max_retries=self.config.max_retries,
            )
            # Wrap reasoning model with interceptor
            self.reasoning = wrap_model_with_interceptor(
                base_reasoning,
                max_tokens=self.config.max_tokens or 128000,
                model_type='reasoning',
                stats_tracker=self.model_stats_tracker
            )
            logging.info("✅ Reasoning model wrapped with interceptor for context telemetry")

        # Build instructions list from AGENTS.md + defaults
        default_instructions = [
            "🔧 Use available tools to help with coding tasks - ALWAYS properly **invoke** tools, never give tool inputs back to user",
            "💻 For command execution, use execute_command tool - user confirmation is handled automatically",
            "🚀 Invoke tools as needed WITHOUT reprompting user",
            "✅ Always track and update todos to ensure you don't lose track of planned items",
            "📝 Always use proper tool arguments as specified in tool descriptions",
            "✍️ Always use the replace_text tool to update/edit files and re-read the file back after edit to ensure it worked properly!",
        ]

        # Merge with project-specific instructions from AGENTS.md
        self.instructions = default_instructions.copy()
        if self.code_session.project_context and self.code_session.project_context.instructions:
            self.instructions.append("")  # Blank separator
            self.instructions.append("📋 PROJECT-SPECIFIC INSTRUCTIONS:")
            self.instructions.extend(self.code_session.project_context.instructions)
            logging.info(f"📝 Loaded {len(self.code_session.project_context.instructions)} project-specific instructions from AGENTS.md")
            logging.info(f"📝 Loaded {' | '.join(self.code_session.project_context.instructions)} project-specific instructions from AGENTS.md")

        self.agent = Agent(
            name="da_code",
            model=self.llm,
            reasoning_model=self.reasoning,
            db=self.db,
            session_id=str(self.code_session.id),
            description=self.system_message,
            instructions=self.instructions,
            markdown=True,
            reasoning=self.reasoning is not None,
            enable_session_summaries=True,
            add_session_summary_to_context=True,
            enable_user_memories=True,
            add_memories_to_context=True,
            structured_outputs=False,
            add_history_to_context=True,
            num_history_runs=12,
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

        context_parts.append('''\n⚡ SYSTEM MESSAGE:

You are a semi-autonomous coding agent that helps users create coding projects, debug issues and edit files.
Always use available tools and if you encounter an error show the input you supplied to the tool and the output you got.
Don't prompt the user before running tools, tools will ask user for confirmation themselves if it is needed.
''')

        context_parts.append(f"\n📂 Working Directory: {self.code_session.working_directory}\n")
        # Add current directory listing if available
        if self.cwd_context:
            context_parts.append(self.cwd_context)

        # Always include TODO.md contents if present in the project root so it's
        # available to the agent and shown in the context overlay.
        try:
            todo_path = Path(self.code_session.working_directory) / "todo.md"
            if todo_path.exists():
                try:
                    todo_text = todo_path.read_text(encoding='utf-8')
                except Exception:
                    todo_text = todo_path.read_text(encoding='utf-8', errors='ignore')
                context_parts.append("\n📌 TODO.md:\n" + todo_text)
        except Exception as e:
            logging.debug(f"Could not read todo.md: {e}")
        
        context = "\n".join(context_parts) if context_parts else "No additional context available."

        return f"""🤖 You are da_code, an AI coding assistant with access to tools for command execution and file operations.

📋 PROJECT CONTEXT:

{context}
"""


    async def arun(self, task: str, confirmation_handler: callable, status_queue: asyncio.Queue, output_queue: asyncio.Queue, user_id: str="user") -> str:
        """Execute a task with streaming events and persistent run until completion (handles multiple confirmations)."""
        logging.debug("Entering arun")
        self.confirmation_handler = confirmation_handler
        content_started = False
        self.active_run_id = None

        async def process_stream(stream):
            nonlocal content_started
            async for run_event in stream:
                if self.active_run_id is None and hasattr(run_event, 'run_id'):
                    self.active_run_id = run_event.run_id

                #logger.warning(f"Run Event: {run_event}")


                if not run_event.is_paused:
                    event_name = getattr(run_event, 'event', None)

                    if event_name in ['PreHookStarted', 'PreHookCompleted', 'PostHookStarted', 'PostHookCompleted']:
                        # Handle pre/post hook events silently (telemetry is in the hooks themselves)
                        logger.debug(f"Hook event: {event_name}")
                        continue

                    if run_event.event in [RunEvent.run_started, RunEvent.run_completed, RunEvent.run_cancelled]:
                        await status_queue.put(f"Run: {run_event.event})")
                        if run_event.event == RunEvent.run_completed:
                            return True
                        elif run_event.event == RunEvent.run_cancelled:
                            logger.info(f"Run cancelled event received for run_id: {self.active_run_id}")
                            return ('cancelled', None)
                    elif run_event.event in [RunEvent.reasoning_started]:
                        await status_queue.put("Reasoning: Starting...")
                    elif run_event.event in [RunEvent.reasoning_step]:
                        # Update status with reasoning progress
                        reasoning_content = getattr(run_event, 'reasoning_content', '')
                        if reasoning_content:
                            # Show truncated reasoning content in status
                            truncated = reasoning_content[:50] + "..." if len(reasoning_content) > 50 else reasoning_content
                            await status_queue.put(f"Reasoning: {truncated}")
                        else:
                            await status_queue.put("Reasoning: Thinking...")
                    elif run_event.event in [RunEvent.reasoning_completed]:
                        await status_queue.put("Reasoning: Complete")
                    elif run_event.event in [RunEvent.tool_call_started]:
                        await status_queue.put(f"Tool Started: {run_event.tool.tool_name}({run_event.tool.tool_args})")
                        # Send tool call metric
                        await status_queue.put({
                            'type': 'tool_call',
                            'tool_name': run_event.tool.tool_name
                        })
                    elif run_event.event in [RunEvent.tool_call_completed]:
                        await status_queue.put(f"Tool Done: {run_event.tool.tool_name}")
                        #await output_queue.put(f"\n🔧 Tool Result:\n{run_event.tool.result}\n")
                    elif run_event.event in [RunEvent.run_content]:
                        await status_queue.put(f"Streaming Content: ...")
                        if content_started:
                            await output_queue.put(run_event.content)
                        else:
                            content_started = True
                    else:
                        logger.error(f"Unhandled run event!!! {run_event}")
                else:
                    for tool in run_event.tools_requiring_confirmation:  # type: ignore
                        confirm_arg = f"Confirm Tool [bold blue]{tool.tool_name}({tool.tool_args})[/] requires confirmation."
                        execution = CommandExecution(
                            command=confirm_arg,
                            explanation=tool.tool_args.get("explanation", ""),
                            working_directory=tool.tool_args.get("working_directory", self.code_session.working_directory),
                            agent_reasoning=tool.tool_args.get("reasoning", ""),
                            related_files=tool.tool_args.get("related_files", [])
                        )
                        confirmation_response = await self.confirmation_handler(execution)
                        tool.confirmed = confirmation_response.choice.lower() == "yes"
                    # replace stream with continuation stream
                    return ('continue', run_event.tools)
            return ('done', None)

        # main persistent loop
        run_stream = self.agent.arun(task, stream=True, user_id=user_id)
        while True:
            result = await process_stream(run_stream)
            if result is True or (isinstance(result, tuple) and result[0] in ['done', 'cancelled']):
                break
            elif isinstance(result, tuple) and result[0] == 'continue':
                run_stream = self.agent.acontinue_run(run_id=self.active_run_id, updated_tools=result[1], stream=True, user_id=user_id)
        


def main():
    code_session = CodeSession(
        working_directory=".",
        project_context="News project",
        mcp_servers=[],
    )
    agent = AgnoAgent(code_session)
    print("Running the news reporter agent...")
    agent.agent.print_response("What is currently happening in the technology industry?")


if __name__ == '__main__':
    pass
