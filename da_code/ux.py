"""User experience module - UI prompts and splash screens for da_code CLI."""

import os
import time
import asyncio
import random
import sys
from typing import List, Optional

from da_code.models import ConfirmationResponse, UserResponse, CommandExecution
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.status import Status

# Global console for clean interaction
console = Console()

#====================================================================================================
# Status Interface Class
#====================================================================================================


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


#====================================================================================================
# UI / Prompting Functions
#====================================================================================================


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
        selected_index = 0  # Initialize locally

        try:
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
                        config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "color": "white"})
                        print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)
                    elif key == '\x1b[B':  # Down
                        selected_index = (selected_index + 1) % len(choices)
                        config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "color": "white"})
                        print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)

                # Enter key
                elif key in ['\r', '\n']:
                    print('\r\033[K', end='', flush=True)
                    return choices[selected_index]

                # Ctrl+C
                elif key == '\x03':
                    raise KeyboardInterrupt()

        finally:
            pass

    # Get choice asynchronously
    loop = asyncio.get_event_loop()
    selected_choice = await loop.run_in_executor(None, get_keypress_choice)

    # Show clean selection result in console history
    config = choice_config.get(selected_choice.lower(), {"label": selected_choice, "color": "white"})
    console.print(f"[green bold]✅ Selected: {config['label']}[/green bold]")

    return selected_choice


def display_simple_confirmation(execution) -> None:
    """Display simplified command confirmation panel using UserResponse enum."""
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


async def async_prompt_text(message: str, default: str = None) -> str:
    """Async wrapper for Rich text prompts."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: Prompt.ask(message, default=default)
    )


async def confirmation_handler(execution: CommandExecution, status_interface: SimpleStatusInterface) -> ConfirmationResponse:
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


#====================================================================================================
# Splash Screen Functions
#====================================================================================================


def get_splash_screen() -> str:
    """Get the da_code ASCII splash screen."""
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

"""User experience module - UI prompts and splash screens for da_code CLI."""

import os
import time
import asyncio
import random
import sys
from typing import List, Optional

from da_code.models import ConfirmationResponse, UserResponse, CommandExecution
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.status import Status

# Global console for clean interaction
console = Console()

#====================================================================================================
# Status Interface Class
#====================================================================================================


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


#====================================================================================================
# UI / Prompting Functions
#====================================================================================================


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
        selected_index = 0  # Initialize locally

        try:
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
                        config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "color": "white"})
                        print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)
                    elif key == '\x1b[B':  # Down
                        selected_index = (selected_index + 1) % len(choices)
                        config = choice_config.get(choices[selected_index].lower(), {"label": choices[selected_index], "color": "white"})
                        print(f"\r\033[K▶ {selected_index + 1}. {config['label']}", end='', flush=True)

                # Enter key
                elif key in ['\r', '\n']:
                    print('\r\033[K', end='', flush=True)
                    return choices[selected_index]

                # Ctrl+C
                elif key == '\x03':
                    raise KeyboardInterrupt()

        finally:
            pass

    # Get choice asynchronously
    loop = asyncio.get_event_loop()
    selected_choice = await loop.run_in_executor(None, get_keypress_choice)

    # Show clean selection result in console history
    config = choice_config.get(selected_choice.lower(), {"label": selected_choice, "color": "white"})
    console.print(f"[green bold]✅ Selected: {config['label']}[/green bold]")

    return selected_choice


def display_simple_confirmation(execution) -> None:
    """Display simplified command confirmation panel using UserResponse enum."""
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


async def async_prompt_text(message: str, default: str = None) -> str:
    """Async wrapper for Rich text prompts."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: Prompt.ask(message, default=default)
    )


async def confirmation_handler(execution: CommandExecution, status_interface: SimpleStatusInterface) -> ConfirmationResponse:
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


#====================================================================================================
# Splash Screen Functions
#====================================================================================================


def get_splash_screen() -> str:
    """Get the da_code ASCII splash screen."""
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
