
"""Main CLI entry point for da_code tool."""

import argparse
import asyncio
import logging
import os
import sys
import time

import random
from typing import List
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.prompt import Prompt
from rich.console import Console
from rich.status import Status

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from .agent import DaCodeAgent
from .config import ConfigManager, setup_logging
from .context import ContextLoader
from .models import CodeSession

logger = logging.getLogger(__name__)

# Global console for clean interaction
console = Console()


class RealTimeAgentCallbackHandler(AsyncCallbackHandler):
    """Async callback handler for real-time agent monitoring."""

    def __init__(self, status_interface):
        self.status_interface = status_interface
        self.interrupt_requested = False

    async def on_llm_start(self, serialized, prompts, **kwargs):
        """Called when LLM starts."""
        self.status_interface.llm_calls += 1
        self.status_interface.update_status("Calling Azure OpenAI...")

    async def on_llm_end(self, response: LLMResult, **kwargs):
        """Called when LLM ends - track token usage."""
        if hasattr(response, 'llm_output') and response.llm_output:
            token_usage = response.llm_output.get('token_usage', {})
            tokens = token_usage.get('total_tokens', 0)
            if tokens > 0:
                self.status_interface.total_tokens += tokens
        self.status_interface.update_status("Processing response...")

    async def on_tool_start(self, serialized, input_str, **kwargs):
        """Called when tool starts."""
        tool_name = serialized.get('name', 'Unknown')
        self.status_interface.tool_calls += 1
        self.status_interface.update_status(f"Using tool: {tool_name}")

    async def on_tool_end(self, output, **kwargs):
        """Called when tool ends."""
        self.status_interface.update_status("Tool completed")

    async def on_agent_action(self, action, **kwargs):
        """Called when agent takes an action."""
        self.status_interface.update_status(f"Agent action: {action.tool}")

    async def on_agent_finish(self, finish, **kwargs):
        """Called when agent finishes."""
        self.status_interface.update_status("Finalizing response...")

    async def on_text(self, text: str, **kwargs):
        """Called on arbitrary text - can be used for streaming."""
        # This could be used for token-by-token streaming
        pass

    def request_interrupt(self):
        """Request interruption of agent execution."""
        self.interrupt_requested = True


class SimpleStatusInterface:
    """Simple status interface with Rich spinner and agent insights."""

    def __init__(self):
        self.start_time = None
        self.current_status = None
        self.llm_calls = 0
        self.tool_calls = 0
        self.total_tokens = 0
        self.callback_handler = None

    def start_execution(self, message: str):
        """Start execution with status message."""
        self.start_time = time.time()
        self.llm_calls = 0
        self.tool_calls = 0
        self.total_tokens = 0
        self.current_status = Status(f"🤖 {message}", spinner="dots")
        self.current_status.start()
        self.callback_handler = RealTimeAgentCallbackHandler(self)

    def update_status(self, message: str):
        """Update the current status message."""
        if self.current_status:
            elapsed = time.time() - self.start_time if self.start_time else 0
            status_text = f"🤖 {message} | {elapsed:.1f}s"
            if self.llm_calls > 0:
                status_text += f" | LLM: {self.llm_calls}"
            if self.tool_calls > 0:
                status_text += f" | Tools: {self.tool_calls}"
            if self.total_tokens > 0:
                status_text += f" | Tokens: {self.total_tokens}"
            self.current_status.update(status_text)

    def log_llm_call(self, tokens_used: int = 0):
        """Log an LLM call."""
        self.llm_calls += 1
        if tokens_used > 0:
            self.total_tokens += tokens_used
        self.update_status("Processing...")

    def log_tool_call(self, tool_name: str = ""):
        """Log a tool call."""
        self.tool_calls += 1
        self.update_status(f"Using tool: {tool_name}" if tool_name else "Using tool...")

    def stop_execution(self, success: bool = True, final_message: str = None):
        """Stop execution and show final result."""
        if self.current_status:
            self.current_status.stop()

        elapsed = time.time() - self.start_time if self.start_time else 0

        if success:
            result_text = "✅ Complete"
        else:
            result_text = "❌ Failed"

        result_text += f" | {elapsed:.1f}s"
        if self.llm_calls > 0:
            result_text += f" | LLM: {self.llm_calls}"
        if self.tool_calls > 0:
            result_text += f" | Tools: {self.tool_calls}"
        if self.total_tokens > 0:
            result_text += f" | Tokens: {self.total_tokens}"

        if final_message:
            result_text += f" | {final_message}"

        console.print(result_text)
        self.current_status = None
        self.callback_handler = None


