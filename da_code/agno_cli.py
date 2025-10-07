
"""Main CLI entry point for da_code tool."""

import asyncio
import logging
import os
import sys
import time
import subprocess

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
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import PathCompleter, WordCompleter, Completer, Completion

from .config import ConfigManager, setup_logging
from .context import ContextLoader
from .models import CodeSession, CommandExecution, UserResponse, ConfirmationResponse
from .agno_agent import AgnoAgent
from .mcp_tool import mcp2tool


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

    🤖 Agentic CLI with Agno & Azure OpenAI 🚀
    """

    return ascii_art

def get_random_taglines() -> List[str]:
    """Get random taglines for variety."""
    return [
        "🤖 Agentic CLI with Agno & Azure OpenAI 🚀",
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
        splash = splash.replace("🤖 Agentic CLI with Agno & Azure OpenAI 🚀", random_tagline)

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

        # Create sample context files if they don't exist
        if not Path('AGENTS.md').exists():
            context_ldr.create_sample_agents_md()

        if not Path('DA.json').exists():
            context_ldr.create_sample_da_json()

        print("\n✅ Setup complete!")
        print("\nNext steps:")
        print("1. Edit .env with your Azure OpenAI credentials")
        print("2. Edit AGENTS.md with your project information")
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
            print(f"✓ AGENTS.md loaded: {project_context.project_name or 'Unnamed project'}")
        else:
            print("✗ AGENTS.md not found or empty")

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



class ShellCompleter(Completer):
    """Custom completer for shell commands with file/directory completion."""

    def __init__(self):
        # Common shell commands
        self.shell_commands = [
            'ls', 'cd', 'pwd', 'mkdir', 'rmdir', 'rm', 'cp', 'mv', 'cat', 'less', 'more',
            'grep', 'find', 'which', 'whereis', 'locate', 'chmod', 'chown', 'touch',
            'head', 'tail', 'wc', 'sort', 'uniq', 'cut', 'awk', 'sed', 'tar', 'gzip',
            'gunzip', 'zip', 'unzip', 'ps', 'top', 'htop', 'kill', 'killall', 'jobs',
            'bg', 'fg', 'nohup', 'screen', 'tmux', 'ssh', 'scp', 'rsync', 'curl', 'wget',
            'git', 'python', 'python3', 'pip', 'pip3', 'node', 'npm', 'yarn', 'docker',
            'docker-compose', 'make', 'cmake', 'gcc', 'g++', 'javac', 'java', 'go',
            'cargo', 'rustc', 'echo', 'printf', 'date', 'cal', 'uptime', 'df', 'du',
            'free', 'uname', 'whoami', 'id', 'groups', 'su', 'sudo', 'history', 'alias',
            'export', 'env', 'printenv', 'source', 'bash', 'sh', 'zsh', 'fish'
        ]
        self.path_completer = PathCompleter()
        self.command_completer = WordCompleter(self.shell_commands)

    def get_completions(self, document, complete_event):
        text = document.text

        # If empty, complete commands
        if not text.strip():
            yield from self.command_completer.get_completions(document, complete_event)
            return

        words = text.split()

        # If we have multiple words OR the text ends with space, complete file paths
        if len(words) > 1 or (len(words) == 1 and text.endswith(' ')):
            yield from self.path_completer.get_completions(document, complete_event)
        else:
            # Single word without trailing space - could be command or path
            # Try both command completion and path completion
            command_completions = list(self.command_completer.get_completions(document, complete_event))
            path_completions = list(self.path_completer.get_completions(document, complete_event))

            # Yield command completions first, then path completions
            yield from command_completions
            yield from path_completions


class ShellModeManager:
    """Manages shell mode and captures command output for agent context."""

    def __init__(self):
        self.is_shell_mode = False
        self.shell_history = []
        self.max_history_entries = 50
        self.shell_command_history = []  # Separate history for shell commands only

    def toggle_shell_mode(self):
        """Toggle between shell mode and agent mode."""
        self.is_shell_mode = not self.is_shell_mode
        mode_name = "shell" if self.is_shell_mode else "agent"
        console.print(f"[cyan]🔧 Switched to {mode_name} mode[/cyan]")

    def execute_shell_command(self, command: str) -> str:
        """Execute shell command and capture output."""
        # Add command to shell command history for up/down arrow navigation
        if command.strip() and (not self.shell_command_history or command != self.shell_command_history[-1]):
            self.shell_command_history.append(command)
            # Keep shell command history manageable
            if len(self.shell_command_history) > 1000:
                self.shell_command_history = self.shell_command_history[-1000:]

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Combine stdout and stderr
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            # Add to history for agent context
            self.shell_history.append({
                'command': command,
                'output': output,
                'return_code': result.returncode,
                'timestamp': time.time()
            })

            # Keep only recent entries
            if len(self.shell_history) > self.max_history_entries:
                self.shell_history = self.shell_history[-self.max_history_entries:]

            return output

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after 30 seconds: {command}"
            self.shell_history.append({
                'command': command,
                'output': error_msg,
                'return_code': -1,
                'timestamp': time.time()
            })
            return error_msg

        except Exception as e:
            error_msg = f"Shell execution error: {str(e)}"
            self.shell_history.append({
                'command': command,
                'output': error_msg,
                'return_code': -1,
                'timestamp': time.time()
            })
            return error_msg

    def get_shell_context_for_agent(self) -> str:
        """Get recent shell commands and output as context for the agent."""
        if not self.shell_history:
            return ""

        context_lines = ["Recent shell commands and their output:"]

        # Get last 5 commands for context
        recent_commands = self.shell_history[-5:]

        for entry in recent_commands:
            context_lines.append(f"\n$ {entry['command']}")
            if entry['return_code'] == 0:
                context_lines.append(f"Output:\n{entry['output'][:1000]}")  # Limit output length
            else:
                context_lines.append(f"Error (code {entry['return_code']}):\n{entry['output'][:1000]}")

        return "\n".join(context_lines)


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


def get_file_emoji(filename: str) -> str:
    """Get emoji for file type"""
    name_lower = filename.lower()
    if name_lower.endswith(('.py', '.pyw')):
        return "🐍"
    elif name_lower.endswith(('.js', '.jsx', '.ts', '.tsx')):
        return "🟨"
    elif name_lower.endswith(('.md', '.markdown')):
        return "📖"
    elif name_lower.endswith(('.json', '.yaml', '.yml', '.toml')):
        return "⚙️"
    elif name_lower.endswith(('.env', '.gitignore', '.dockerignore')):
        return "🔧"
    elif name_lower.endswith(('.txt', '.log')):
        return "📝"
    elif name_lower.endswith(('.sh', '.bash', '.zsh')):
        return "🔸"
    elif name_lower.endswith(('.html', '.htm', '.css')):
        return "🌐"
    elif name_lower.endswith(('.sql', '.db', '.sqlite')):
        return "🗄️"
    elif name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
        return "🖼️"
    else:
        return "📄"


def calculate_directory_activity_score(dir_path: Path, current_time: float) -> float:
    """Calculate activity score using max(avg_file_activity, directory_activity)"""
    try:
        dir_stat = dir_path.stat()
        directory_update_delta = current_time - dir_stat.st_mtime

        # Get all file update deltas
        file_deltas = []
        for file_path in dir_path.rglob('*'):
            if (file_path.is_file() and
                not file_path.name.startswith('.') and
                file_path.name not in {'__pycache__', '.pyc', '.pyo'}):
                file_delta = current_time - file_path.stat().st_mtime
                file_deltas.append(file_delta)

        if not file_deltas:
            return directory_update_delta

        avg_file_activity = sum(file_deltas) / len(file_deltas)

        # Your scoring formula: max of average file activity vs directory activity
        score = max(avg_file_activity, directory_update_delta)
        return score

    except (OSError, PermissionError):
        return float('inf')  # Inaccessible = lowest priority


def get_activity_ranked_directories(working_dir: str, top_n: int = 3) -> list:
    """Get directories ranked by recent activity score"""
    current_time = time.time()
    scored_dirs = []
    path = Path(working_dir)

    ignored = {'.git', '__pycache__', '.vscode', 'node_modules', '.pytest_cache'}

    for item in path.iterdir():
        if (item.is_dir() and
            not item.name.startswith('.') and
            item.name not in ignored):
            score = calculate_directory_activity_score(item, current_time)
            scored_dirs.append((item.name, score))

    # Sort by score (lower = more recent activity)
    scored_dirs.sort(key=lambda x: x[1])
    return scored_dirs[:top_n]


def get_subdirectory_preview(working_dir: str, subdir_name: str, max_files: int = 4) -> str:
    """Get preview of subdirectory contents with emoji file types"""
    subdir_path = Path(working_dir) / subdir_name
    if not subdir_path.exists() or not subdir_path.is_dir():
        return ""

    preview_lines = []
    file_count = 0
    total_files = 0

    try:
        # Get files sorted by size (larger files often more important)
        files = []
        for item in subdir_path.iterdir():
            if item.is_file() and not item.name.startswith('.'):
                try:
                    size = item.stat().st_size
                    files.append((item.name, size))
                    total_files += 1
                except (OSError, PermissionError):
                    continue

        # Sort by size descending, then by name
        files.sort(key=lambda x: (-x[1], x[0]))

        # Show top files with emojis
        for filename, size in files[:max_files]:
            if size < 1024:
                size_str = f"{size}B"
            elif size < 1024*1024:
                size_str = f"{size//1024}KB"
            else:
                size_str = f"{size//(1024*1024)}MB"

            emoji = get_file_emoji(filename)
            preview_lines.append(f"  └── {emoji} {filename} ({size_str})")
            file_count += 1

        # Add summary if there are more files
        if total_files > max_files:
            remaining = total_files - max_files
            preview_lines.append(f"  └── ... and {remaining} more files")

    except (OSError, PermissionError):
        preview_lines.append(f"  └── (unable to read {subdir_name})")

    return "\n".join(preview_lines)


def format_time_delta(seconds: float) -> str:
    """Format time delta in human readable form"""
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds/60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds/3600)}h ago"
    else:
        return f"{int(seconds/86400)}d ago"


def get_directory_listing(working_dir: str) -> tuple[str, float]:
    """Get integrated directory listing with subdirectory previews and time deltas."""
    try:
        path = Path(working_dir)
        listing = []
        current_time = time.time()

        # Get files/dirs, skip ignored patterns
        ignored = {'.git', '__pycache__', '.vscode', 'node_modules'}

        # Get activity scores for directories
        directory_scores = {}
        for item in path.iterdir():
            if (item.is_dir() and
                not item.name.startswith('.') and
                item.name not in ignored):
                score = calculate_directory_activity_score(item, current_time)
                directory_scores[item.name] = score

        # Process all items with integrated subdirectory previews
        for item in sorted(path.iterdir()):
            if item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                continue
            if item.name in ignored:
                continue

            try:
                if item.is_dir():
                    # Directory with activity score and time delta
                    activity_score = directory_scores.get(item.name, float('inf'))
                    time_delta = format_time_delta(activity_score)

                    listing.append(f"📁 {item.name}/ ({time_delta})")

                    # Add subdirectory preview if it's one of the active directories
                    if activity_score < 7 * 86400:  # Only show preview for dirs active within 7 days
                        preview = get_subdirectory_preview(working_dir, item.name, max_files=3)
                        if preview:
                            listing.append(preview)
                else:
                    # File with size and modification time
                    stat = item.stat()
                    mod_delta = current_time - stat.st_mtime
                    time_str = format_time_delta(mod_delta)

                    size = stat.st_size
                    if size < 1024:
                        size_str = f"{size}B"
                    elif size < 1024*1024:
                        size_str = f"{size//1024}KB"
                    else:
                        size_str = f"{size//(1024*1024)}MB"

                    emoji = get_file_emoji(item.name)
                    listing.append(f"{emoji} {item.name} ({size_str}, {time_str})")

            except (OSError, PermissionError):
                continue

        if not listing:
            listing.append("(empty directory)")

        result = "\n".join(listing)
        timestamp = time.time()
        return result, timestamp

    except Exception as e:
        logger.error(f"Failed to get directory listing: {e}")
        return f"📁 {working_dir} (unable to read)", time.time()


def check_directory_changes(working_dir: str, cache_timestamp: float) -> Optional[str]:
    """Check if directory changed since timestamp. Returns update message if changed."""
    if not cache_timestamp:
        return None

    try:
        path = Path(working_dir)

        # Quick check: any file newer than cache?
        for item in path.iterdir():
            if item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                continue
            if item.name in {'.git', '__pycache__', '.vscode', 'node_modules'}:
                continue

            try:
                if item.stat().st_mtime > cache_timestamp:
                    new_listing, _ = get_directory_listing(working_dir)
                    return f"📁 Directory updated:\n{new_listing}\n\n"
            except (OSError, PermissionError):
                continue

        return None

    except Exception as e:
        logger.error(f"Failed to check directory changes: {e}")
        return None




#---------------------------------------------------------------
# Setup
#---------------------------------------------------------------

# Agent will be initialized in main() after config validation


# Available commands
commands = ['help', 'setup', 'status', 'add_mcp', 'shell', 'exit', 'quit', 'q']

async def async_main():
    """Async main with simple status interface."""
    status_interface = SimpleStatusInterface()
    shell_manager = ShellModeManager()



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
            
        # Directory cache for change detection
        directory_cache, cache_timestamp = get_directory_listing(code_session.working_directory)
        agent = AgnoAgent(code_session, directory_cache)

        # Track dynamic MCP tools
        dynamic_mcp_tools = []

        if agent is None:
            logger.error("Agent init failed, rerun setup")
        else:
            # Get deployment name
            deployment_name = agent.config.deployment_name
            reasoning_deployment = agent.config.reasoning_deployment
            
            # Get chat memory status from agent
            try:
                if agent.db_type == 'postgres':
                    memory_status = "[green]PostgreSQL[/green]"
                elif agent.db_type == 'sqlite':
                    memory_status = "[yellow]File[/yellow]"
                else:
                    memory_status = "[red]Memory[/red]"
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
            status_interface.stop_execution(True, f"🤖 {deployment_name} | 🤔 {reasoning_deployment} | 💾 {memory_status} | 🍃 {mongo_status_str}")

    # Set up history files
    agent_history = FileHistory(agent.config.history_file_path)
    shell_history_path = os.getenv('SHELL_HISTORY_FILE', os.path.expanduser('~/.da_code_shell_history'))
    shell_history = FileHistory(shell_history_path)

    # Set up completers
    shell_completer = ShellCompleter()
    # No completer for agent mode (or could add custom agent completer later)

    # Create key bindings for shell mode toggle
    bindings = KeyBindings()

    @bindings.add(Keys.Escape)  # Escape key
    def _(event):
        """Toggle shell mode with Escape key."""
        shell_manager.toggle_shell_mode()

    # Create PromptSession for async usage - will switch history and completer dynamically
    session = PromptSession(
        history=agent_history,
        multiline=False,
        complete_style='column',
        key_bindings=bindings,
        completer=None,  # Will be set dynamically
    )

    async def get_user_input_with_history(queue):
        """Get user input with file-based history and arrow key support."""
        while True:
            try:
                # Dynamic prompt, history, and completer based on mode
                if shell_manager.is_shell_mode:
                    prompt_text = HTML('<yellow>shell$</yellow> ')
                    # Switch to shell history and completer
                    session.history = shell_history
                    session.completer = shell_completer
                else:
                    prompt_text = HTML('<cyan>agent!</cyan> ')
                    # Switch to agent history and no completer
                    session.history = agent_history
                    session.completer = None

                user_input = await session.prompt_async(prompt_text)
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
                    try:
                        final_response = running_agent.result()
                        status_message = None
                        running_agent = None
                        status_interface.stop_execution(True)
                        console.print()
                        console.print(output_message)
                        output_message = None
                    except Exception as e:
                        # Handle agent execution errors
                        running_agent = None
                        status_interface.stop_execution(False, str(e))
                        console.print(f"[red]Agent error: {str(e)}[/red]")
                        logger.error(f"Agent execution error: {type(e).__name__}: {str(e)}", exc_info=True)
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
                    console.print("  • help - Show this help message")
                    console.print("  • setup - Create configuration files")
                    console.print("  • status - Show current configuration status")
                    console.print("  • add_mcp <url> [name] - Add MCP server dynamically")
                    console.print("  • shell - Toggle shell mode")
                    console.print("  • exit/quit/q - Exit the application")
                    console.print("\n[bold]Shell Mode:[/bold]")
                    console.print("  • Type [cyan]shell[/cyan] or press [cyan]Escape[/cyan] to toggle between modes")
                    console.print("  • In shell mode, commands are executed directly")
                    console.print("  • [cyan]Tab[/cyan] completion for commands and file paths")
                    console.print("  • Shell output is automatically included in next agent prompt")
                elif user_input.lower() == 'setup':
                    create_example_configuration(config_mgr=ConfigManager(), context_ldr=ContextLoader())
                    console.print("[green]Edit files and reload to update agent context[/green]")
                elif user_input.lower() == 'status':
                    show_status(config_mgr=ConfigManager(), context_ldr=ContextLoader())
                elif user_input.lower() == 'shell':
                    shell_manager.toggle_shell_mode()
                    continue
                elif user_input.startswith('add_mcp '):
                    # Handle dynamic MCP server addition
                    try:
                        mcp_arg = user_input[8:].strip()

                        # Try JSON first (Clippy format)
                        try:
                            import json
                            config = json.loads(mcp_arg)
                            url = config.get('url')
                            tool_name = config.get('name')
                        except (json.JSONDecodeError, AttributeError):
                            # Fall back to positional format
                            parts = mcp_arg.split(' ', 1)
                            url = parts[0] if parts else None
                            tool_name = parts[1] if len(parts) > 1 else None

                        if not url:
                            console.print("[red]Usage: add_mcp <url> [name] OR add_mcp {\"url\":\"...\",\"name\":\"...\"}[/red]")
                            continue

                        console.print(f"[yellow]Adding MCP server: {url}[/yellow]")
                        mcp_tool = mcp2tool(url, tool_name)

                        if mcp_tool:
                            agent.agent.add_tool(mcp_tool)
                            dynamic_mcp_tools.append(mcp_tool)
                            actual_name = getattr(mcp_tool, 'name', 'unknown')
                            console.print(f"[green]✅ Added MCP tool '{actual_name}' from {url}[/green]")
                        else:
                            console.print(f"[red]❌ Failed to create MCP tool from {url}[/red]")
                    except Exception as e:
                        console.print(f"[red]❌ Error adding MCP server: {str(e)}[/red]")
                        logger.error(f"MCP addition error: {e}")
                    continue
                elif user_input.strip() == '':
                    continue
                elif shell_manager.is_shell_mode:
                    # Shell mode: execute command and capture output
                    console.print(f"[dim]$ {user_input}[/dim]")
                    output = shell_manager.execute_shell_command(user_input)
                    console.print(output)
                    continue
                else:
                    # Agent mode
                    if agent is None:
                        console.print("[yellow]Agent not initialized. Run 'setup' first.[/yellow]")
                        continue

                    # Beautiful unified streaming execution 🚀
                    try:
                        # Check for directory changes and add to user input if needed
                        dir_update = check_directory_changes(code_session.working_directory, cache_timestamp)
                        if dir_update:
                            # Update cache with fresh listing
                            directory_cache, cache_timestamp = get_directory_listing(code_session.working_directory)

                        # Add shell context to the user input if available
                        shell_context = shell_manager.get_shell_context_for_agent()
                        enhanced_input = user_input

                        # Prepend contexts in order: directory updates, then shell context
                        context_parts = []
                        if dir_update:
                            context_parts.append(dir_update)
                        if shell_context:
                            context_parts.append(shell_context)

                        if context_parts:
                            context_str = "\n".join(context_parts)
                            enhanced_input = f"{context_str}\n\nUser request: {user_input}"

                        status_message = f"Calculating: {user_input[:40]}..."
                        status_interface.start_execution(status_message)
                        output_message = ""
                        running_agent = tg.create_task(
                            agent.arun(enhanced_input, confirmation_handler, tg, status_queue, output_queue)
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
        
            finally:
                # No MCP cleanup needed - custom MCP implementation will handle this
                pass
            



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
