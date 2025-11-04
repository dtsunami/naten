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
from rich.table import Table
from rich.prompt import Prompt
from rich.text import Text
from rich.status import Status

# Global console for clean interaction
console = Console()

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, DataTable, Button, Footer, Header, Input
from textual.screen import Screen, ModalScreen
from textual import events
from typing import Optional, Dict, List, Tuple

#====================================================================================================
# Random Status Phrases
#====================================================================================================

THINKING_PHRASES = [
    "🤔 Pondering",
    "🧠 Analyzing",
    "💭 Contemplating",
    "🔍 Investigating",
    "⚡ Processing",
    "🎯 Strategizing",
    "🔬 Examining",
    "💡 Ideating",
    "🌟 Evaluating",
    "🚀 Computing",
    "🎨 Crafting",
    "🔧 Planning",
    "📊 Assessing",
    "🎪 Orchestrating",
    "🌊 Flowing through",
]

SPINNERS = ["dots", "line", "simpleDots", "arc", "circle", "bouncingBar"]


def get_random_thinking_phrase() -> str:
    """Get a random thinking phrase for status messages."""
    return random.choice(THINKING_PHRASES)


def get_random_spinner() -> str:
    """Get a random spinner style."""
    return random.choice(SPINNERS)

#====================================================================================================
# Status Interface Class
#====================================================================================================


class SimpleStatusInterface:
    """Simple status interface with Rich spinner and agent insights.

    New features:
    - pause_execution(): stop the visual spinner without resetting internal metrics/start_time
      (useful for temporary modal prompts like confirmations)
    - resume_execution(): restart the spinner and timer preserving metrics and start_time
    """

    def __init__(self):
        self.start_time = None
        self.current_status = None
        self._timer_task = None
        self.llm_calls = 0
        self.tool_calls = 0
        self.total_tokens = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.callback_handler = None
        # Agent metrics
        self.agent_metrics = {'calls': 0, 'tokens': 0}
        self.current_spinner = get_random_spinner()
        # Setup logger for debug/diagnostic messages
        import logging
        self._logger = logging.getLogger(__name__)

    def ensure_visual_display(self, preserve_metrics: bool = True) -> bool:
        """Attempt to (re)build the Rich.Status visual without resetting internal metrics.

        Returns True on success, False on failure. This is safer than calling
        start_execution() which resets metrics.
        """
        try:
            # If there's an existing status, stop it cleanly first
            if getattr(self, 'current_status', None):
                try:
                    self.current_status.stop()
                except Exception:
                    pass

            # Recreate the visual status using stored last message
            last_msg = getattr(self, '_last_message', 'Processing...')
            self.current_status = Status(f"🤖 {last_msg}", spinner=self.current_spinner)
            try:
                self.current_status.start()
            except Exception as e:
                self._logger.debug(f"ensure_visual_display: Status.start() failed: {e}")
                return False

            # Restart timer tick loop to update display
            try:
                import threading

                def _tick():
                    try:
                        if self.current_status:
                            elapsed = time.time() - self.start_time if self.start_time else 0
                            status_text = f"🤖 {getattr(self, '_last_message', 'Processing...')} | {elapsed:.1f}s"
                            if self.llm_calls > 0:
                                status_text += f" | 🧠 {self.llm_calls}"
                            if self.tool_calls > 0:
                                status_text += f" | 🔧 {self.tool_calls}"
                            self.current_status.update(status_text)
                            self._timer_task = threading.Timer(0.8, _tick)
                            self._timer_task.daemon = True
                            self._timer_task.start()
                    except Exception:
                        pass

                # Cancel any previous timer
                if getattr(self, '_timer_task', None):
                    try:
                        self._timer_task.cancel()
                    except Exception:
                        pass

                self._timer_task = threading.Timer(0.8, _tick)
                self._timer_task.daemon = True
                self._timer_task.start()
            except Exception:
                self._logger.debug("ensure_visual_display: failed to start timer loop")
                # Not fatal - visual display may still be ok
                pass

            return True
        except Exception as e:
            try:
                self._logger.debug(f"ensure_visual_display unexpected error: {e}")
            except Exception:
                pass
            return False

    def start_execution(self, message: str):
        """Start execution with status message and start background timer for updates.

        This resets the timers and metrics (for a fresh execution)."""
        self.start_time = time.time()
        self.llm_calls = 0
        self.tool_calls = 0
        self.total_tokens = 0
        self.input_tokens = 0
        self.output_tokens = 0
        # Reset agent metrics
        self.agent_metrics = {'calls': 0, 'tokens': 0}
        self.current_spinner = get_random_spinner()
        self.current_status = Status(f"🤖 {message}", spinner=self.current_spinner)
        self.current_status.start()

        # Keep track of the initial message for resume scenarios
        self._last_message = message

        # Start a lightweight background timer task that periodically refreshes the status text.
        # We keep it synchronous-friendly by using threading.Timer so it works both in sync and
        # asyncio contexts where the event loop may not be running.
        try:
            import threading

            # Cancel any previous timer
            if getattr(self, '_timer_task', None):
                try:
                    self._timer_task.cancel()
                except Exception:
                    pass

            def _tick():
                try:
                    # Only update if status is still active
                    if self.current_status:
                        # Compute a short status label without heavy formatting
                        elapsed = time.time() - self.start_time if self.start_time else 0
                        status_text = f"🤖 {self._last_message} | {elapsed:.1f}s"
                        if self.llm_calls > 0:
                            status_text += f" | 🧠 {self.llm_calls}"
                        if self.tool_calls > 0:
                            status_text += f" | 🔧 {self.tool_calls}"
                        self.current_status.update(status_text)
                        # Schedule next tick
                        self._timer_task = threading.Timer(0.8, _tick)
                        self._timer_task.daemon = True
                        self._timer_task.start()
                except Exception as e:
                    import logging
                    logging.debug(f"Timer tick failed: {e}")

            # Start the first tick
            self._timer_task = threading.Timer(0.8, _tick)
            self._timer_task.daemon = True
            self._timer_task.start()
        except Exception:
            # If threading isn't available for some reason, silently skip the timer.
            pass

    def update_status(self, message: str):
        """Update the current status message."""
        if self.current_status:
            elapsed = time.time() - self.start_time if self.start_time else 0
            status_text = f"🤖 {message} | {elapsed:.1f}s"
            if self.llm_calls > 0:
                status_text += f" | 🧠 {self.llm_calls}"
            if self.tool_calls > 0:
                status_text += f" | 🔧 {self.tool_calls}"
            if self.total_tokens > 0:
                # Format tokens nicely (e.g., 1.2k instead of 1234)
                if self.total_tokens >= 1000:
                    token_str = f"{self.total_tokens/1000:.1f}k"
                else:
                    token_str = str(self.total_tokens)
                status_text += f" | 🎯 {token_str}"
                # Add input/output breakdown if available
                if self.input_tokens > 0 or self.output_tokens > 0:
                    status_text += f" (↓{self.input_tokens}↑{self.output_tokens})"
            # Update last displayed message so pause/resume can restore it
            self._last_message = message
            self.current_status.update(status_text)

    def log_llm_call(self, tokens_used: int = 0, input_tokens: int = 0, output_tokens: int = 0):
        """Log an LLM call."""
        self.llm_calls += 1
        if tokens_used > 0:
            self.total_tokens += tokens_used
        if input_tokens > 0:
            self.input_tokens += input_tokens
        if output_tokens > 0:
            self.output_tokens += output_tokens
        self.update_status("Thinking...")

    def log_tool_call(self, tool_name: str = ""):
        """Log a tool call."""
        self.tool_calls += 1
        self.update_status(f"Using tool: {tool_name}" if tool_name else "Using tool...")

    def track_agent_call(self, tokens: int = 0):
        """Track agent calls and token usage."""
        self.agent_metrics['calls'] += 1
        self.agent_metrics['tokens'] += tokens

    def stop_execution(self, success: bool = True, final_message: str = None, silent: bool = False):
        """Stop execution and show final result.

        This stops the visual spinner, clearing the status, but leaves internal
        metrics intact unless called from start_execution which intentionally
        resets them.
        """
        # Cancel any background timer task we started
        if getattr(self, '_timer_task', None):
            try:
                self._timer_task.cancel()
            except Exception:
                pass
            finally:
                self._timer_task = None

        if self.current_status:
            try:
                self.current_status.stop()
            except Exception:
                pass

        if not silent:
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

        # Keep internal metrics (llm_calls/tool_calls/tokens) so caller can resume the status
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
        "modify": {"label": "✏️  Modify", "desc": "Edit the command before execution", "color": "yellow"},
        "reprompt": {"label": "❓ Reprompt", "desc": "Send agent info to correct the command", "color": "blue"}
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


