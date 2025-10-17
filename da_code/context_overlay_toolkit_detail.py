"""Full context breakdown display with management actions for context overlay."""

from rich.panel import Panel
from rich.table import Table


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

        components = breakdown['components']
        total_tokens = breakdown['total_tokens']
        max_tokens = breakdown['max_tokens']
        usage_pct = breakdown['usage_pct']

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