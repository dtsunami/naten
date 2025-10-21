"""Textual-based file restore menu for version selection."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, DataTable, Button, Footer, Header
from textual.screen import Screen
from textual import events
from typing import Optional, Dict, List, Tuple


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

    async def action_restore_session(self) -> None:
        """Restore entire session (revert all changes)."""
        from .textual_confirmation import show_confirmation_dialog

        try:
            confirmed = await show_confirmation_dialog(
                "Restore Entire Session?",
                "This will revert ALL files to their session start state. This action cannot be undone.",
                self.console_ref
            )

            if confirmed:
                # Return special marker for session restore
                result = {
                    "restore_session": True
                }
                self.app.exit(result)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Session restore confirmation failed: {e}", exc_info=True)


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