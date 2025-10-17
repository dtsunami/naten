"""Textual-based context manager UI for token management."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, DataTable, Button, Footer, Header
from textual.screen import Screen
from textual import events
from rich.text import Text


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