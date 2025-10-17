"""Textual-based confirmation dialog for command execution."""

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static, Button
from textual.screen import ModalScreen
from textual import events
from da_code.models import ConfirmationResponse, UserResponse, CommandExecution


class ConfirmationScreen(ModalScreen[ConfirmationResponse]):
    """Modal confirmation dialog with Yes/No/Modify/Explain options."""

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

    Button {
        margin: 0 1;
    }

    Button.yes {
        background: $success;
    }

    Button.no {
        background: $error;
    }

    Button.modify {
        background: $warning;
    }

    Button.explain {
        background: $accent;
    }
    """

    def __init__(self, execution: CommandExecution):
        super().__init__()
        self.execution = execution
        self.selected_choice = None

    def compose(self) -> ComposeResult:
        """Compose the confirmation dialog."""
        with Container(id="dialog"):
            yield Static("🤖 Confirm Agent Command", id="title")
            yield Static(
                f"Command: `{self.execution.command}`",
                id="command"
            )

            with Vertical(id="buttons"):
                yield Button("✅ Yes (1)", variant="success", id="yes", classes="yes")
                yield Button("❌ No (2)", variant="error", id="no", classes="no")
                yield Button("✏️  Modify (3)", variant="warning", id="modify", classes="modify")
                yield Button("❓ Explain (4)", variant="primary", id="explain", classes="explain")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id

        if button_id == "yes":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.YES.value,
                modified_command=None
            ))
        elif button_id == "no":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.NO.value,
                modified_command=None
            ))
        elif button_id == "modify":
            # For now, just return modify - we'll handle text input separately
            # TODO: Add input dialog for modified command
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.MODIFY.value,
                modified_command=self.execution.command
            ))
        elif button_id == "explain":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.EXPLAIN.value,
                modified_command=None
            ))

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard shortcuts."""
        if event.key == "1":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.YES.value,
                modified_command=None
            ))
        elif event.key == "2":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.NO.value,
                modified_command=None
            ))
        elif event.key == "3":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.MODIFY.value,
                modified_command=self.execution.command
            ))
        elif event.key == "4":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.EXPLAIN.value,
                modified_command=None
            ))
        elif event.key == "escape":
            self.dismiss(ConfirmationResponse(
                choice=UserResponse.NO.value,
                modified_command=None
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

    # Return default "No" if user closed without selecting
    if result is None:
        return ConfirmationResponse(
            choice=UserResponse.NO.value,
            modified_command=None
        )

    return result