# Add pause/resume helpers for temporary modals so we don't reset metrics during confirmation
def pause_execution(status: SimpleStatusInterface):
    """Pause visual status spinner but keep metrics intact.

    This now explicitly clears the current_status reference and returns when
    complete. It also performs a prompt_toolkit invalidate() to force a redraw
    of the input prompt so Rich/Textual overlays don't leave stray artifacts.
    """
    try:
        if not status:
            return

        if getattr(status, 'current_status', None):
            try:
                status.current_status.stop()
            except Exception:
                pass
            finally:
                # Explicitly clear visual reference to avoid half-stopped objects
                status.current_status = None

        # Cancel timer but DO NOT reset metrics
        if getattr(status, '_timer_task', None):
            try:
                status._timer_task.cancel()
            except Exception:
                pass
            finally:
                status._timer_task = None

        # Ask prompt_toolkit to invalidate/redraw to avoid stale spinner fragments
        try:
            # Small sleep to allow terminal to restore state in some environments
            import time as _time
            # Conservative short sleep - tweak if needed per-platform
            _time.sleep(0.02)
            from prompt_toolkit.application.current import get_app
            get_app().invalidate()
        except Exception:
            pass
    except Exception:
        pass


def resume_execution(status: SimpleStatusInterface) -> bool:
    """Resume visual status spinner and timer preserving metrics and start_time.

    Returns True if the visual was successfully rebuilt, False otherwise.
    """
    try:
        if not status:
            return False

        if status and getattr(status, 'start_time', None):
            # Try to reuse the new helper to rebuild the visual display without
            # resetting metrics. This is safer than directly calling start_execution.
            success = status.ensure_visual_display(preserve_metrics=True)

            # If ensure_visual_display wasn't successful, try a conservative
            # fallback that doesn't reset metrics: attempt to re-create Status
            # inline and restart the timer loop. We return a boolean to let
            # the caller decide whether to call start_execution (which resets).
            if not success:
                try:
                    status.current_status = Status(f"🤖 {getattr(status, '_last_message', 'Processing...')}", spinner=status.current_spinner)
                    try:
                        status.current_status.start()
                    except Exception:
                        pass

                    import threading

                    def _tick():
                        try:
                            if status.current_status:
                                elapsed = time.time() - status.start_time if status.start_time else 0
                                status_text = f"🤖 {getattr(status, '_last_message', 'Processing...')} | {elapsed:.1f}s"
                                if status.llm_calls > 0:
                                    status_text += f" | 🧠 {status.llm_calls}"
                                if status.tool_calls > 0:
                                    status_text += f" | 🔧 {status.tool_calls}"
                                status.current_status.update(status_text)
                                status._timer_task = threading.Timer(0.8, _tick)
                                status._timer_task.daemon = True
                                status._timer_task.start()
                        except Exception:
                            pass

                    # Cancel any previous timer
                    if getattr(status, '_timer_task', None):
                        try:
                            status._timer_task.cancel()
                        except Exception:
                            pass

                    status._timer_task = threading.Timer(0.8, _tick)
                    status._timer_task.daemon = True
                    status._timer_task.start()
                except Exception:
                    return False

            # Give the terminal a moment and invalidate prompt_toolkit so the
            # prompt is redrawn and any overlay artifacts are removed.
            try:
                import time as _time
                _time.sleep(0.02)
                from prompt_toolkit.application.current import get_app
                get_app().invalidate()
            except Exception:
                pass

            return True
    except Exception:
        pass

    return False


