
"""Main CLI entry point for da_code tool."""

import asyncio
import logging
import os
import sys
import time

import random
from typing import List, Optional
from pathlib import Path
#import termios
#import tty

from rich.prompt import Prompt
from rich.console import Console
from rich.status import Status
from rich.text import Text
from rich.panel import Panel

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML

from .config import ConfigManager, setup_logging
from .context import ContextLoader
from .models import CodeSession, CommandExecution, UserResponse, ConfirmationResponse
from .agno_agent import AgnoAgent


logger = logging.getLogger(__name__)

# Global console for clean interaction
console = Console()


async def async_prompt_user_silent(choices: List[str], default: str = None, command: str = None) -> str:
    """Interactive prompt with visual arrow indicator for selected option."""


    # Choice configuration with colors
    choice_config = {
        "yes": {"label": "✅ Yes", "desc": "Execute the command as shown", "color": "green"},
        "no": {"label": "❌ No", "desc": "Cancel command execution", "color": "red"},
        "modify": {"label": "✏️  Modify", "desc": "Edit the command before execution", "color": "yellow"},
        "explain": {"label": "❓ Explain", "desc": "Ask agent to explain the command", "color": "blue"}
    }

    def display_static_confirmation():
        """Display confirmation panel once - no updates until selection made."""
        content_lines = Text()

        # Add command info if provided
        if command:
            command_text = Text()
            command_text.append("Command: ", style="bold cyan")
            command_text.append(f"`{command}`", style="bold yellow")
            content_lines.append(command_text)
            content_lines.append("\n")

        # Add choices (no arrow initially)
        for i, choice in enumerate(choices):
            config = choice_config.get(choice.lower(), {"label": choice, "desc": "", "color": "white"})
            line = Text()
            line.append("    ", style="white")
            line.append(f"{i+1}. {config['label']}", style=config['color'])
            if config['desc']:
                line.append(f" - {config['desc']}", style="white dim")
            line.append("\n")
            content_lines.append(line) 


        # Instructions
        instructions = Text()
        instructions.append("Press 1-4", style="cyan bold")
        instructions.append(" or use ", style="white dim")
        instructions.append("↑/↓ arrows", style="cyan bold")
        instructions.append(" and ", style="white dim")
        instructions.append("Enter", style="red bold")
        instructions.append(" to select\n", style="white dim")
        content_lines.append(instructions)


        # Display the panel once
        unified_panel = Panel(
            content_lines,
            title="🤖 Confirm Agent Command",
            title_align="left",
            border_style="cyan"
        )
        console.print(unified_panel)

    def get_keypress_choice() -> str:
        fd = sys.stdin.fileno()
        #old_settings = termios.tcgetattr(fd)
        selected_index = 0  # Initialize locally

        try:
            #tty.setraw(sys.stdin.fileno())

            # Display confirmation panel once
            display_static_confirmation()
            
            # display the default choice
            config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "desc": "", "color": "white"})
            print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)
            
            while True:
                key = sys.stdin.read(1)

                # Number key shortcuts
                if key in ['1', '2', '3', '4']:
                    idx = int(key) - 1
                    if idx < len(choices):
                        return choices[idx]

                # Arrow keys - track selection and show simple feedback
                elif key == '\x1b':
                    key += sys.stdin.read(2)
                    if key == '\x1b[A':  # Up
                        selected_index = (selected_index - 1) % len(choices)
                        # Show simple selection feedback
                        config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "color": "white"})
                        print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)
                    elif key == '\x1b[B':  # Down
                        selected_index = (selected_index + 1) % len(choices)
                        # Show simple selection feedback
                        config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "color": "white"})
                        print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)

                # Enter key
                elif key in ['\r', '\n']:
                    # Clear any status line before returning
                    print('\r\033[K', end='', flush=True)
                    return choices[selected_index]

                # Ctrl+C
                elif key == '\x03':
                    raise KeyboardInterrupt()

        finally:
            pass
            #termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Get choice asynchronously
    loop = asyncio.get_event_loop()
    selected_choice = await loop.run_in_executor(None, get_keypress_choice)

    # Show clean selection result in console history
    config = choice_config.get(selected_choice.lower(), {"label": selected_choice, "color": "white"})
    console.print(f"[green bold]✅ Selected: {config['label']}[/green bold]")

    return selected_choice



