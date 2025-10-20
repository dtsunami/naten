"""Textual-based file restore menu for version selection."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static, DataTable, Button, Footer, Header
from textual.screen import Screen
from textual import events
from typing import Optional


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