async def async_prompt_text(message: str, default: str = None) -> str:
    """Async wrapper for Rich text prompts."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: Prompt.ask(message, default=default)
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


#====================================================================================================
# Full context breakdown display with management actions for context overlay.
#====================================================================================================


def show_detailed_context_breakdown(agent, console):
    """
    Show complete breakdown of ALL context components with management options.

    This provides a Pareto-style view showing:
    - System prompt, instructions, history, toolkits, memory, etc.
    - Token counts and percentages for each
    - Available management actions
    - Sorted by token usage (biggest consumers first)

    Args:
        agent: AgnoAgent instance
        console: Rich console instance
    """
    try:
        from .context_telemetry import ContextManager

        mgr = ContextManager(agent)
        breakdown = mgr.get_full_context_breakdown()

        console.print()

        if not breakdown or not breakdown.get('components'):
            panel = Panel(
                "[yellow]No context data available[/yellow]\n\n"
                "[dim]Make a request to see context breakdown[/dim]",
                title="[bold cyan]📊 Context Breakdown[/bold cyan]",
                border_style="cyan"
            )
            console.print(panel)
            console.print()
            return

        # If ContextManager was updated to return memories/history, support both shapes
        if isinstance(breakdown, dict) and 'breakdown' in breakdown:
            bd = breakdown['breakdown']
            memories = breakdown.get('memories', [])
            history = breakdown.get('history', [])
        else:
            bd = breakdown
            memories = []
            history = []

        components = bd.get('components', [])
        total_tokens = bd.get('total_tokens', 0)
        max_tokens = bd.get('max_tokens', 128000)
        usage_pct = bd.get('usage_pct', 0)

        # Create table
        table = Table(show_header=True, header_style="bold cyan", padding=(0, 1), expand=False)
        table.add_column("Component", style="white", width=25, no_wrap=True)
        table.add_column("Usage", style="", width=25)
        table.add_column("Tokens", justify="right", style="cyan", width=10)
        table.add_column("%", justify="right", style="yellow", width=6)
        table.add_column("Actions", style="dim", width=18)

        # Add rows for each component (already sorted by Pareto)
        for component in components:
            name = component['name']
            tokens = component['tokens']
            pct = component['percentage']
            description = component.get('description', '')
            actions = component.get('actions', [])

            # Create mini progress bar
            bar_width = 25
            filled = int((tokens / total_tokens * bar_width)) if total_tokens > 0 else 0
            bar = "█" * filled + "░" * (bar_width - filled)

            # Color code based on percentage
            if pct > 30:
                bar_color = "red"
            elif pct > 15:
                bar_color = "yellow"
            else:
                bar_color = "green"

            # Format actions
            actions_str = ", ".join(actions) if actions else "-"

            table.add_row(
                name,
                f"[{bar_color}]{bar}[/{bar_color}]",
                f"{tokens:,}",
                f"{pct:.1f}%",
                actions_str
            )

        # Print header
        status_color = "green" if usage_pct < 50 else "yellow" if usage_pct < 70 else "red"
        console.print(f"\n[bold cyan]📊 Full Context Breakdown[/bold cyan]")
        console.print(f"[bold]Total Context: [{status_color}]{total_tokens:,} / {max_tokens:,} tokens ({usage_pct:.1f}%)[/{status_color}][/bold]")
        console.print()

        # Print table
        console.print(table)

        # Print footer with management tips
        console.print()
        # Show small memory/chat summary if available
        if memories:
            console.print("[bold]📚 Recent Memories:[/bold]")
            for m in memories[:3]:
                console.print(f"  • {m.get('summary', '')[:120]}  [dim]{m.get('tokens',0)} tokens[/dim]")
            console.print()
        if history:
            console.print("[bold]🕘 Recent Chat Excerpts:[/bold]")
            for h in history[:5]:
                console.print(f"  • {h.get('excerpt','')[:120]}  [dim]{h.get('tokens',0)} tokens[/dim]")
            console.print()

        console.print("[bold]💡 Management Actions:[/bold]")
        console.print("[dim]The components above are sorted by token usage (Pareto principle).[/dim]")
        console.print()
        console.print("  [cyan]view[/cyan]   - View component content")
        console.print("  [cyan]edit[/cyan]   - Edit component (system/instructions)")
        console.print("  [cyan]clear[/cyan]  - Clear component (history/memory)")
        console.print("  [cyan]reduce[/cyan] - Reduce size (history depth)")
        console.print("  [cyan]disable[/cyan]- Disable toolkit")
        console.print()
        console.print("[dim]🎯 Focus on the largest components for the biggest impact.[/dim]")
        console.print("[dim]Press # once for summary view[/dim]")
        console.print()

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Context breakdown failed: {e}", exc_info=True)
        console.print(f"\n[red]Context breakdown error: {e}[/red]")


#====================================================================================================
# Textual-based file restore menu for version selection.
#====================================================================================================


class RestoreScreen(Screen):
    """Interactive file restore menu with revision selection."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("r", "restore", "Restore"),
        ("1,2,3,4,5,6,7,8,9", "select_number", "Select by number"),
    ]

    DEFAULT_CSS = """
    RestoreScreen {
        background: $surface;
    }

    #header {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $boost;
        border: solid $primary;
        margin: 0 0 1 0;
    }

    #title {
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #file-info {
        color: $text;
        padding: 0 0 1 0;
    }

    #table-container {
        width: 100%;
        height: 1fr;
        padding: 0 2;
    }

    DataTable {
        height: 100%;
    }

    #actions {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $boost;
        layout: horizontal;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }

    #help-text {
        width: 100%;
        padding: 1 2;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, file_path: str, revisions: list, has_session_start: bool, console_ref):
        """Initialize restore screen.

        Args:
            file_path: Relative path of file to restore
            revisions: List of tuples (revision_num, lines_changed, time_ago_str, timestamp)
            has_session_start: Whether file existed at session start
            console_ref: Rich console instance
        """
        super().__init__()
        self.file_path = file_path
        self.revisions = revisions
        self.has_session_start = has_session_start
        self.console_ref = console_ref
        self.selected_revision: Optional[int] = None
        self.auto_confirm = False

    def compose(self) -> ComposeResult:
        """Compose the restore UI."""
        try:
            yield Header()

            # Header with file info
            with Container(id="header"):
                yield Static("⏮️  File Restore", id="title")
                yield Static(f"File: {self.file_path}", id="file-info")

            # Data table
            with Container(id="table-container"):
                table = DataTable()
                table.cursor_type = "row"
                table.zebra_stripes = True
                table.add_column("#", width=8)
                table.add_column("Lines Changed", width=18)
                table.add_column("Time Ago", width=15)
                table.add_column("Description", width=40)

                # Add session start option (revision 0)
                if self.has_session_start:
                    table.add_row(
                        "0",
                        "-",
                        "-",
                        "Session start (original version)"
                    )
                elif self.revisions:
                    # File was created during session
                    table.add_row(
                        "0",
                        "-",
                        "-",
                        "Session start (will DELETE file)"
                    )

                # Add all revisions
                for rev_num, lines_changed, time_str, _ in self.revisions:
                    table.add_row(
                        str(rev_num),
                        f"{lines_changed} lines",
                        f"{time_str} ago",
                        f"Revision #{rev_num}"
                    )

                yield table

            # Action buttons
            with Horizontal(id="actions"):
                yield Button("Restore [R]", variant="success", id="restore")
                yield Button("Restore (skip confirm) [!]", variant="warning", id="restore-auto")
                yield Button("Cancel [Q]", variant="error", id="cancel")

            # Help text
            yield Static(
                "Use ↑/↓ or 1-9 to select • R=Restore • !=Auto-confirm • Q=Cancel",
                id="help-text"
            )

            yield Footer()

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Restore UI composition failed: {e}", exc_info=True)
            yield Static(f"Error loading restore menu: {e}", classes="error")
            yield Footer()

    def on_mount(self) -> None:
        """Focus the table when screen mounts."""
        try:
            table = self.query_one(DataTable)
            if table:
                table.focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id

        if button_id == "cancel":
            self.app.exit(None)
        elif button_id == "restore":
            self.auto_confirm = False
            self.action_restore()
        elif button_id == "restore-auto":
            self.auto_confirm = True
            self.action_restore()

    def action_restore(self) -> None:
        """Restore selected revision."""
        try:
            table = self.query_one(DataTable)
            if table.cursor_row is not None:
                # Revision 0 is session start, then 1+ for actual revisions
                selected_revision = table.cursor_row  # 0-indexed row = revision number

                # Validate selection
                max_revision = len(self.revisions)
                if selected_revision < 0 or selected_revision > max_revision:
                    self.console_ref.print(f"[red]Invalid selection[/red]")
                    self.app.exit(None)
                    return

                # Return result
                result = {
                    "revision": selected_revision,
                    "auto_confirm": self.auto_confirm
                }
                self.app.exit(result)

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Restore action failed: {e}", exc_info=True)
            self.console_ref.print(f"[red]Error during restore: {e}[/red]")
            self.app.exit(None)

    def action_quit(self) -> None:
        """Cancel restore."""
        self.app.exit(None)

    def action_select_number(self, number: str) -> None:
        """Select row by number."""
        try:
            idx = int(number)
            max_revision = len(self.revisions)
            if 0 <= idx <= max_revision:
                table = self.query_one(DataTable)
                table.move_cursor(row=idx)
        except (ValueError, TypeError):
            pass

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts."""
        # Number key selection (0-9)
        if event.key in "0123456789":
            idx = int(event.key)
            max_revision = len(self.revisions)
            if 0 <= idx <= max_revision:
                table = self.query_one(DataTable)
                table.move_cursor(row=idx)