def display_simple_confirmation(execution) -> None:
    """Display simplified command confirmation panel using UserResponse enum."""
    from rich.panel import Panel
    from rich.text import Text

    # Build content
    content = []

    # Command info section
    command_text = Text()
    command_text.append("Command: ", style="bold cyan")
    command_text.append(execution.command, style="bold white")
    content.append(str(command_text))

    # Add separator
    content.append("")

    # Complete choice display using all UserResponse enum values
    choices = [
        ("✅ Yes", "Execute the command as shown"),
        ("❌ No", "Cancel command execution"),
        ("✏️ Modify", "Edit the command before execution"),
        ("❓ Explain", "Ask agent to explain the command")
    ]

    for i, (label, desc) in enumerate(choices):
        choice_line = Text()
        choice_line.append(f"  {i+1}. {label}", style="bold")
        choice_line.append(f" - {desc}", style="white dim")
        content.append(str(choice_line))

    # Add instructions
    content.append("")
    instructions = Text()
    instructions.append("Press ", style="white dim")
    instructions.append("1-4", style="cyan bold")
    instructions.append(" or use ", style="white dim")
    instructions.append("↑/↓ arrows", style="cyan bold")
    instructions.append(" + ", style="white dim")
    instructions.append("Enter", style="green bold")
    content.append(str(instructions))

    # Create panel
    panel = Panel(
        "\n".join(content),
        title="🤖 Command Confirmation",
        title_align="left",
        border_style="cyan",
        padding=(1, 2)
    )

    console.print(panel)




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



class SimpleStatusInterface:
    """Simple status interface with Rich spinner and agent insights."""

    def __init__(self):
        self.start_time = None
        self.current_status = None
        self.llm_calls = 0
        self.tool_calls = 0
        self.total_tokens = 0
        self.callback_handler = None
        # Agent metrics (LangGraph only)
        self.agent_metrics = {'calls': 0, 'tokens': 0}

    def start_execution(self, message: str):
        """Start execution with status message."""
        self.start_time = time.time()
        self.llm_calls = 0
        self.tool_calls = 0
        self.total_tokens = 0
        # Reset agent metrics
        self.agent_metrics = {'calls': 0, 'tokens': 0}
        self.current_status = Status(f"🤖 {message}", spinner="dots")
        self.current_status.start()

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

    def track_agent_call(self, tokens: int = 0):
        """Track agent calls and token usage."""
        self.agent_metrics['calls'] += 1
        self.agent_metrics['tokens'] += tokens

    def stop_execution(self, success: bool = True, final_message: str = None):
        """Stop execution and show final result."""
        if self.current_status:
            self.current_status.stop()

        elapsed = time.time() - self.start_time if self.start_time else 0

        if success:
            result_text = "✅ Complete"
        else:
            result_text = "❌ Failed"

        result_text += f" {elapsed:.1f}s"

        # Add current directory
        current_dir = os.path.basename(os.getcwd()) or "/"
        result_text += f" | 📂 {current_dir}"

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