"""ASCII art splash screen for da_code."""



def get_splash_screen() -> str:
    """Get the da_code ASCII splash screen."""

    # Main da_code ASCII art
    ascii_art = r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🤖 Agentic CLI with LangChain & Azure OpenAI 🚀
    """

    return ascii_art


def get_animated_splash() -> List[str]:
    """Get animated frames for splash screen."""

    frames = [
        # Frame 1
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🤖 Initializing AI Agent...
""",
        # Frame 2
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🧠 Loading LangChain...
""",
        # Frame 3
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    ☁️  Connecting to Azure OpenAI...
""",
        # Frame 4
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🔧 Loading MCP Servers...
""",
        # Final frame
        r"""
██████╗  █████╗      ██████╗ ██████╗ ██████╗ ███████╗
██╔══██╗██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║  ██║███████║    ██║     ██║   ██║██║  ██║█████╗
██║  ██║██╔══██║    ██║     ██║   ██║██║  ██║██╔══╝
██████╔╝██║  ██║    ╚██████╗╚██████╔╝██████╔╝███████╗
╚═════╝ ╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

    🚀 Ready! Your AI coding assistant is online.
"""
    ]

    return frames


def get_random_taglines() -> List[str]:
    """Get random taglines for variety."""
    return [
        "🤖 Agentic CLI with LangChain & Azure OpenAI 🚀",
        "🧠 AI-Powered Command Line Assistant 🔧",
        "⚡ Smart Automation with Human Oversight 🛡️",
        "🎯 Precision Coding with AI Intelligence 💡",
        "🔬 Advanced AI Tooling for Developers 🚀",
        "🌟 Next-Gen CLI Experience 🤖",
        "⚙️  Intelligent Command Execution 🎪",
        "🎨 Where AI Meets Development Workflow 🔥"
    ]


def get_mini_splash() -> str:
    """Get a smaller splash for quick starts."""
    return r"""