class RestoreApp(App):
    """Standalone restore menu application."""

    def __init__(self, file_path: str, revisions: list, has_session_start: bool, console_ref):
        super().__init__()
        self.file_path = file_path
        self.revisions = revisions
        self.has_session_start = has_session_start
        self.console_ref = console_ref

    def on_mount(self) -> None:
        """Push restore screen on mount."""
        self.push_screen(RestoreScreen(
            self.file_path,
            self.revisions,
            self.has_session_start,
            self.console_ref
        ))


async def show_restore_menu(file_path: str, revisions: list, has_session_start: bool, console) -> Optional[dict]:
    """
    Show Textual-based file restore menu.

    Args:
        file_path: Relative path of file to restore
        revisions: List of tuples (revision_num, lines_changed, time_ago_str, timestamp)
        has_session_start: Whether file existed at session start
        console: Rich console instance

    Returns:
        Dict with 'revision' and 'auto_confirm' if user selected, None if cancelled
    """
    try:
        app = RestoreApp(file_path, revisions, has_session_start, console)
        result = await app.run_async()

        return result

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Restore menu app failed: {e}", exc_info=True)
        console.print(f"\n[red]Restore menu error: {e}[/red]\n")
        return None


# --- File picker support -------------------------------------------------
class FilePickerScreen(Screen):
    """Simple file picker that lists files and returns the selected path."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("enter", "select", "Select"),
        ("1,2,3,4,5,6,7,8,9", "select_number", "Select by number"),
    ]

    DEFAULT_CSS = """
    FilePickerScreen {
        background: $surface;
    }

    #header {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $boost;
        border: solid $primary;
        margin: 0 0 1 0;
    }

    #title {
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #table-container {
        width: 100%;
        height: 1fr;
        padding: 0 2;
    }

    DataTable {
        height: 100%;
    }

    #help-text {
        width: 100%;
        padding: 1 2;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, files: list, console_ref):
        super().__init__()
        self.files = files
        self.console_ref = console_ref

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="header"):
            yield Static("📁 Select file to restore", id="title")
            yield Static(f"Files: {len(self.files)}", id="file-info")

        with Container(id="table-container"):
            table = DataTable()
            table.cursor_type = "row"
            table.zebra_stripes = True
            table.add_column("#", width=6)
            table.add_column("File Path", width=100)

            for i, fp in enumerate(self.files):
                table.add_row(str(i), fp)

            yield table

        yield Static("Use ↑/↓ or 0-9 to select • Enter=Select • Q=Cancel", id="help-text")
        yield Footer()

    def on_mount(self) -> None:
        try:
            table = self.query_one(DataTable)
            if table:
                table.focus()
        except Exception:
            pass

    def action_quit(self) -> None:
        self.app.exit(None)

    def action_select_number(self, number: str) -> None:
        try:
            idx = int(number)
            if 0 <= idx < len(self.files):
                table = self.query_one(DataTable)
                table.move_cursor(row=idx)
        except Exception:
            pass

    def on_key(self, event: events.Key) -> None:
        if event.key in "0123456789":
            idx = int(event.key)
            if 0 <= idx < len(self.files):
                table = self.query_one(DataTable)
                table.move_cursor(row=idx)

    def action_select(self) -> None:
        try:
            table = self.query_one(DataTable)
            if table and table.cursor_row is not None:
                idx = table.cursor_row
                result = self.files[idx]
                self.app.exit(result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"FilePicker selection failed: {e}", exc_info=True)
            self.console_ref.print(f"[red]Error selecting file: {e}[/red]")
            self.app.exit(None)


