"""Interactive context management UI - delete and summarize context components."""

from typing import Optional
from rich.panel import Panel
from rich.table import Table
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter


async def show_context_manager(agent, console) -> None:
    """
    Interactive context management UI.

    Shows context breakdown and lets user:
    - Delete components (clear history, memory, etc)
    - Summarize components (compress with LLM - stubbed for now)

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
                title="[bold cyan]🗑️  Context Manager[/bold cyan]",
                border_style="cyan"
            )
            console.print(panel)
            console.print()
            return

        components = breakdown['components']
        total_tokens = breakdown['total_tokens']
        max_tokens = breakdown['max_tokens']
        usage_pct = breakdown['usage_pct']

        # Create table
        table = Table(show_header=True, header_style="bold cyan", padding=(0, 1), expand=False)
        table.add_column("#", style="dim", width=3)
        table.add_column("Component", style="white", width=20, no_wrap=True)
        table.add_column("Usage", style="", width=25)
        table.add_column("Tokens", justify="right", style="cyan", width=10)
        table.add_column("%", justify="right", style="yellow", width=6)

        # Build component index for easy selection
        component_map = {}

        # Add rows for each component
        for idx, component in enumerate(components, start=1):
            name = component['name']
            tokens = component['tokens']
            pct = component['percentage']
            component_id = component.get('id', name.lower().replace(' ', '_'))

            component_map[str(idx)] = {
                'id': component_id,
                'name': name,
                'tokens': tokens,
                'pct': pct
            }

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

            table.add_row(
                f"[cyan]{idx}[/cyan]",
                name,
                f"[{bar_color}]{bar}[/{bar_color}]",
                f"{tokens:,}",
                f"{pct:.1f}%"
            )

        # Add Cancel option as the last numbered row
        cancel_idx = len(components) + 1
        component_map[str(cancel_idx)] = {
            'id': '__cancel__',
            'name': 'Cancel',
            'tokens': 0,
            'pct': 0
        }
        table.add_row(
            f"[dim]{cancel_idx}[/dim]",
            "[dim]Cancel[/dim]",
            "",
            "",
            ""
        )

        # Print header
        status_color = "green" if usage_pct < 50 else "yellow" if usage_pct < 70 else "red"
        console.print(f"\n[bold cyan]🗑️  Context Manager[/bold cyan]")
        console.print(f"[bold]Total Context: [{status_color}]{total_tokens:,} / {max_tokens:,} tokens ({usage_pct:.1f}%)[/{status_color}][/bold]")
        console.print()

        # Print table
        console.print(table)
        console.print()

        # Show help
        console.print("[bold]Actions:[/bold]")
        console.print("  [cyan]delete[/cyan]    - Remove component from context")
        console.print("  [cyan]summarize[/cyan] - Compress component (LLM summary)")
        console.print("  [cyan]cancel[/cyan]    - Exit without changes")
        console.print()

        # Interactive selection
        try:
            # Create session for async prompts
            session = PromptSession()

            # Get component selection
            component_keys = list(component_map.keys())
            component_completer = WordCompleter(component_keys, ignore_case=True)

            selection = await session.prompt_async(
                "Select component [1-{}]: ".format(len(component_keys)),
                completer=component_completer
            )
            selection = selection.strip()

            if selection.lower() in ['cancel', 'exit', 'q', '']:
                console.print("[dim]Cancelled[/dim]\n")
                return

            if selection not in component_map:
                console.print(f"[red]Invalid selection: {selection}[/red]\n")
                return

            selected = component_map[selection]

            # Handle cancel selection
            if selected['id'] == '__cancel__':
                console.print("[dim]Cancelled[/dim]\n")
                return

            # Get action selection
            action_completer = WordCompleter(['delete', 'summarize', 'cancel'], ignore_case=True)
            action = await session.prompt_async(
                f"Action for '{selected['name']}' [delete/summarize/cancel]: ",
                completer=action_completer
            )
            action = action.strip().lower()

            if action in ['cancel', 'exit', 'q', '']:
                console.print("[dim]Cancelled[/dim]\n")
                return

            if action == 'delete':
                success = mgr.delete_component(selected['id'])
                if success:
                    console.print(f"[green]✓ Deleted {selected['name']} ({selected['tokens']:,} tokens freed)[/green]\n")
                else:
                    console.print(f"[red]✗ Failed to delete {selected['name']}[/red]\n")

            elif action == 'summarize':
                result = mgr.summarize_component(selected['id'])
                if result:
                    console.print(f"[green]✓ Summarized {selected['name']}[/green]")
                    console.print(f"[dim]Before: {result['before_tokens']:,} tokens → After: {result['after_tokens']:,} tokens[/dim]")
                    console.print(f"[cyan]Saved {result['saved_tokens']:,} tokens ({result['reduction_pct']:.1f}% reduction)[/cyan]\n")
                else:
                    console.print(f"[red]✗ Failed to summarize {selected['name']}[/red]\n")

            else:
                console.print(f"[red]Invalid action: {action}[/red]\n")

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cancelled[/dim]\n")
            return

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Context manager UI failed: {e}", exc_info=True)
        console.print(f"\n[red]Context manager error: {e}[/red]\n")