async def async_prompt_text(message: str, default: str = None) -> str:
    """Async wrapper for Rich text prompts."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: Prompt.ask(message, default=default)
    )



#---------------------------------------------------------------
# Setup
#---------------------------------------------------------------

# Agent will be initialized in main() after config validation


# Available commands
commands = ['help', 'setup', 'status', 'add_mcp', 'exit', 'quit', 'q']

async def async_main():
    """Async main with simple status interface."""
    status_interface = SimpleStatusInterface()

    
    async def confirmation_handler(execution: CommandExecution, status_interface=status_interface) -> ConfirmationResponse:
        """Handle command confirmation directly."""
        # Stop status to show confirmation dialog cleanly
        status_interface.stop_execution()

        # Get user choice using enum values with command display
        response = await async_prompt_user_silent([
            UserResponse.YES.value.title(),    # "Yes"
            UserResponse.NO.value.title(),     # "No"
            UserResponse.MODIFY.value.title(), # "Modify"
            UserResponse.EXPLAIN.value.title() # "Explain"
        ], default=UserResponse.YES.value.title(), command=execution.command)

        modified_command = None
        if response.lower() == UserResponse.MODIFY.value:
            # Get modified command from user
            modified_command = await async_prompt_text("Enter modified command", default=execution.command)
            if not modified_command:
                response = UserResponse.NO.value.title()

        # Restart status interface for continued execution
        status_interface.start_execution("Processing...")

        # Convert response back to enum value for consistency
        response_lower = response.lower()
        if response_lower == "yes":
            enum_choice = UserResponse.YES.value
        elif response_lower == "no":
            enum_choice = UserResponse.NO.value
        elif response_lower == "modify":
            enum_choice = UserResponse.MODIFY.value
        elif response_lower == "explain":
            enum_choice = UserResponse.EXPLAIN.value
        else:
            enum_choice = UserResponse.NO.value  # Default fallback

        return ConfirmationResponse(
            choice=enum_choice,
            modified_command=modified_command
        )

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

        status_interface.update_status("Initializing Agno agent...")
        agent = AgnoAgent(code_session)
        if agent is None:
            status_interface.stop_execution(False, "Agent initialization failed")
            console.print("[red]Agent initialization failed. Run 'setup' to regenerate.[/red]")
        else:
            # Get deployment name
            deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4')

            # Get chat memory status from agent
            try:
                session_info = agent.get_session_info()
                memory_info = session_info.get('memory_info', {})
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
            status_interface.stop_execution(True, f"🤖 {deployment_name} | 💾 {memory_status} | 🍃 {mongo_status_str}")

    history = FileHistory(agent.config.history_file_path)

    # Create PromptSession for async usage
    session = PromptSession(
        history=history,
        multiline=False,
        complete_style='column',
    )

    async def get_user_input_with_history(queue):
        """Get user input with file-based history and arrow key support."""
        while True:
            try:
                user_input = await session.prompt_async(HTML('<cyan>>></cyan> '))
                await queue.put(user_input)
            except (EOFError, KeyboardInterrupt):
                return None
            await asyncio.sleep(0.05)
        
    input_queue = asyncio.Queue()
    status_queue = asyncio.Queue()
    output_queue = asyncio.Queue()
    
    async with asyncio.TaskGroup() as tg:
        wait_for_input = tg.create_task(get_user_input_with_history(input_queue))
        #task2 = tg.create_task(another_coro(...))
 
        running_agent = None
        status_message = None
        output_message = None
        while True:
            try:
                # If agent is not running then wait for input command 
                if running_agent is None:
                    if wait_for_input.done():
                        console(f"ERROR: wait_for_input is done!! {wait_for_input.result()}")
                    user_input = await input_queue.get()
                elif running_agent.done():
                    final_response = running_agent.result()
                    status_message = None
                    running_agent = None
                    status_interface.stop_execution(True)
                    console.print()
                    console.print(output_message)
                    output_message = None
                else:
                    while output_queue.qsize() > 0:
                        output_message += await output_queue.get()
                        #console.print(output_message, end="")
                    while status_queue.qsize() > 0:
                        status_message = await status_queue.get()
                    status_interface.update_status(f"{status_message}")
                    await asyncio.sleep(0.01)
                    continue

                if user_input is None:
                    continue

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
                elif user_input.strip() == '':
                    continue
                else:
                    if agent is None:
                        console.print("[yellow]Agent not initialized. Run 'setup' first.[/yellow]")
                        continue

                # Beautiful unified streaming execution 🚀

                try:
                    status_message = f"Calculating: {user_input[:40]}..."
                    status_interface.start_execution(status_message)
                    output_message = ""
                    running_agent = tg.create_task(
                        agent.arun(user_input, confirmation_handler, tg, status_queue, output_queue)
                    )
                    user_input = None
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
    parser.add_argument('command', nargs='?', choices=['setup', 'status'],
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