class FilePickerApp(App):
    def __init__(self, files: list, console_ref):
        super().__init__()
        self.files = files
        self.console_ref = console_ref

    def on_mount(self) -> None:
        self.push_screen(FilePickerScreen(self.files, self.console_ref))


async def show_file_picker(files: list, console) -> Optional[str]:
    """Show a simple Textual file picker and return selected file path or None."""
    try:
        app = FilePickerApp(files, console)
        result = await app.run_async()
        return result
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"File picker failed: {e}", exc_info=True)
        console.print(f"\n[red]File picker error: {e}[/red]\n")
        return None


# --- Combined File and Revision Picker -------------------------------------------------


class CombinedRestoreScreen(Screen):
    """Combined file picker and revision history in side-by-side view."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("tab", "switch_panel", "Switch panel"),
        ("s", "restore_session", "Restore Session"),
    ]

    DEFAULT_CSS = """
    CombinedRestoreScreen {
        background: $surface;
    }

    #header {
        width: 100%;
        height: auto;
        padding: 0 2;
        background: $boost;
        border-bottom: solid $primary;
    }

    #title {
        text-style: bold;
        color: $accent;
    }

    #main-container {
        width: 100%;
        height: 1fr;
        layout: horizontal;
    }

    #files-panel {
        width: 40%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }

    #revisions-panel {
        width: 60%;
        height: 100%;
        border: solid $accent;
        padding: 1;
    }

    #files-table {
        height: 1fr;
    }

    #revisions-table {
        height: 1fr;
    }

    .panel-title {
        text-style: bold;
        padding: 0 0 1 0;
    }

    #help-text {
        width: 100%;
        padding: 1 2;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, file_data: Dict[str, Tuple[List, bool]], console_ref):
        """Initialize combined restore screen.

        Args:
            file_data: Dict mapping file_path -> (revisions_list, has_session_start)
            console_ref: Rich console instance
        """
        super().__init__()
        self.file_data = file_data
        self.console_ref = console_ref
        self.current_file: Optional[str] = None
        self.current_panel = "files"  # "files" or "revisions"
        self.auto_confirm = False

    def compose(self) -> ComposeResult:
        """Compose the combined restore UI."""
        try:
            yield Header()

            # Header
            with Container(id="header"):
                yield Static("File Restore", id="title")

            # Main container with side-by-side panels
            with Horizontal(id="main-container"):
                # Left panel: Files
                with Vertical(id="files-panel"):
                    yield Static("📁 Modified Files", classes="panel-title")
                    files_table = DataTable(id="files-table")
                    files_table.cursor_type = "row"
                    files_table.zebra_stripes = True
                    files_table.add_column("File Path", width=50)
                    files_table.add_column("Revisions", width=10)

                    # Populate files
                    for file_path, (revisions, has_session_start) in self.file_data.items():
                        revision_count = len(revisions)
                        files_table.add_row(file_path, str(revision_count))

                    yield files_table

                # Right panel: Revisions
                with Vertical(id="revisions-panel"):
                    yield Static("📝 Revision History", classes="panel-title", id="revisions-title")
                    revisions_table = DataTable(id="revisions-table")
                    revisions_table.cursor_type = "row"
                    revisions_table.zebra_stripes = True
                    revisions_table.add_column("#", width=8)
                    revisions_table.add_column("Lines Changed", width=15)
                    revisions_table.add_column("Time Ago", width=15)
                    revisions_table.add_column("Description", width=30)
                    yield revisions_table

            # Help text
            yield Static(
                "↑/↓=Select file • Tab=Switch panel • 0-9/Enter=Restore revision • S=Restore session • Q=Quit",
                id="help-text"
            )

            yield Footer()

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Combined restore UI composition failed: {e}", exc_info=True)
            yield Static(f"Error loading restore menu: {e}", classes="error")

    def on_mount(self) -> None:
        """Focus the files table when screen mounts."""
        try:
            files_table = self.query_one("#files-table", DataTable)
            if files_table:
                files_table.focus()
                # Select first file if available
                if files_table.row_count > 0:
                    files_table.move_cursor(row=0)
                    self._update_revisions_for_current_file()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"on_mount error: {e}", exc_info=True)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update revisions panel when a file is selected."""
        try:
            if event.data_table.id == "files-table":
                self._update_revisions_for_current_file()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Row highlight error: {e}", exc_info=True)

    def _update_revisions_for_current_file(self) -> None:
        """Update the revisions table based on selected file."""
        try:
            files_table = self.query_one("#files-table", DataTable)
            revisions_table = self.query_one("#revisions-table", DataTable)

            if files_table.cursor_row is None:
                return

            # Get the selected file path
            row_key = files_table.get_row_at(files_table.cursor_row)
            if not row_key:
                return

            file_path = str(row_key[0])  # First column is file path
            self.current_file = file_path

            # Update title
            title = self.query_one("#revisions-title", Static)
            title.update(f"📝 Revisions: {file_path}")

            # Clear and repopulate revisions table
            revisions_table.clear()

            if file_path in self.file_data:
                revisions, has_session_start = self.file_data[file_path]

                # Add session start option (revision 0)
                if has_session_start:
                    revisions_table.add_row(
                        "0",
                        "-",
                        "-",
                        "Session start (original)"
                    )
                elif revisions:
                    # File was created during session
                    revisions_table.add_row(
                        "0",
                        "-",
                        "-",
                        "Session start (DELETE file)"
                    )

                # Add all revisions
                for rev_num, lines_changed, time_str, _ in revisions:
                    revisions_table.add_row(
                        str(rev_num),
                        f"{lines_changed} lines",
                        f"{time_str} ago",
                        f"Revision #{rev_num}"
                    )

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Update revisions error: {e}", exc_info=True)

    def action_switch_panel(self) -> None:
        """Switch focus between files and revisions panels."""
        try:
            files_table = self.query_one("#files-table", DataTable)
            revisions_table = self.query_one("#revisions-table", DataTable)

            if self.current_panel == "files":
                revisions_table.focus()
                self.current_panel = "revisions"
            else:
                files_table.focus()
                self.current_panel = "files"
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Switch panel error: {e}", exc_info=True)

    def action_quit(self) -> None:
        """Cancel restore."""
        self.app.exit(None)

    def action_restore_selected(self) -> None:
        """Restore the currently highlighted revision."""
        try:
            if not self.current_file:
                return

            revisions_table = self.query_one("#revisions-table", DataTable)
            if revisions_table.cursor_row is None:
                return

            selected_revision = revisions_table.cursor_row
            revisions, _ = self.file_data[self.current_file]
            max_revision = len(revisions)

            # Check if the revision number is valid
            if 0 <= selected_revision <= max_revision:
                # Restore with auto_confirm=True (no confirmation for Enter key)
                result = {
                    "file_path": self.current_file,
                    "revision": selected_revision,
                    "auto_confirm": True
                }
                self.app.exit(result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Restore selected failed: {e}", exc_info=True)

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts for instant restore."""
        # Enter key - restore currently selected revision
        if event.key == "enter":
            try:
                if not self.current_file:
                    return

                revisions_table = self.query_one("#revisions-table", DataTable)
                if revisions_table.cursor_row is None:
                    return

                selected_revision = revisions_table.cursor_row
                revisions, _ = self.file_data[self.current_file]
                max_revision = len(revisions)

                # Check if the revision number is valid
                if 0 <= selected_revision <= max_revision:
                    # Instantly restore with auto_confirm=True (no confirmation)
                    result = {
                        "file_path": self.current_file,
                        "revision": selected_revision,
                        "auto_confirm": True
                    }
                    event.prevent_default()
                    event.stop()
                    self.app.exit(result)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Enter key restore failed: {e}", exc_info=True)

        # Number key selection (0-9) - instantly restore that revision
        elif event.key in "0123456789":
            try:
                idx = int(event.key)

                if not self.current_file:
                    return

                revisions, _ = self.file_data[self.current_file]
                max_revision = len(revisions)

                # Check if the revision number is valid
                if 0 <= idx <= max_revision:
                    # Instantly restore with auto_confirm=True (no confirmation)
                    result = {
                        "file_path": self.current_file,
                        "revision": idx,
                        "auto_confirm": True
                    }
                    self.app.exit(result)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Number key restore failed: {e}", exc_info=True)

    def action_restore_session(self) -> None:
        """Restore entire session (revert all changes)."""
        try:
            # Return special marker for session restore
            # Note: Caller should confirm this action before invoking
            result = {
                "restore_session": True
            }
            self.app.exit(result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Session restore action failed: {e}", exc_info=True)


class CombinedRestoreApp(App):
    """Combined file and revision restore application."""

    def __init__(self, file_data: Dict[str, Tuple[List, bool]], console_ref):
        super().__init__()
        self.file_data = file_data
        self.console_ref = console_ref

    def on_mount(self) -> None:
        """Push combined restore screen on mount."""
        self.push_screen(CombinedRestoreScreen(self.file_data, self.console_ref))


async def show_combined_restore_menu(file_data: Dict[str, Tuple[List, bool]], console) -> Optional[dict]:
    """
    Show combined file and revision restore menu.

    Args:
        file_data: Dict mapping file_path -> (revisions_list, has_session_start)
                   where revisions_list is List[(revision_num, lines_changed, time_ago_str, timestamp)]
        console: Rich console instance

    Returns:
        Dict with 'file_path', 'revision', and 'auto_confirm' if user selected, None if cancelled
    """
    try:
        app = CombinedRestoreApp(file_data, console)
        result = await app.run_async()
        return result
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Combined restore menu failed: {e}", exc_info=True)
        console.print(f"\n[red]Combined restore menu error: {e}[/red]\n")
        return None

#====================================================================================================
# Textual-based confirmation dialog for command execution.
#====================================================================================================


class ConfirmationScreen(ModalScreen[ConfirmationResponse]):
    """Modal confirmation dialog with Yes/Modify/Reprompt options."""

    DEFAULT_CSS = """
    ConfirmationScreen {
        align: center middle;
    }

    #dialog {
        width: 80;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #command {
        width: 100%;
        background: $boost;
        border: solid $accent;
        padding: 1 2;
        margin: 0 0 1 0;
    }

    #buttons {
        layout: horizontal;
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }

    #input-container {
        width: 100%;
        height: auto;
        margin: 1 0;
    }

    #input-label {
        color: $text;
        margin: 0 0 1 0;
    }

    #command-input {
        width: 100%;
        margin: 0 0 1 0;
    }

    #submit-buttons {
        layout: horizontal;
        width: 100%;
        height: auto;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }

    Button.yes {
        background: $success;
    }

    Button.edit {
        background: $warning;
    }

    Button.reprompt {
        background: $error;
    }

    .hidden {
        display: none;
    }
    """

    def __init__(self, execution: CommandExecution):
        super().__init__()
        self.execution = execution
        self.mode = None  # None, "modify", or "reprompt"

    def compose(self) -> ComposeResult:
        """Compose the confirmation dialog."""
        with Container(id="dialog"):
            yield Static("🤖 Confirm Agent Command", id="title")
            yield Static(
                f"Command: `{self.execution.command}`",
                id="command"
            )

            # Main action buttons
            with Vertical(id="buttons"):
                yield Button("✅ Yes - Confirm (1)", variant="success", id="yes", classes="yes")
                yield Button("✏️ Modify - Modify Command (2)", variant="warning", id="modify", classes="modify")
                yield Button("💬 Reprompt - Send Feedback (3)", variant="error", id="reprompt", classes="reprompt")

            # Input container (initially hidden)
            with Container(id="input-container", classes="hidden"):
                yield Static("", id="input-label")
                yield Input(id="command-input", placeholder="")
                with Horizontal(id="submit-buttons"):
                    yield Button("✓ Submit", variant="success", id="submit")
                    yield Button("← Back", variant="default", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id

        if button_id == "yes":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.YES.value,
                modified_command=None,
                reprompt_message=None
            ))
        elif button_id == "modify":
            self._show_modify_input()
        elif button_id == "reprompt":
            self._show_reprompt_input()
        elif button_id == "submit":
            self._handle_submit()
        elif button_id == "back":
            self._hide_input()

    def _show_modify_input(self):
        """Show the mondify command input field."""
        self.mode = "modify"
        # Hide main buttons
        self.query_one("#buttons").add_class("hidden")
        # Show input container
        input_container = self.query_one("#input-container")
        input_container.remove_class("hidden")
        # Set label and input value
        self.query_one("#input-label", Static).update("✏️  Edit Command:")
        command_input = self.query_one("#command-input", Input)
        command_input.value = self.execution.command
        command_input.placeholder = "Enter modified command"
        command_input.focus()

    def _show_reprompt_input(self):
        """Show the reprompt feedback input field."""
        self.mode = "reprompt"
        # Hide main buttons
        self.query_one("#buttons").add_class("hidden")
        # Show input container
        input_container = self.query_one("#input-container")
        input_container.remove_class("hidden")
        # Set label and input value
        self.query_one("#input-label", Static).update("💬 Why is this command wrong?")
        command_input = self.query_one("#command-input", Input)
        command_input.value = ""
        command_input.placeholder = "Explain what's wrong with this command..."
        command_input.focus()

    def _hide_input(self):
        """Hide the input field and show main buttons."""
        self.mode = None
        # Show main buttons
        self.query_one("#buttons").remove_class("hidden")
        # Hide input container
        self.query_one("#input-container").add_class("hidden")

    def _handle_submit(self):
        """Handle submit button based on current mode."""
        input_value = self.query_one("#command-input", Input).value

        if self.mode == "modify":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.MODIFY.value,
                modified_command=input_value,
                reprompt_message=None
            ))
        elif self.mode == "reprompt":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.REPROMPT.value,
                modified_command=None,
                reprompt_message=input_value
            ))

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts."""
        # If input is shown, Enter submits
        if self.mode in ["modify", "reprompt"]:
            if event.key == "enter":
                self._handle_submit()
                event.prevent_default()
            elif event.key == "escape":
                self._hide_input()
                event.prevent_default()
        else:
            # Main menu shortcuts
            if event.key == "1":
                self.dismiss(ConfirmationResponse(
                    choice=UserResponse.YES.value,
                    modified_command=None,
                    reprompt_message=None
                ))
            elif event.key == "2":
                # Open the modify input mode
                self._show_modify_input()
            elif event.key == "3":
                self._show_reprompt_input()
            elif event.key == "escape":
                # Escape denies the command
                self.dismiss(ConfirmationResponse(
                    choice=UserResponse.REPROMPT.value,
                    modified_command=None,
                    reprompt_message="User cancelled the command"
                ))


class ConfirmationApp(App[ConfirmationResponse]):
    """Standalone app for testing confirmation dialog."""

    def __init__(self, execution: CommandExecution):
        super().__init__()
        self.execution = execution
        self.result = None

    def on_mount(self) -> None:
        """Show confirmation screen on mount."""
        def check_result(response: ConfirmationResponse | None) -> None:
            self.result = response
            self.exit(response)

        self.push_screen(ConfirmationScreen(self.execution), check_result)


async def show_confirmation_dialog(execution: CommandExecution) -> ConfirmationResponse:
    """
    Show confirmation dialog and return user's choice.

    Args:
        execution: CommandExecution instance with command to confirm

    Returns:
        ConfirmationResponse with user's choice
    """
    app = ConfirmationApp(execution)
    result = await app.run_async()

    # Return default reprompt if user closed without selecting
    if result is None:
        return ConfirmationResponse(
            choice=UserResponse.REPROMPT.value,
            modified_command=None,
            reprompt_message="User closed dialog without selecting"
        )

    return result


#====================================================================================================
# Textual-based context manager screen.
#====================================================================================================


class ContextManagerScreen(Screen):
    """Interactive context manager with data table."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("d", "delete", "Delete"),
        ("s", "summarize", "Summarize"),
        ("1,2,3,4,5,6,7,8,9", "select_number", "Select by number"),
    ]

    DEFAULT_CSS = """
    ContextManagerScreen {
        background: $surface;
    }

    #header {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $boost;
        border: solid $primary;
        margin: 0 0 1 0;
    }

    #title {
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    #usage {
        text-style: bold;
    }

    #table-container {
        width: 100%;
        height: 1fr;
        padding: 0 2;
    }

    DataTable {
        height: 100%;
    }

    #actions {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $boost;
        layout: horizontal;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }

    .success {
        color: $success;
    }

    .warning {
        color: $warning;
    }

    .error {
        color: $error;
    }

    #help-text {
        width: 100%;
        padding: 1 2;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self, agent, console_ref):
        super().__init__()
        self.agent = agent
        self.console_ref = console_ref
        self.components = []
        self.component_map = {}
        self.breakdown = None
        self.selected_row = 0

    def compose(self) -> ComposeResult:
        """Compose the context manager UI."""
        try:
            from .context_telemetry import ContextManager

            mgr = ContextManager(self.agent)
            self.breakdown = mgr.get_full_context_breakdown()

            yield Header()

            # Check if we have data
            if not self.breakdown or not self.breakdown.get('components'):
                with Container(id="header"):
                    yield Static("🗑️  Context Manager", id="title")
                    yield Static(
                        "No context data available\n\nMake a request to see context breakdown",
                        classes="warning"
                    )
                yield Footer()
                return

            components = self.breakdown['components']
            total_tokens = self.breakdown['total_tokens']
            max_tokens = self.breakdown['max_tokens']
            usage_pct = self.breakdown['usage_pct']

            # Determine color based on usage
            if usage_pct < 50:
                usage_class = "success"
            elif usage_pct < 70:
                usage_class = "warning"
            else:
                usage_class = "error"

            # Header with usage info
            with Container(id="header"):
                yield Static("🗑️  Context Manager", id="title")
                yield Static(
                    f"Total Context: {total_tokens:,} / {max_tokens:,} tokens ({usage_pct:.1f}%)",
                    id="usage",
                    classes=usage_class
                )

            # Data table
            with Container(id="table-container"):
                table = DataTable()
                table.cursor_type = "row"
                table.zebra_stripes = True
                table.add_column("#", width=5)
                table.add_column("Component", width=25)
                table.add_column("Tokens", width=15)
                table.add_column("%", width=10)
                table.add_column("Usage Bar", width=30)

                self.components = components
                self.component_map = {}

                # Populate table
                for idx, component in enumerate(components, start=1):
                    name = component['name']
                    tokens = component['tokens']
                    pct = component['percentage']
                    component_id = component.get('id', name.lower().replace(' ', '_'))

                    self.component_map[str(idx)] = {
                        'id': component_id,
                        'name': name,
                        'tokens': tokens,
                        'pct': pct
                    }

                    # Create progress bar
                    bar_width = 30
                    filled = int((tokens / total_tokens * bar_width)) if total_tokens > 0 else 0
                    bar = "█" * filled + "░" * (bar_width - filled)

                    # Color code based on percentage
                    if pct > 30:
                        bar_color = "red"
                    elif pct > 15:
                        bar_color = "yellow"
                    else:
                        bar_color = "green"

                    table.add_row(
                        f"{idx}",
                        name,
                        f"{tokens:,}",
                        f"{pct:.1f}%",
                        f"[{bar_color}]{bar}[/{bar_color}]"
                    )

                yield table

            # Action buttons
            with Horizontal(id="actions"):
                yield Button("Delete [D]", variant="error", id="delete")
                yield Button("Summarize [S]", variant="warning", id="summarize")
                yield Button("Cancel [Q]", variant="primary", id="cancel")

            # Help text
            yield Static(
                "Use ↑/↓ or 1-9 to select • D=Delete • S=Summarize • Q=Quit",
                id="help-text"
            )

            yield Footer()

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Context manager UI composition failed: {e}", exc_info=True)
            yield Static(f"Error loading context manager: {e}", classes="error")
            yield Footer()

    def on_mount(self) -> None:
        """Focus the table when screen mounts."""
        if self.breakdown and self.breakdown.get('components'):
            table = self.query_one(DataTable)
            if table:
                table.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id

        if button_id == "cancel":
            self.app.exit(None)
        elif button_id == "delete":
            self.action_delete()
        elif button_id == "summarize":
            self.action_summarize()

    def action_delete(self) -> None:
        """Delete selected component."""
        try:
            table = self.query_one(DataTable)
            if table.cursor_row is not None and table.cursor_row < len(self.components):
                # Get the selected component (1-indexed)
                selected_idx = str(table.cursor_row + 1)
                if selected_idx in self.component_map:
                    selected = self.component_map[selected_idx]

                    # Perform deletion
                    from .context_telemetry import ContextManager
                    mgr = ContextManager(self.agent)
                    success = mgr.delete_component(selected['id'])

                    if success:
                        self.console_ref.print(
                            f"[green]✓ Deleted {selected['name']} ({selected['tokens']:,} tokens freed)[/green]"
                        )
                        self.app.exit({"action": "delete", "component": selected['name']})
                    else:
                        self.console_ref.print(
                            f"[red]✗ Failed to delete {selected['name']}[/red]"
                        )
                        self.app.exit(None)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Delete action failed: {e}", exc_info=True)
            self.console_ref.print(f"[red]Error during delete: {e}[/red]")
            self.app.exit(None)

    def action_summarize(self) -> None:
        """Summarize selected component."""
        try:
            table = self.query_one(DataTable)
            if table.cursor_row is not None and table.cursor_row < len(self.components):
                # Get the selected component (1-indexed)
                selected_idx = str(table.cursor_row + 1)
                if selected_idx in self.component_map:
                    selected = self.component_map[selected_idx]

                    # Perform summarization
                    from .context_telemetry import ContextManager
                    mgr = ContextManager(self.agent)
                    result = mgr.summarize_component(selected['id'])

                    if result:
                        self.console_ref.print(f"[green]✓ Summarized {selected['name']}[/green]")
                        self.console_ref.print(
                            f"[dim]Before: {result['before_tokens']:,} tokens → "
                            f"After: {result['after_tokens']:,} tokens[/dim]"
                        )
                        self.console_ref.print(
                            f"[cyan]Saved {result['saved_tokens']:,} tokens "
                            f"({result['reduction_pct']:.1f}% reduction)[/cyan]"
                        )
                        self.app.exit({"action": "summarize", "component": selected['name']})
                    else:
                        self.console_ref.print(
                            f"[red]✗ Failed to summarize {selected['name']}[/red]"
                        )
                        self.app.exit(None)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Summarize action failed: {e}", exc_info=True)
            self.console_ref.print(f"[red]Error during summarize: {e}[/red]")
            self.app.exit(None)

    def action_quit(self) -> None:
        """Quit the context manager."""
        self.app.exit(None)

    def action_select_number(self, number: str) -> None:
        """Select row by number."""
        try:
            idx = int(number)
            if 1 <= idx <= len(self.components):
                table = self.query_one(DataTable)
                table.move_cursor(row=idx - 1)
        except (ValueError, TypeError):
            pass

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts."""
        # Number key selection (1-9)
        if event.key in "123456789":
            idx = int(event.key)
            if 1 <= idx <= len(self.components):
                table = self.query_one(DataTable)
                table.move_cursor(row=idx - 1)


class ContextManagerApp(App):
    """Standalone context manager application."""

    def __init__(self, agent, console_ref):
        super().__init__()
        self.agent = agent
        self.console_ref = console_ref

    def on_mount(self) -> None:
        """Push context manager screen on mount."""
        self.push_screen(ContextManagerScreen(self.agent, self.console_ref))


async def show_context_manager_textual(agent, console) -> None:
    """
    Show Textual-based context manager UI.

    Args:
        agent: AgnoAgent instance
        console: Rich console instance
    """
    try:
        app = ContextManagerApp(agent, console)
        result = await app.run_async()

        # Print result message if needed
        if result:
            console.print(f"\n[green]Context manager action completed: {result['action']} on {result['component']}[/green]\n")
        else:
            console.print("\n[dim]Context manager closed without changes[/dim]\n")

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Context manager app failed: {e}", exc_info=True)
        console.print(f"\n[red]Context manager error: {e}[/red]\n")


#====================================================================================================
# Done :)
#====================================================================================================