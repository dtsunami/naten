"""Modern UI components for da_code using Rich and Questionary."""

import asyncio
import os
import signal
from typing import Any, Callable, List, Optional, Dict
from contextlib import asynccontextmanager

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.syntax import Syntax

console = Console()


class ModernUI:
    """Modern UI with Rich formatting and Questionary interactions."""

    def __init__(self, auto_accept: Optional[bool] = None):
        """Initialize modern UI.

        Args:
            auto_accept: If True, auto-accept all confirmations.
                        If None, read from environment variable DA_CODE_AUTO_ACCEPT.
        """
        if auto_accept is None:
            auto_accept = os.getenv("DA_CODE_AUTO_ACCEPT", "false").lower() == "true"

        self.auto_accept = auto_accept
        self.cancel_event = asyncio.Event()

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful cancellation."""
        def signal_handler(signum, frame):
            console.print("\n🚫 Operation cancelled by user (Ctrl+C)")
            self.cancel_event.set()

        signal.signal(signal.SIGINT, signal_handler)

    def show_command_info(self, command: str, explanation: str = "",
                         working_directory: str = "", reasoning: str = "",
                         related_files: List[str] = None) -> None:
        """Display formatted command information."""

        # Create command info table
        table = Table(show_header=True, header_style="bold blue", expand=True)
        table.add_column("Property", style="cyan", width=15)
        table.add_column("Value", style="white")

        table.add_row("Command", f"[bold yellow]{command}[/bold yellow]")
        table.add_row("Directory", working_directory or "[dim]current[/dim]")

        if explanation:
            table.add_row("Purpose", explanation)

        if reasoning:
            table.add_row("Reasoning", reasoning)

        if related_files:
            files_text = ", ".join(related_files)
            table.add_row("Related Files", files_text)

        # Show in a panel
        console.print(Panel(
            table,
            title="🔧 Tool Execution Request",
            border_style="blue",
            expand=True
        ))

    async def confirm_command(self, command: str, explanation: str = "",
                            working_directory: str = "", reasoning: str = "",
                            related_files: List[str] = None) -> str:
        """Show modern interactive confirmation dialog.

        Returns:
            str: "yes", "no", "modify", or "explain"
        """

        # Check auto-accept dynamically (in case env var was set after init)
        auto_accept = self.auto_accept or os.getenv("DA_CODE_AUTO_ACCEPT", "false").lower() == "true"

        if auto_accept:
            console.print("[green]🤖 Auto-accepting command (DA_CODE_AUTO_ACCEPT=true)[/green]")
            return "yes"

        # Show command information
        self.show_command_info(command, explanation, working_directory, reasoning, related_files)

        # Interactive choice menu
        try:
            choice = questionary.select(
                "How would you like to proceed?",
                choices=[
                    questionary.Choice("✅ Execute", value="yes"),
                    questionary.Choice("❌ Cancel", value="no"),
                    questionary.Choice("✏️ Modify", value="modify"),
                    questionary.Choice("ℹ️ Explain", value="explain")
                ],
                default="✅ Execute",
                style=questionary.Style([
                    ('question', 'bold'),
                    ('answer', 'fg:#ff9d00 bold'),
                    ('pointer', 'fg:#ff9d00 bold'),
                    ('highlighted', 'fg:#ff9d00 bold'),
                    ('selected', 'fg:#cc5454'),
                    ('separator', 'fg:#cc5454'),
                    ('instruction', ''),
                    ('text', ''),
                    ('disabled', 'fg:#858585 italic')
                ]),
                instruction="(Use ↑↓ arrows, Enter to select, Ctrl+C to cancel)"
            ).ask()

            return choice or "no"  # None means ESC/Ctrl+C pressed

        except KeyboardInterrupt:
            console.print("[red]❌ Operation cancelled by user[/red]")
            return "no"
        except Exception as e:
            console.print(f"[red]❌ Error in confirmation dialog: {e}[/red]")
            return "no"

    async def get_command_modification(self, original_command: str) -> Optional[str]:
        """Get command modification with syntax highlighting."""

        # Show original command with syntax highlighting
        console.print(Panel(
            Syntax(original_command, "bash", theme="monokai"),
            title="Original Command",
            border_style="yellow"
        ))

        try:
            modified = questionary.text(
                "Enter your modified command:",
                default=original_command,
                style=questionary.Style([
                    ('question', 'bold'),
                    ('answer', 'fg:#ff9d00'),
                ])
            ).ask()

            if not modified or modified.strip() == original_command.strip():
                return None

            return modified.strip()

        except KeyboardInterrupt:
            console.print("[red]❌ Modification cancelled[/red]")
            return None

    @asynccontextmanager
    async def live_status(self, status_text: str = "Executing...",
                         show_spinner: bool = True):
        """Context manager for live status updates with cancellation support."""

        self.cancel_event.clear()
        self._setup_signal_handlers()

        if show_spinner:
            status_renderable = Spinner("dots", text=status_text, style="cyan")
        else:
            status_renderable = Text(status_text, style="cyan")

        with Live(status_renderable, console=console, refresh_per_second=10) as live:
            try:
                yield live
            except asyncio.CancelledError:
                live.update(Text("❌ Operation cancelled", style="red"))
                raise
            except Exception as e:
                live.update(Text(f"❌ Error: {e}", style="red"))
                raise

    async def execute_with_status(self,
                                execution_func: Callable,
                                status_text: str = "Executing...",
                                *args, **kwargs) -> Any:
        """Execute function with live status updates and cancellation support."""

        async with self.live_status(status_text) as live:
            # Create cancellation task
            cancel_task = asyncio.create_task(self._wait_for_cancel())
            execution_task = asyncio.create_task(execution_func(*args, **kwargs))

            try:
                # Race between execution and cancellation
                done, pending = await asyncio.wait(
                    [execution_task, cancel_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Check which completed
                if cancel_task in done:
                    execution_task.cancel()
                    raise asyncio.CancelledError("Operation cancelled by user")

                # Get result from execution
                return execution_task.result()

            except asyncio.CancelledError:
                live.update(Text("❌ Operation cancelled by user", style="red"))
                raise
            except Exception as e:
                live.update(Text(f"❌ Error: {e}", style="red"))
                raise

    async def _wait_for_cancel(self):
        """Wait for cancellation event."""
        await self.cancel_event.wait()

    def show_success(self, message: str, details: Optional[str] = None):
        """Show success message."""
        content = f"[bold green]{message}[/bold green]"
        if details:
            content += f"\n{details}"

        console.print(Panel(
            content,
            title="✅ Success",
            border_style="green"
        ))

    def show_error(self, message: str, details: Optional[str] = None):
        """Show error message."""
        content = f"[bold red]{message}[/bold red]"
        if details:
            content += f"\n[red]{details}[/red]"

        console.print(Panel(
            content,
            title="❌ Error",
            border_style="red"
        ))

    def show_warning(self, message: str, details: Optional[str] = None):
        """Show warning message."""
        content = f"[bold yellow]{message}[/bold yellow]"
        if details:
            content += f"\n[yellow]{details}[/yellow]"

        console.print(Panel(
            content,
            title="⚠️ Warning",
            border_style="yellow"
        ))

    async def chat_with_agent(self, agent_chat_func: Callable[[str], Any],
                             message: str) -> Optional[str]:
        """Execute agent chat with modern status display."""
        try:
            async with self.live_status("🤖 Assistant: Thinking..."):
                result = await agent_chat_func(message)
                return result
        except asyncio.CancelledError:
            console.print("[yellow]🚫 Chat cancelled by user[/yellow]")
            return None
        except Exception as e:
            self.show_error("Agent chat failed", str(e))
            return None


# Global modern UI instance
modern_ui = ModernUI()


# Compatibility functions for existing code
def confirm_command(command: str, explanation: str = "", working_directory: str = "",
                   reasoning: str = "", related_files: List[str] = None) -> str:
    """Compatibility wrapper for existing confirm_command calls."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        modern_ui.confirm_command(command, explanation, working_directory, reasoning, related_files)
    )


def get_command_modification(original_command: str) -> Optional[str]:
    """Compatibility wrapper for existing get_command_modification calls."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        modern_ui.get_command_modification(original_command)
    )