██████╗  █████╗ ██████╗
██╔══██╗██╔══██╗██╔════╝
██║  ██║███████║██║     
██║  ██║██╔══██║██║     
██████╔╝██║  ██║╚██████╗
╚═════╝ ╚═╝  ╚═╝ ╚═════╝
🤖 Your AI Coding Assistant 🚀
"""


def get_status_splash() -> str:
    """Get splash screen for status/setup commands."""
    return r"""
    ╔═════════════════════════════════╗
    ║     ██████╗  █████╗ ██████╗     ║
    ║     ██╔══██╗██╔══██╗██╔════╝    ║
    ║     ██║  ██║███████║██║         ║
    ║     ██║  ██║██╔══██║██║         ║
    ║     ██████╔╝██║  ██╚██████╗     ║
    ║     ╚═════╝ ╚═╝  ╚═╝╚═════╝     ║
    ╚═════════════════════════════════╝
    """


def print_with_colors(text: str, color_code: str = "94") -> None:
    """Print text with ANSI colors."""
    print(f"\033[{color_code}m{text}\033[0m")


def print_gradient_splash(text: str) -> None:
    """Print splash with gradient effect."""
    lines = text.split('\n')
    # True blue gradient: dark blue -> bright blue -> cyan
    colors = ["34", "94", "94", "96", "96", "36", "36", "96"]

    for i, line in enumerate(lines):
        color = colors[i % len(colors)]
        print(f"\033[{color}m{line}\033[0m")


def print_rainbow_splash(text: str) -> None:
    """Print splash with rainbow colors."""
    lines = text.split('\n')
    rainbow_colors = ["91", "93", "92", "96", "94", "95"]

    for i, line in enumerate(lines):
        if line.strip():  # Only color non-empty lines
            color = rainbow_colors[i % len(rainbow_colors)]
            print(f"\033[{color}m{line}\033[0m")
        else:
            print(line)


def show_splash(style: str = "default", mini: bool = False) -> None:
    """Show splash screen with specified style."""

    if mini:
        splash = get_mini_splash()
    else:
        splash = get_splash_screen()
        # Add random tagline
        taglines = get_random_taglines()
        random_tagline = random.choice(taglines)
        splash = splash.replace("🤖 Agentic CLI with LangChain & Azure OpenAI 🚀", random_tagline)

    # Apply styling
    if style == "gradient":
        print_gradient_splash(splash)
    elif style == "rainbow":
        print_rainbow_splash(splash)
    elif style == "blue":
        print_with_colors(splash, "94")
    elif style == "cyan":
        print_with_colors(splash, "96")
    elif style == "green":
        print_with_colors(splash, "92")
    elif style == "yellow":
        print_with_colors(splash, "93")
    elif style == "purple":
        print_with_colors(splash, "95")
    else:
        # Default - no colors
        print(splash)


def show_status_splash() -> None:
    """Show splash for status/configuration commands."""
    print_with_colors(get_status_splash(), "96")


def create_session(context_ldr: ContextLoader):
    # Load project context
    project_context = context_ldr.load_project_context()

    # Load MCP servers
    mcp_servers = context_ldr.load_mcp_servers()

    # Determine working directory
    working_dir = os.getcwd()

    # Create session
    code_session = CodeSession(
        working_directory=working_dir,
        project_context=project_context,
        mcp_servers=mcp_servers,
    )
    return code_session


def initialize_agent(config_mgr: ConfigManager, code_session: CodeSession):
    """Initialize agent after configuration is validated."""
    try:
        # Validate configuration
        if not config_mgr.validate_config():
            return None

        # Create agent
        new_agent = DaCodeAgent(config_mgr.create_agent_config(), code_session)

        logger.info("Agent initialized successfully")
        return new_agent

    except Exception as e:
        logger.error(f"Agent initialization failed: {e}")
        print(f"❌ Failed to initialize agent: {e}")
        return None
    
    return new_agent


def create_example_configuration(config_mgr: ConfigManager, context_ldr: ContextLoader) -> int:
    """Setup configuration files."""
    show_status_splash()
    print("🔧 Setting up da_code configuration...")

    try:
        # Create sample environment file
        config_mgr.create_sample_env()

        # Create sample DA files if they don't exist
        if not Path('DA.md').exists():
            context_ldr.create_sample_da_md()

        if not Path('DA.json').exists():
            context_ldr.create_sample_da_json()

        print("\n✅ Setup complete!")
        print("\nNext steps:")
        print("1. Edit .env with your Azure OpenAI credentials")
        print("2. Edit DA.md with your project information")
        print("3. Edit DA.json with your MCP server configuration")
        print("4. Run 'da_code status' to verify configuration")
        print("5. Run 'da_code' to start interactive session")

        return 0

    except Exception as e:
        print(f"❌ Setup failed: {e}")
        return 1



def show_status(config_mgr: ConfigManager, context_ldr: ContextLoader) -> int:
    """Show configuration and system status."""
    try:
        config_mgr.print_config_status()

        # Check project context
        print("\n=== Project Context ===")
        project_context = context_ldr.load_project_context()
        if project_context:
            print(f"✓ DA.md loaded: {project_context.project_name or 'Unnamed project'}")
        else:
            print("✗ DA.md not found or empty")

        # Check MCP servers
        mcp_servers = context_ldr.load_mcp_servers()
        print(f"\n=== MCP Servers ===")
        if mcp_servers:
            print(f"✓ Found {len(mcp_servers)} MCP servers:")
            for server in mcp_servers:
                print(f"  - {server.name}: {server.url}")
        else:
            print("✗ No MCP servers configured")

        return 0

    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return 1

#---------------------------------------------------------------
# Setup
#---------------------------------------------------------------

# Agent will be initialized in main() after config validation
agent = None
default_timeout = 300
code_session = None
session_start_time = None


# Available commands
commands = ['help', 'setup', 'status', 'test', 'reload', 'exit', 'quit', 'q']

async def async_main():
    """Async main with simple status interface."""
    status_interface = SimpleStatusInterface()

    show_splash("gradient")

    # Check if we need to run setup first
    if not ConfigManager().validate_config():
        console.print("[yellow]Configuration not found. Run 'setup' to create configuration files.[/yellow]")
        console.print(f"Available commands: {', '.join(commands)}")
    else:
        # Initialize agent if config is valid
        status_interface.start_execution("Initializing session...")
        code_session = create_session(context_ldr=ContextLoader())
        if code_session is None:
            status_interface.stop_execution(False, "Session creation failed")
            raise ValueError("Failed to create code session!")

        status_interface.update_status("Initializing agent...")
        agent = initialize_agent(config_mgr=ConfigManager(), code_session=code_session)
        if agent is None:
            status_interface.stop_execution(False, "Agent initialization failed")
            console.print("[red]Agent initialization failed. Run 'setup' to regenerate.[/red]")
        else:
            # Get deployment name
            deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4')

            # Get chat memory status
            try:
                memory_info = agent.memory_manager.get_memory_info()
                memory_type = memory_info.get('memory_type', 'unknown')
                message_count = memory_info.get('message_count', 0)

                if memory_type == 'postgres':
                    memory_status = "[green]PostgreSQL[/green]"
                elif memory_type == 'file':
                    memory_status = "[yellow]File[/yellow]"
                else:
                    memory_status = "[red]Memory[/red]"

                # Add message count if exists
                if message_count > 0:
                    memory_status += f" ({message_count})"

            except Exception as e:
                memory_status = "[red]Unknown[/red]"

            # Get MongoDB status
            try:
                from .models import get_mongo_status
                mongo_status = get_mongo_status()
                if mongo_status:
                    mongo_status_str = "[green]Connected[/green]"
                else:
                    mongo_status_str = "[yellow]Disconnected[/yellow]"
            except:
                mongo_status_str = "[red]Unknown[/red]"

            # Combined status line
            status_interface.stop_execution(True, f"Ready | 🤖 {deployment_name} | 💾 {memory_status} | 🍃 {mongo_status_str}")

    while True:
        try:
            user_input = Prompt.ask("[cyan]>")

            if user_input.lower() in ['exit', 'quit', 'q']:
                console.print("👋 Goodbye!")
                break
            elif user_input.lower() == 'help':
                console.print("[bold]Available commands:[/bold]")
                for cmd in commands:
                    console.print(f"  • {cmd}")
            elif user_input.lower() == 'setup':
                create_example_configuration(config_mgr=ConfigManager(), context_ldr=ContextLoader())
                console.print("[green]Edit files and reload to update agent context[/green]")
            elif user_input.lower() == 'status':
                show_status(config_mgr=ConfigManager(), context_ldr=ContextLoader())
            elif user_input.lower() == 'test':
                console.print("🧪 Running Azure OpenAI connection test...")
                try:
                    from .test_connection import main as test_main
                    test_main()
                except Exception as e:
                    console.print(f"[red]❌ Test failed: {e}[/red]")
            elif user_input.lower() == 'reload':
                status_interface.start_execution("Reloading configuration...")
                try:
                    status_interface.update_status("Creating new session...")
                    code_session = create_session(context_ldr=ContextLoader())
                    if code_session is None:
                        raise ValueError("Failed to create code session!")

                    status_interface.update_status("Reinitializing agent...")
                    agent = initialize_agent(config_mgr=ConfigManager(), code_session=code_session)
                    if agent is None:
                        status_interface.stop_execution(False, "Agent initialization failed")
                        console.print("[red]Agent initialization failed. Run 'setup' to regenerate.[/red]")
                    else:
                        status_interface.stop_execution(True, "Configuration reloaded")
                except Exception as e:
                    status_interface.stop_execution(False, f"Reload error: {str(e)}")
                    console.print(f"[red]❌ Reload failed: {e}[/red]")
            elif user_input.strip() == '':
                continue
            else:
                if agent is None:
                    console.print("[yellow]Agent not initialized. Run 'setup' first.[/yellow]")
                    continue

                # Real-time agent execution with streaming events
                status_interface.start_execution(f"Processing: {user_input[:40]}...")
                try:
                    # Use the agent's underlying executor for streaming
                    agent_executor = agent.agent_executor
                    final_response = ""

                    # Track agent thoughts and actions
                    agent_thoughts = []
                    current_action = None

                    # Stream events from the agent executor
                    async for event in agent_executor.astream_events(
                        {"input": user_input},
                        version="v1"
                    ):
                        event_type = event.get("event")
                        event_name = event.get("name", "")
                        data = event.get("data", {})

                        # Handle different event types for real-time updates
                        if event_type == "on_llm_start":
                            status_interface.llm_calls += 1
                            status_interface.update_status("Thinking...")

                        elif event_type == "on_llm_end":
                            # Extract token usage and capture thoughts
                            if "output" in data:
                                output = data["output"]

                                # Track token usage
                                if hasattr(output, "usage_metadata"):
                                    tokens = output.usage_metadata.get("total_tokens", 0)
                                    if tokens > 0:
                                        status_interface.total_tokens += tokens

                                # Capture agent thoughts/reasoning
                                if hasattr(output, "content"):
                                    content = output.content

                                    # Look for thoughts in the content
                                    if "Thought:" in content:
                                        lines = content.split('\n')
                                        for line in lines:
                                            if line.strip().startswith("Thought:"):
                                                thought = line.replace("Thought:", "").strip()
                                                if thought and len(thought) > 15:
                                                    # Clean up and truncate thought
                                                    clean_thought = thought.replace("The user", "User").replace("I should", "Planning to")
                                                    truncated = clean_thought[:60] + "..." if len(clean_thought) > 60 else clean_thought
                                                    agent_thoughts.append(truncated)
                                                    # Show thought immediately
                                                    status_interface.update_status(f"💭 {truncated}")
                                            elif line.strip().startswith("Action:"):
                                                current_action = line.replace("Action:", "").strip()

                                    # Look for Final Answer
                                    elif "Final Answer:" in content:
                                        status_interface.update_status("Preparing final answer...")

                            status_interface.update_status("Processing...")

                        elif event_type == "on_tool_start":
                            tool_name = event.get("name", "Unknown")
                            status_interface.tool_calls += 1

                            # Show current thought if available
                            if agent_thoughts:
                                latest_thought = agent_thoughts[-1]
                                status_interface.update_status(f"Using {tool_name}: {latest_thought[:40]}...")
                            else:
                                status_interface.update_status(f"Using {tool_name}")

                        elif event_type == "on_tool_end":
                            status_interface.update_status("Tool completed")

                        elif event_type == "on_chain_start":
                            if "agent" in event_name.lower():
                                status_interface.update_status("Planning...")

                        elif event_type == "on_chain_end":
                            # Check if this is the final agent executor output
                            if "output" in data:
                                output_data = data["output"]
                                if isinstance(output_data, dict) and "output" in output_data:
                                    final_response = output_data["output"]
                                    status_interface.update_status("Finalizing...")

                    status_interface.stop_execution(True)
                    console.print()  # Empty line for spacing

                    # Display the final response
                    if final_response:
                        console.print(final_response)
                    else:
                        console.print("[yellow]No response received from agent[/yellow]")

                except Exception as e:
                    status_interface.stop_execution(False, str(e))
                    console.print(f"[red]Sorry, I encountered an error: {str(e)}[/red]")
                    logger.error(f"Agent chat error: {type(e).__name__}: {str(e)}", exc_info=True)

        except KeyboardInterrupt:
            if status_interface.current_status:
                status_interface.stop_execution(False, "Interrupted by user")
            console.print("[yellow]⚠️ Interrupted[/yellow]")
            continue
        except EOFError:
            break


def main():
    """Entry point with argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="da_code - AI Coding Assistant")
    parser.add_argument('command', nargs='?', choices=['setup', 'status', 'test'],
                       help='Command to run (setup creates config files and exits, test checks connection)')
    parser.add_argument('--working-dir', type=str, help='Working directory')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='Logging level')

    args = parser.parse_args()

    # Environment is automatically loaded when config module is imported

    # Setup logging with command line arg overriding environment LOG_LEVEL
    log_level = args.log_level if args.log_level != 'INFO' else os.getenv('LOG_LEVEL', 'INFO')
    setup_logging(log_level)

    # Handle command-line commands that exit immediately
    if args.command == 'setup':
        show_status_splash()
        result = create_example_configuration(config_mgr=ConfigManager(), context_ldr=ContextLoader())
        sys.exit(result)
    elif args.command == 'status':
        show_status_splash()
        result = show_status(config_mgr=ConfigManager(), context_ldr=ContextLoader())
        sys.exit(result)
    elif args.command == 'test':
        show_status_splash()
        print("🧪 Running Azure OpenAI connection test...")
        try:
            # Import and run the connection test
            from .test_connection import main as test_main
            result = test_main()
            sys.exit(result)
        except Exception as e:
            print(f"❌ Test failed: {e}")
            sys.exit(1)

    # Interactive mode
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Main execution error: {e}")

if __name__ == '__main__':
    main()
