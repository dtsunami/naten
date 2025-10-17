
"""Main CLI entry point for da_code tool."""

import asyncio
import logging
import os
import shlex
import sys
import time
import subprocess

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import PathCompleter, WordCompleter, Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.application.current import get_app

from .config import ConfigManager, setup_logging
from .context import ContextLoader, DirectoryContext
from .models import CodeSession, CommandExecution, UserResponse, ConfirmationResponse, FileChange, da_mongo
from .agno_agent import AgnoAgent
from .mcp_tool import mcp2tool
from .filesystem_watcher import FileSystemWatcher
from .completers import NudgeCompleter, ShellCompleter
from .shell_manager import ShellModeManager
from .session_manager import create_session, create_example_configuration, show_status
from .ux import (
    show_splash,
    show_status_splash,
    SimpleStatusInterface,
    confirmation_handler,
    get_random_thinking_phrase,
    console  # Import the shared console from ux
)


logger = logging.getLogger(__name__)


# Windows clipboard and VT helpers ---------------------------------------------------------------

def enable_windows_vt():
    """Try to enable Virtual Terminal Processing on Windows consoles so bracketed paste
    and ANSI sequences behave more consistently. This is best-effort and will log failures.
    """
    try:
        if not sys.platform.startswith('win'):
            return False
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200

        hOut = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        hIn = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        modeOut = ctypes.c_uint()
        modeIn = ctypes.c_uint()
        if not kernel32.GetConsoleMode(hOut, ctypes.byref(modeOut)):
            logger.debug("GetConsoleMode(out) failed when enabling VT")
            return False
        if not kernel32.GetConsoleMode(hIn, ctypes.byref(modeIn)):
            logger.debug("GetConsoleMode(in) failed when enabling VT")
            return False
        kernel32.SetConsoleMode(hOut, modeOut.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        kernel32.SetConsoleMode(hIn, modeIn.value | ENABLE_VIRTUAL_TERMINAL_INPUT)
        logger.debug("Enabled Windows VT processing (best-effort)")
        return True
    except Exception as e:
        logger.debug(f"Failed to enable Windows VT processing: {e}")
        return False


def read_windows_clipboard():
    """Read Unicode text from the Windows clipboard using Win32 APIs. Returns str or None.
    This avoids depending on terminal bracketed paste and works even when the host
    intercepts Ctrl+V.
    """
    try:
        if not sys.platform.startswith('win'):
            return None
        import ctypes
        from ctypes import wintypes

        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(None):
            logger.debug("OpenClipboard failed")
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            user32.CloseClipboard()
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            user32.CloseClipboard()
            return None
        try:
            # wchar_t pointer
            text = ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
            user32.CloseClipboard()
        return text
    except Exception as e:
        logger.debug(f"read_windows_clipboard failed: {e}")
        return None


#====================================================================================================
# Context building and agent interaction
#====================================================================================================


# Available commands
commands = ['help', 'setup', 'status', 'add_mcp', 'shell', 'exit', 'quit', 'q']

# Global session ID for restart message
_current_session_id = None


def build_agent_context(
    user_input: str,
    pasted_storage: dict,
    search_storage: dict,
    dir_update: str = None,
    file_changes: str = None,
    shell_context: str = None
) -> str:
    """Build enhanced context for agent from various sources.

    Args:
        user_input: The raw user input
        pasted_storage: Dict mapping placeholders to pasted content
        search_storage: Dict mapping placeholders to search results
        dir_update: Directory change summary (optional)
        file_changes: File changes summary (optional)
        shell_context: Shell command history (optional)

    Returns:
        Enhanced input string with all context prepended
    """
    context_parts = []

    # Add pasted content ONLY if placeholder still exists in user_input
    if pasted_storage:
        pasted_sections = []
        for placeholder, pasted_text in pasted_storage.items():
            if placeholder in user_input:
                pasted_sections.append(f"Pasted content from {placeholder}:\n```\n{pasted_text}\n```")

        if pasted_sections:
            context_parts.append("\n\n".join(pasted_sections))
            logger.warning(f"Pasted content used: {' | '.join(pasted_sections)}")

        # Clear pasted content after using it
        pasted_storage.clear()

    # Add search results automatically (grep/glob results from previous commands)
    if search_storage:
        logger.warning(f"🔍 build_agent_context: search_storage has {len(search_storage)} items: {list(search_storage.keys())}")
        logger.warning(f"🔍 build_agent_context: user_input = {user_input[:200]}")

        search_sections = []
        for placeholder, search_data in search_storage.items():
            logger.warning(f"🔍 Auto-injecting search results from: '{placeholder}'")

            search_term = search_data.get('term', 'unknown')
            files_dict = search_data.get('files', {})

            # Build formatted output with line numbers and sample matches
            file_lines = []
            show_sample_lines = len(files_dict) <= 10

            for file_path, match_data in sorted(files_dict.items())[:20]:  # Limit to 20 files
                line_numbers = match_data['line_numbers']
                matches = match_data.get('matches', [])

                # Show line number range for better readability
                show_line_number_matches = 12
                if len(line_numbers) <= show_line_number_matches:
                    line_nums_str = ', '.join(map(str, line_numbers))
                else:
                    line_nums_str = f"{line_numbers[0]}-{line_numbers[show_line_number_matches-1]}, ... ({len(line_numbers)} total)"

                file_line = f"  • {file_path}: lines {line_nums_str}"

                # Optionally show sample matching lines (first 5)
                show_line_matches = 5
                if show_sample_lines and matches:
                    for match in matches[:show_line_matches]:
                        file_line += f"\n      L{match['line_num']}: {match['content']}"
                    if len(matches) > show_line_matches:
                        file_line += f"\n      ... {len(matches) - show_line_matches} more matches"

                file_lines.append(file_line)

            more_files = len(files_dict) - 20 if len(files_dict) > 20 else 0
            more_str = f"\n  ... and {more_files} more files" if more_files > 0 else ""

            search_section = f"Content search for '{search_term}' found {len(files_dict)} file{'s' if len(files_dict) != 1 else ''}:\n" + "\n".join(file_lines) + more_str
            search_sections.append(search_section)

        if search_sections:
            search_str = "\n\n".join(search_sections)
            context_parts.append(search_str)
            logger.warning(f"✅ Search content injected: {len(search_sections)} result(s)")

        # Clear search content after using it
        search_storage.clear()

    # Add other context
    if dir_update:
        context_parts.append(dir_update)
    if file_changes:
        context_parts.append(file_changes)
    if shell_context:
        context_parts.append(shell_context)

    # Combine all context with user request
    if context_parts:
        context_str = "\n\n".join(context_parts)
        return f"{context_str}\n\nUser request: {user_input}"

    return user_input


async def async_main(session_id: str = None):
    """Async main with simple status interface."""
    global _current_session_id
    status_interface = SimpleStatusInterface()
    shell_manager = ShellModeManager()

    async def confirm_wrapper(execution: CommandExecution) -> ConfirmationResponse:
        return await confirmation_handler(execution, status_interface)

    show_splash("gradient")

    # Check if we need to run setup first
    if not ConfigManager().validate_config():
        console.print("[yellow]Configuration not found. Run 'setup' to create configuration files.[/yellow]")
        console.print(f"Available commands: {', '.join(commands)}")
        # Configuration missing - return early to avoid uninitialized agent usage
        return
    else:
        # Initialize or load session
        status_interface.start_execution("Initializing session...")

        if session_id:
            # Try to load existing session
            console.print(f"[cyan]Loading session {session_id}...[/cyan]")
            code_session = await da_mongo.load_session(session_id)
            if code_session is None:
                console.print(f"[yellow]⚠️  Session {session_id} not found in MongoDB or file system[/yellow]")
                console.print(f"[cyan]Creating new session with ID {session_id} to preserve chat history[/cyan]")
                # Recreate session with the given session_id to maintain PostgreSQL chat history
                code_session = create_session(context_ldr=ContextLoader(), session_id=session_id)
                if code_session is None:
                    status_interface.stop_execution(False, "Session creation failed")
                    raise ValueError("Failed to create code session!")
            else:
                console.print(f"[green]✓ Session loaded[/green]")
        else:
            # Create new session
            code_session = create_session(context_ldr=ContextLoader())
            if code_session is None:
                status_interface.stop_execution(False, "Session creation failed")
                raise ValueError("Failed to create code session!")

        # Store session ID globally for restart message
        _current_session_id = str(code_session.id)

        # Initialize filesystem history for tracking file changes
        code_session.init_filesystem_history()

        # Capture session-start snapshot for restore functionality
        if code_session.filesystem_history:
            # Snapshotting can be expensive on large projects or when running on
            # Windows with a drive root as the working directory. Run it in a
            # background thread (non-blocking) and skip snapshotting when the
            # working directory appears to be a drive root.
            from .daignore import DaIgnore
            import functools
            daignore = DaIgnore(project_root=code_session.working_directory)
            project_root = Path(code_session.working_directory)

            try:
                # Don't attempt a full recursive snapshot if the project root is a drive root
                # (e.g. C:\) which can be extremely large on Windows.
                is_drive_root = str(project_root.resolve()) == str(Path(project_root.anchor).resolve())
            except Exception:
                is_drive_root = False

            if is_drive_root:
                logger.warning("Project root appears to be a drive root; skipping session snapshot for safety")
                status_interface.update_status("Skipping session snapshot (drive root)")
            else:
                status_interface.update_status("Scheduling session snapshot (non-blocking)...")
                # Offload the potentially expensive snapshot to a thread so the CLI stays responsive
                loop = asyncio.get_running_loop()
                # Provide a progress callback that updates the status interface with current file being indexed
                def _progress_cb(msg: str):
                    try:
                        status_interface.update_status(f"Indexing: {msg}")
                        logger.debug(f"Snapshot progress: {msg}")
                    except Exception:
                        pass

                loop.run_in_executor(None, functools.partial(code_session.filesystem_history.capture_session_start_snapshot, daignore, 10, _progress_cb))

        status_interface.update_status("Initializing Agno agent...")

        # Directory context for change detection
        dir_context = DirectoryContext(code_session.working_directory, daignore=code_session.daignore)
        directory_cache, cache_timestamp = dir_context.get_directory_listing()
        agent = AgnoAgent(code_session, directory_cache)

        # Track dynamic MCP tools
        dynamic_mcp_tools = []

        if agent is None:
            logger.error("Agent init failed, rerun setup")
        else:
            # Initialize mcp_servers display string to avoid NameError
            mcp_servers = ""

            # Get deployment name
            deployment_name = agent.config.deployment_name
            reasoning_deployment = agent.config.reasoning_deployment
            
            # Get chat memory status from agent
            try:
                if agent.db_type == 'postgre':
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
                    mongo_status_str = "[green]Mongo[/green]"
                else:
                    mongo_status_str = "[yellow]None[/yellow]"
            except:
                mongo_status_str = "[red]Unknown[/red]"
            
            if len(agent.mcp_servers) > 0:
                mcp_servers = f"\n✨ MCP Servers ([green]{'[/green]/[green]'.join([v.name for v in agent.mcp_servers])}[/green])"

            # Count total tools by summing functions in each toolkit
            function_count = 0
            for toolkit in agent.agent_tools:
                try:
                    # Each Toolkit has a 'tools' attribute with list of functions
                    if hasattr(toolkit, 'tools'):
                        function_count += len(toolkit.tools)
                    else:
                        function_count += 1  # Fallback for non-toolkit tools
                except Exception:
                    function_count += 1

            # Combined status line with tool count
            status_interface.stop_execution(True, f"🤖 {deployment_name} | 🤔 {reasoning_deployment} | 💾 {memory_status} | 📡 {mongo_status_str} | 🔧 {function_count} tools{mcp_servers}")

    # Set up history files
    agent_history = FileHistory(agent.config.history_file_path)
    shell_history_path = os.getenv('DA_CODE_SHELL_HISTORY', f'.da{os.sep}shell_history')
    shell_history = FileHistory(shell_history_path)

    # Set up completers
    shell_completer = ShellCompleter()

    # Storage for pasted content and search results (maps placeholder to content)
    pasted_content_storage = {}
    paste_counter = [0]  # Mutable counter for unique paste IDs
    search_content_storage = {}

    nudge_completer = NudgeCompleter(
        working_dir=code_session.working_directory,
        code_session=code_session,
        search_storage=search_content_storage
    )

    # Try to enable Windows VT processing early so terminals that support it behave better
    try:
        if enable_windows_vt():
            logger.debug("Windows VT enabled")
    except Exception:
        pass

    # Create key bindings for shell mode toggle and completion
    bindings = KeyBindings()

    # Use '#' (Shift+3) to toggle shell/agent mode and provide shell history navigation
    shell_history_index = [None]  # Mutable index for navigating shell_command_history

    # Cancellation flag for agent interrupt
    cancel_agent = [False]  # Mutable flag for escape key interrupt

    # Track last # press for double-press detection
    last_hash_press = [0.0]  # Mutable timestamp

    def handle_paste(pasted_text: str, buffer) -> None:
        """Shared paste handling logic for both BracketedPaste and Ctrl+V.

        This function normalizes CRLF/CR-only line endings that can appear when
        pasting from Windows/PowerShell hosts (bracketed-paste may deliver
        text with '\r' characters, which previously caused the paste to be
        treated as a single line). We normalize to '\n', trim trailing newlines,
        and then make the same decisions about direct vs placeholder insertion.
        """
        try:
            if not pasted_text:
                logger.debug("handle_paste: empty pasted_text, nothing to do")
                return

            # Normalize Windows CRLF and lone CR to \n so split() yields real lines
            if '\r' in pasted_text:
                logger.debug("handle_paste: normalizing CR/LF characters in pasted text")
            pasted_text = pasted_text.replace('\r\n', '\n').replace('\r', '\n')

            # Trim trailing newline that often accompanies pasted blocks
            pasted_text = pasted_text.rstrip('\n')
            lines = pasted_text.split('\n')
            line_count = len(lines)

            # Check if paste is a direct command - if so, paste directly without placeholder
            first_line = lines[0].strip()
            first_line_l = first_line.lower()
            direct_commands = ['add_mcp', 'add_voice']

            is_direct_command = any(first_line_l.startswith(cmd) for cmd in direct_commands)

            # Also check if it's a single-line paste (likely a command or short text)
            is_single_line = line_count == 1

            logger.warning(
                "handle_paste called: lines=%d, first_line=%r, direct=%s, single_line=%s",
                line_count, first_line[:120], is_direct_command, is_single_line
            )

            # Paste directly if it's a command or single line
            if is_direct_command or is_single_line:
                buffer.insert_text(pasted_text)
                return

            # Multi-line paste for agent context: create placeholder
            paste_counter[0] += 1
            paste_id = paste_counter[0]
            placeholder = f"[[paste#{paste_id}: {line_count} line{'s' if line_count != 1 else ''}]]"

            # Store the actual pasted content with placeholder as key
            pasted_content_storage[placeholder] = pasted_text

            # Insert placeholder in buffer
            buffer.insert_text(placeholder)
        except Exception as e:
            # Log exception and re-raise so callers can fallback if needed
            logger.error(f"handle_paste exception: {e}", exc_info=True)
            raise

    @bindings.add('$')  # '$' (Shift+4) - moved from #
    def _(event):
        """Toggle shell mode with '$' key (Shift+4)."""
        shell_manager.toggle_shell_mode()
        # Reset history navigation index when toggling modes
        shell_history_index[0] = None
        # Invalidate the application to force prompt re-render so the prompt label updates immediately
        try:
            # event.app.invalidate() will request a redraw
            event.app.invalidate()
        except Exception:
            try:
                get_app().invalidate()
            except Exception:
                pass

    @bindings.add(Keys.Escape)
    def _(event):
        """Cancel running agent with Escape key."""
        cancel_agent[0] = True

    @bindings.add(Keys.Up, filter=Condition(lambda: shell_manager.is_shell_mode), eager=True)
    def _(event):
        """Navigate up through shell command history when in shell mode."""
        # Only intercept up arrow when in shell mode and we have our in-memory history
        hist = shell_manager.shell_command_history
        if not hist:
            return
        idx = shell_history_index[0]
        if idx is None:
            idx = len(hist) - 1
        else:
            idx = max(0, idx - 1)
        shell_history_index[0] = idx
        cmd = hist[idx]
        # Replace buffer content with the command
        buf = event.current_buffer
        buf.text = cmd
        buf.cursor_position = len(cmd)

    @bindings.add(Keys.Down, filter=Condition(lambda: shell_manager.is_shell_mode), eager=True)
    def _(event):
        """Navigate down through shell command history when in shell mode."""
        hist = shell_manager.shell_command_history
        if not hist:
            return
        idx = shell_history_index[0]
        if idx is None:
            return
        if idx >= len(hist) - 1:
            # Move past the last entry -> clear buffer and reset index
            shell_history_index[0] = None
            event.current_buffer.text = ''
            return
        idx = min(len(hist) - 1, idx + 1)
        shell_history_index[0] = idx
        cmd = hist[idx]
        event.current_buffer.text = cmd
        event.current_buffer.cursor_position = len(cmd)

    @bindings.add(Keys.BracketedPaste)  # Terminal bracketed paste (clipboard)
    def _(event):
        """Intercept terminal paste: show placeholder in prompt, store actual content."""
        try:
            data = getattr(event, 'data', None)
            try:
                logger.warning("BracketedPaste event: data_present=%s", bool(data))
            except Exception:
                pass

            # If there's no data on Windows, attempt Win32 clipboard read as a fallback
            if not data and sys.platform.startswith('win'):
                try:
                    logger.warning("BracketedPaste: no data, attempting Win32 clipboard fallback")
                    wb = read_windows_clipboard()
                    if wb:
                        handle_paste(wb, event.current_buffer)
                        return
                except Exception as e:
                    logger.warning(f"BracketedPaste Win32 fallback failed: {e}")

            # Normal handling
            handle_paste(data, event.current_buffer)
        except Exception as e:
            logger.error(f"Paste error: {e}")
            # On error, do default paste if possible
            try:
                event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
            except Exception:
                pass

    @bindings.add('c-v')  # Ctrl+V
    def _(event):
        """Handle Ctrl+V paste from clipboard (desktop terminals).

        On Windows the terminal host or PSReadLine may intercept Ctrl+V, so we try
        a few approaches in order, and we log diagnostics when things don't
        return text so we can trace failures on PowerShell/Win32 hosts.
        """
        try:
            data = None
            try:
                cb = event.app.clipboard
                logger.debug("Ctrl+V: trying prompt_toolkit clipboard")
                try:
                    cd = cb.get_data()
                    # Try common attributes
                    data = getattr(cd, 'text', None) or getattr(cd, 'data', None) or None
                    logger.debug("Ctrl+V: clipboard got data (type=%s) text_present=%s", type(cd), bool(data))
                except Exception as e:
                    logger.debug(f"Ctrl+V: prompt_toolkit clipboard.get_data() failed: {e}")
                    data = None
            except Exception as e:
                logger.debug(f"Ctrl+V: event.app.clipboard access failed: {e}")
                data = None

            # If no data from prompt_toolkit clipboard and we're on Windows, try Win32 clipboard
            if not data and sys.platform.startswith('win'):
                try:
                    logger.debug("Ctrl+V: trying Win32 clipboard fallback")
                    data = read_windows_clipboard()
                    logger.debug("Ctrl+V: Win32 clipboard returned text_present=%s", bool(data))
                except Exception as e:
                    logger.debug(f"Ctrl+V: Win32 fallback failed: {e}")
                    data = None

            if data:
                handle_paste(data, event.current_buffer)
            else:
                logger.debug("Ctrl+V: no data from clipboards, falling back to paste_clipboard_data")
                # Fallback to default paste behavior
                try:
                    event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
                except Exception as e:
                    logger.debug(f"Ctrl+V: paste_clipboard_data failed: {e}")
                    # Last fallback: try to read Windows clipboard one more time
                    try:
                        data2 = read_windows_clipboard() if sys.platform.startswith('win') else None
                        if data2:
                            handle_paste(data2, event.current_buffer)
                    except Exception as e:
                        logger.error(f"Ctrl+V final fallback failed: {e}")
        except Exception as e:
            logger.error(f"Ctrl+V paste error: {e}")
            try:
                event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
            except Exception:
                pass

    @bindings.add('#')  # '#' (Shift+3) - Context window breakdown
    def _(event):
        """Show clean progress bar breakdown of context window usage (single press) or detailed toolkit breakdown (double press)."""
        try:
            import time
            from rich.panel import Panel
            from .context_telemetry import get_interceptor_stats, ContextManager, get_multi_model_stats

            # Check for double-press (within 500ms)
            now = time.time()
            is_double_press = (now - last_hash_press[0]) < 0.5
            last_hash_press[0] = now

            if is_double_press:
                # Show detailed full context breakdown with management actions
                from .context_overlay_toolkit_detail import show_detailed_context_breakdown
                show_detailed_context_breakdown(agent, console)
                return

            # Get ACTUAL stats from model interceptor
            stats = get_interceptor_stats(agent)
            mgr = ContextManager(agent)
            max_tokens = 128000

            console.print()

            if not stats or stats.call_count == 0:
                # Pre-call estimate - simple panel
                from .token_estimator import TokenEstimator
                estimator = TokenEstimator()
                system_tokens = estimator.count_tokens(agent.system_message)
                tool_tokens = sum(estimator.estimate_tool_from_toolkit(tool) for tool in agent.agent_tools)
                est_total = system_tokens + tool_tokens + 1000

                panel = Panel(
                    f"[yellow]⚠️  No LLM calls yet[/yellow]\n\n"
                    f"[dim]Estimated starting context:[/dim] [cyan]~{est_total:,}[/cyan] tokens\n"
                    f"[dim]Make a request to see actual usage[/dim]",
                    title="[bold cyan]📊 Context Window[/bold cyan]",
                    border_style="cyan"
                )
                console.print(panel)
                console.print()
                return

            # Get breakdown from main model's last call
            breakdown = stats.last_breakdown
            if not breakdown:
                console.print(Panel("No breakdown available", title="📊 Context Window", border_style="cyan"))
                console.print()
                return

            # Use tokens from the LAST call (not cumulative)
            total_tokens = breakdown['total_tokens']

            # Calculate usage percentage
            usage_pct = (total_tokens / max_tokens) * 100

            # Create progress bar visualization
            def make_bar(value, total, width=40):
                filled = int((value / total) * width) if total > 0 else 0
                return "█" * filled + "░" * (width - filled)

            # Build content
            lines = []

            # Header with total
            lines.append(f"[bold]📊 Context Window: {total_tokens:,} / {max_tokens:,} tokens[/bold]")
            bar = make_bar(total_tokens, max_tokens, 50)
            status_color = "green" if usage_pct < 50 else "yellow" if usage_pct < 70 else "red"
            lines.append(f"[{status_color}]{bar}[/{status_color}] [bold]{usage_pct:.1f}%[/bold]")
            lines.append("")

            # Component breakdown with mini bars
            components = [
                ("System", breakdown['system_tokens'], "cyan"),
                ("History", breakdown['assistant_tokens'], "blue"),
                ("Tools", breakdown['tool_tokens'], "magenta"),
                ("User", breakdown['user_tokens'], "yellow"),
            ]

            for label, tokens, color in components:
                if tokens > 0:
                    pct = (tokens / total_tokens) * 100
                    bar = make_bar(tokens, total_tokens, 30)
                    lines.append(f"{label:8} [{color}]{bar}[/{color}] {tokens:>6,} ([yellow]{pct:4.1f}%[/yellow])")

            lines.append("")
            lines.append("[dim]💡 Tip: Press ## (double-press) for full breakdown with management actions[/dim]")

            # Tool summary
            tool_functions = mgr.count_tool_functions()
            lines.append(f"[bold]🔧 Tools:[/bold] {len(agent.agent_tools)} toolkits, {breakdown['tool_count']} functions sent")

            panel = Panel(
                "\n".join(lines),
                title="[bold cyan]📊 Context Dashboard[/bold cyan]",
                border_style="cyan"
            )

            console.print(panel)
            console.print()
            return

        except Exception as e:
            logger.error(f"Context overlay failed: {e}", exc_info=True)
            console.print(f"\n[red]Context overlay error: {e}[/red]")

    @bindings.add('~')  # '~' - Context management (delete/summarize)
    def _(event):
        """Manage context components - delete or summarize to free tokens."""
        try:
            from .context_manager_ui import show_context_manager
            import asyncio

            console.print()

            # Schedule the async function as a task in the running event loop
            asyncio.create_task(show_context_manager(agent, console))

        except Exception as e:
            logger.error(f"Context manager failed: {e}", exc_info=True)
            console.print(f"\n[red]Context manager error: {e}[/red]\n")

    # Voice server URL (CLI feature, not agent tool)
    voice_server_url = [None]  # Mutable for inner function access

    # Voice recording state (shared between Ctrl+I and Space handlers)
    voice_recording_state = {
        "session_id": None,
        "is_recording": False,
        "voice_url": None
    }

    @bindings.add('escape', 'v')  # Alt+V
    def _(event):
        """Voice input via achat server (streaming with VAD)."""
        import requests
        import time

        # Check if voice server is configured
        voice_url = voice_server_url[0]

        if not voice_url:
            # Show helpful setup message
            console.print("\n[yellow]🎤 Voice input not available[/yellow]")
            console.print("   [dim]To enable voice input:[/dim]")
            console.print("   1. On your local machine: [cyan]achat[/cyan]")
            console.print("   2. Copy connection command from output")
            console.print("   3. Paste here: [cyan]add_voice http://localhost:8765[/cyan]")
            console.print("   4. Press [cyan]Alt+V[/cyan] to record voice!\n")
            return

        # Show recording indicator
        console.print("🔴 [red]Recording...[/red] (press [cyan]Space[/cyan] to stop, auto-stops on silence)")

        try:
            # Start streaming session
            response = requests.post(
                f"{voice_url}/tools/voice_stream_start",
                timeout=5
            )
            result = response.json()

            if result.get("status") != "recording":
                error = result.get("error", "Unknown error")
                console.print(f"[red]❌ Failed to start recording: {error}[/red]")
                return

            session_id = result.get("session_id")
            if not session_id:
                console.print("[red]❌ No session ID returned[/red]")
                return

            # Store session state for Space key handler
            voice_recording_state["session_id"] = session_id
            voice_recording_state["is_recording"] = True
            voice_recording_state["voice_url"] = voice_url

            # Poll for transcript chunks
            start_time = time.time()
            max_duration = 30  # Safety timeout
            poll_interval = 0.5  # Poll every 500ms

            while voice_recording_state["is_recording"] and (time.time() - start_time) < max_duration:
                # Check for new chunks
                try:
                    chunk_response = requests.get(
                        f"{voice_url}/tools/voice_stream_chunk/{session_id}",
                        timeout=2
                    )
                    chunk_result = chunk_response.json()

                    if chunk_result.get("status") == "success":
                        chunks = chunk_result.get("chunks", [])

                        # Insert new chunks into buffer
                        for chunk_text in chunks:
                            if chunk_text.strip():
                                # Insert with space separator
                                if event.current_buffer.text and not event.current_buffer.text.endswith(" "):
                                    event.current_buffer.insert_text(" ")
                                event.current_buffer.insert_text(chunk_text.strip())
                                console.print(f"  → [cyan]{chunk_text.strip()}[/cyan]")

                        # Check if recording is complete
                        if chunk_result.get("is_complete"):
                            console.print("✅ [green]Recording complete[/green]")
                            voice_recording_state["is_recording"] = False
                            break

                except requests.exceptions.Timeout:
                    # Timeout on chunk poll is OK, just continue
                    pass
                except Exception as e:
                    logger.error(f"Chunk poll error: {e}")

                # Sleep before next poll
                time.sleep(poll_interval)

            # Clean up
            voice_recording_state["session_id"] = None
            voice_recording_state["is_recording"] = False

            if time.time() - start_time >= max_duration:
                console.print("[yellow]⚠️  Recording timed out (safety limit)[/yellow]")

        except requests.exceptions.ConnectionError:
            console.print(f"[red]❌ Cannot connect to voice server at {voice_url}[/red]")
            console.print("   [dim]Is achat running on your local machine?[/dim]")
        except requests.exceptions.Timeout:
            console.print("[red]❌ Voice request timed out[/red]")
        except Exception as e:
            console.print(f"[red]❌ Voice error: {e}[/red]")
            logger.error(f"Voice input error: {e}")
        finally:
            # Ensure state is cleaned up
            voice_recording_state["session_id"] = None
            voice_recording_state["is_recording"] = False

    @bindings.add(' ', filter=Condition(lambda: voice_recording_state["is_recording"]))
    def _(event):
        """Stop voice recording when Space is pressed during recording."""
        import requests

        if not voice_recording_state["is_recording"]:
            return

        session_id = voice_recording_state.get("session_id")
        voice_url = voice_recording_state.get("voice_url")

        if not session_id or not voice_url:
            return

        console.print("⏹️  [yellow]Stopping recording...[/yellow]")

        try:
            # Stop the recording session
            response = requests.post(
                f"{voice_url}/tools/voice_stream_stop/{session_id}",
                timeout=5
            )
            result = response.json()

            if result.get("status") == "stopped":
                # Get any final chunks
                final_chunks = result.get("chunks", [])
                for chunk_text in final_chunks:
                    if chunk_text.strip():
                        if event.current_buffer.text and not event.current_buffer.text.endswith(" "):
                            event.current_buffer.insert_text(" ")
                        event.current_buffer.insert_text(chunk_text.strip())
                        console.print(f"  → [cyan]{chunk_text.strip()}[/cyan]")

                console.print("✅ [green]Recording stopped[/green]")

            # Signal Ctrl+I loop to stop
            voice_recording_state["is_recording"] = False

        except Exception as e:
            console.print(f"[red]❌ Failed to stop recording: {e}[/red]")
            logger.error(f"Stop recording error: {e}")
            # Force stop anyway
            voice_recording_state["is_recording"] = False

    @bindings.add(Keys.Enter)
    def _(event):
        """Handle Enter: accept completion first, then submit on second press."""
        # Check if completion menu is showing
        if event.current_buffer.complete_state:
            # Completion menu is active - accept the currently selected completion
            completion_state = event.current_buffer.complete_state
            if completion_state.current_completion:
                # Apply the selected completion
                event.current_buffer.apply_completion(completion_state.current_completion)
            # Clear the completion state to close the menu
            event.current_buffer.complete_state = None
        else:
            # No completion menu - submit the input
            event.current_buffer.validate_and_handle()

    # Create PromptSession for async usage - will switch history and completer dynamically
    prompt_session = PromptSession(
        history=agent_history,
        multiline=False,
        complete_style='multi-column',  # Multi-column for better space usage
        key_bindings=bindings,
        completer=None,  # Will be set dynamically
        complete_in_thread=True,  # Better performance for large completions
        enable_system_prompt=True,
        reserve_space_for_menu=8,  # Reserve space for completion menu (8 rows)
    )

    async def get_user_input_with_history(queue):
        """Get user input with file-based history and arrow key support.

        Use a callable for the prompt message so that prompt_toolkit will re-evaluate
        it on invalidate/redraw. The callable also updates the session's history
        and completer as a side-effect so the displayed prompt and behaviors
        switch immediately when toggling modes (e.g. via the '#' key).
        """
        def _get_prompt_message():
            # Update history and completer as a side-effect so they change immediately
            # when the prompt is re-rendered.
            try:
                if shell_manager.is_shell_mode:
                    prompt_session.history = shell_history
                    prompt_session.completer = shell_completer
                    return HTML('<yellow>shell$</yellow> ')
                else:
                    prompt_session.history = agent_history
                    prompt_session.completer = nudge_completer
                    return HTML('<cyan>agent!</cyan> ')
            except Exception:
                # Fallback to a simple prompt if something goes wrong
                return HTML('<cyan>agent!</cyan> ')

        while True:
            try:
                # Pass a callable so prompt_async will call it on redraws (invalidate())
                user_input = await prompt_session.prompt_async(_get_prompt_message)
                await queue.put(user_input)
            except (EOFError, KeyboardInterrupt):
                return None
            await asyncio.sleep(0.01)
        
    input_queue = asyncio.Queue()
    status_queue = asyncio.Queue()
    output_queue = asyncio.Queue()

    user_id = os.getenv('USER', None)
    if user_id is None:
        user_id = os.getenv('USERNAME', None)
    if user_id is None:
        user_id = "user"  # Generic fallback instead of hardcoded personal name
    
    
    # Create filesystem watcher callback
    async def on_file_change(event):
        """Handle file change events from watchdog."""
        try:
            if not code_session.filesystem_history:
                return

            path = Path(event.src_path)
            relative_path = str(path.relative_to(code_session.working_directory))

            # Check if this is the first change for this file
            existing_changes = code_session.filesystem_history.get_file_history(relative_path)
            is_first_change = len(existing_changes) == 0

            # Capture pre-change snapshot for first modification/deletion
            pre_change_snapshot = None
            if is_first_change and event.event_type in ['modified', 'deleted']:
                # Note: Event fires AFTER change, so we can't capture pre-state here
                # Pre-snapshots must be captured in FileTool before writing
                pass

            # Get file size and content snapshot for non-deleted files
            size = None
            content_snapshot = None

            if event.event_type != 'deleted' and path.exists() and path.is_file():
                try:
                    size = path.stat().st_size

                    # Store content snapshot for small files
                    if size <= code_session.filesystem_history.max_snapshot_size:
                        try:
                            content_snapshot = path.read_text(encoding='utf-8', errors='replace')
                        except Exception:
                            pass
                except Exception:
                    pass

            # Determine source: agent if agent is running, otherwise external
            source = "agent" if running_agent is not None and not running_agent.done() else "external"

            # Create change record
            change = FileChange(
                event_type=event.event_type,
                path=str(path),
                relative_path=relative_path,
                size=size,
                content_snapshot=content_snapshot,
                src_path=getattr(event, 'dest_path', None) if event.event_type == 'moved' else None,
                source=source,
                pre_change_snapshot=pre_change_snapshot
            )

            # Add to session history
            code_session.filesystem_history.changes.append(change)

            # Invalidate file cache when files are created or deleted
            if event.event_type in ['created', 'deleted']:
                nudge_completer.invalidate_file_cache()

            # Persist to MongoDB/disk
            await da_mongo.save_file_change(str(code_session.id), change)

        except Exception as e:
            logger.error(f"Error processing file change: {e}")

    # Async wrapper for filesystem watcher
    async def run_filesystem_watcher():
        """Run filesystem watcher in task group."""
        fs_watcher = FileSystemWatcher(
            root_dir=code_session.working_directory,
            on_change_callback=on_file_change
        )
        try:
            fs_watcher.start(asyncio.get_event_loop())
            logger.info("Filesystem watcher started")
            # Keep running indefinitely
            while True:
                await asyncio.sleep(1)
        finally:
            fs_watcher.stop()
            logger.info("Filesystem watcher stopped")

    async with asyncio.TaskGroup() as tg:
        wait_for_input = tg.create_task(get_user_input_with_history(input_queue))
        fs_watcher_task = tg.create_task(run_filesystem_watcher())

        running_agent = None
        status_message = None
        output_message = None
        while True:
            try:
                # Check for cancellation request
                if cancel_agent[0] and running_agent is not None and not running_agent.done():
                    # Cancel the agent run first (tells the agent to stop)
                    if agent.active_run_id:
                        logger.debug(f"Cancelling agent run: {agent.active_run_id}")
                        agent.agent.cancel_run(agent.active_run_id)

                    # Then cancel the asyncio task
                    running_agent.cancel()
                    try:
                        await running_agent
                    except asyncio.CancelledError:
                        pass

                    running_agent = None
                    status_interface.stop_execution(False, "Cancelled")

                    # Print any partial output that was generated before cancellation
                    if output_message:
                        console.print("\n[dim]Partial output:[/dim]")
                        console.print(output_message)

                    cancel_agent[0] = False
                    output_message = None
                    status_message = None
                    continue

                # If agent is not running then wait for input command
                if running_agent is None:
                    if wait_for_input.done():
                        console.print(f"[red]ERROR: Input task exited unexpectedly: {wait_for_input.result()}[/red]")
                        break  # Exit main loop - input is no longer available
                    user_input = await input_queue.get()
                elif running_agent.done():
                    try:
                        final_response = running_agent.result()
                        status_message = None
                        running_agent = None

                        # Clear status silently
                        status_interface.stop_execution(True, silent=True)

                        # Print agent output
                        console.print()
                        console.print(output_message)
                        output_message = None

                        # Fetch final metrics and print enhanced summary
                        try:
                            session_id = str(code_session.id)
                            metrics = agent.agent.get_session_metrics(session_id=session_id)

                            if metrics:
                                # Extract metrics
                                input_tokens = getattr(metrics, 'input_tokens', 0) or 0
                                output_tokens = getattr(metrics, 'output_tokens', 0) or 0
                                total_tokens = getattr(metrics, 'total_tokens', 0) or (input_tokens + output_tokens)
                                reasoning_tokens = getattr(metrics, 'reasoning_tokens', 0) or 0
                                cache_read = getattr(metrics, 'cache_read_tokens', 0) or 0
                                duration = getattr(metrics, 'duration', None)

                                # Build summary parts
                                summary_parts = []

                                # Timing
                                if duration:
                                    summary_parts.append(f"⏱️  {duration:.1f}s")
                                elif hasattr(status_interface, 'start_time') and status_interface.start_time:
                                    elapsed = time.time() - status_interface.start_time
                                    summary_parts.append(f"⏱️  {elapsed:.1f}s")

                                # Token breakdown
                                if total_tokens > 0:
                                    token_str = f"🎫 {total_tokens:,} tokens"
                                    if input_tokens and output_tokens:
                                        token_str += f" ({input_tokens:,} in / {output_tokens:,} out)"
                                    summary_parts.append(token_str)

                                # Reasoning tokens (if using o1/o3)
                                if reasoning_tokens > 0:
                                    summary_parts.append(f"🧠 {reasoning_tokens:,} reasoning")

                                # Cache hits
                                if cache_read > 0:
                                    summary_parts.append(f"💾 {cache_read:,} cached")

                                # Tool calls
                                if hasattr(status_interface, 'tool_calls') and status_interface.tool_calls > 0:
                                    summary_parts.append(f"🔧 {status_interface.tool_calls} tools")

                                # Context usage percentage
                                if total_tokens > 0:
                                    context_usage_pct = (total_tokens / 128000) * 100
                                    summary_parts.append(f"📊 {context_usage_pct:.0f}% context")

                                # Print summary
                                if summary_parts:
                                    console.print(f"\n[dim]{' | '.join(summary_parts)}[/dim]")
                        except Exception as e:
                            logger.debug(f"Could not fetch session metrics: {e}")

                    except Exception as e:
                        # Handle agent execution errors
                        running_agent = None
                        status_interface.stop_execution(False, str(e))
                        console.print(f"[red]Agent error: {str(e)}[/red]")
                        logger.error(f"Agent execution error: {type(e).__name__}: {str(e)}", exc_info=True)
                else:
                    # Accumulate output while agent is running
                    while output_queue.qsize() > 0:
                        chunk = await output_queue.get()
                        output_message += chunk

                    while status_queue.qsize() > 0:
                        status_update = await status_queue.get()

                        # Check if it's a metrics update (dict) or status message (str)
                        if isinstance(status_update, dict):
                            # Metrics update from agent
                            if 'type' in status_update:
                                if status_update['type'] == 'llm_call':
                                    status_interface.log_llm_call(
                                        tokens_used=status_update.get('tokens', 0),
                                        input_tokens=status_update.get('input_tokens', 0),
                                        output_tokens=status_update.get('output_tokens', 0)
                                    )
                                elif status_update['type'] == 'tool_call':
                                    status_interface.log_tool_call(status_update.get('tool_name', ''))
                        else:
                            # Regular status message - update with actual telemetry if available
                            status_message = status_update

                            # Try to get real-time context stats from model interceptor
                            try:
                                from .context_telemetry import get_interceptor_stats
                                stats = get_interceptor_stats(agent)

                                if stats and stats.call_count > 0:
                                    # We have actual data - show context % from last call
                                    max_tokens = 128000
                                    context_pct = (stats.max_context_seen / max_tokens) * 100
                                    status_interface.update_status(f"{status_message} | 📊 {context_pct:.0f}% context")
                                else:
                                    # No LLM calls yet, just show the status
                                    status_interface.update_status(status_message)
                            except Exception:
                                # Fallback: just show the status message
                                status_interface.update_status(status_message)

                    await asyncio.sleep(0.01)
                    continue

                if user_input is None:
                    continue

                if user_input.lower() in ['exit', 'quit', 'q']:
                    # Save session before exit
                    try:
                        await da_mongo.save_session(code_session)
                        logger.info(f"Session {code_session.id} saved on exit")
                    except Exception as e:
                        logger.warning(f"Failed to save session on exit: {e}")

                    console.print("\n[bold green]👋 Goodbye![/bold green]")
                    console.print(f"\n[dim]To restart this session, run:[/dim]")
                    console.print(f"[cyan]  da_code --session {str(code_session.id)}[/cyan]")
                    console.print()
                    break

                elif user_input.lower() == 'help':
                    console.print("[bold]Available commands:[/bold]")
                    console.print("  • [cyan]help[/cyan] - Show this help message")
                    console.print("  • [cyan]help glob[/cyan] - Show glob command how-to")
                    console.print("  • [cyan]help grep[/cyan] - Show grep command how-to")
                    console.print("  • [cyan]setup[/cyan] - Create configuration files")
                    console.print("  • [cyan]status[/cyan] - Show current configuration status")
                    console.print("  • [cyan]glob <pattern>[/cyan] - Find files matching pattern (results sent to next prompt)")
                    console.print("  • [cyan]grep <pattern>[/cyan] - Search file contents (results sent to next prompt)")
                    console.print("  • [cyan]restore[/cyan] - Revert ALL file changes since session start")
                    console.print("  • [cyan]exit/quit/q[/cyan] - Exit the application")
                    console.print("\n[bold]Agent Control:[/bold]")
                    console.print("  • [cyan]Escape[/cyan] - Cancel running agent execution 🛑")
                    console.print("\n[bold]Voice Input:[/bold]")
                    console.print("  • [cyan]Alt+V[/cyan] - Start streaming voice recording with live transcript 🎤")
                    console.print("  • [cyan]Space[/cyan] - Stop recording (or auto-stops on silence)")
                    console.print("\n[bold]Agent Mode - Left-hand Ergonomic Triggers:[/bold]")
                    console.print("  • [cyan]![/cyan] - AI nudge phrases: '!be<Tab>' → 'be careful and check your work' 💡")
                    console.print("  • [cyan]@[/cyan] - File paths: '@src/<Tab>' → navigate directories 📁")
                    console.print("  • [cyan]#[/cyan] - Context window breakdown (Shift+3) - Shows actual LLM token usage 📊")
                    console.print("  • [cyan]$[/cyan] - Toggle shell mode (Shift+4)")
                    console.print("  • [cyan]~[/cyan] - Context manager - Delete or summarize components to free tokens 🗑️")
                    console.print("\n[bold]Clipboard:[/bold]")
                    console.print("  • [cyan]Ctrl+V or terminal paste[/cyan] - Paste shows '[[paste#N: X lines]]' placeholder, actual content sent to agent")
                    console.print("\n[bold]Tip:[/bold] Use [cyan]glob[/cyan] and [cyan]grep[/cyan] to prepare context, then ask agent about results!")
 
                elif user_input.lower() == 'setup':
                    create_example_configuration(config_mgr=ConfigManager(), context_ldr=ContextLoader())
                    console.print("[green]Edit files and reload to update agent context[/green]")

                elif user_input.lower() == 'status':
                    show_status(config_mgr=ConfigManager(), context_ldr=ContextLoader())

                elif user_input.lower() == 'shell':
                    shell_manager.toggle_shell_mode()
                    continue

                elif user_input.lower().startswith('restore'):
                    # Check if it's a file-specific restore or full session restore
                    if len(user_input.strip()) > len('restore') and user_input[7:].strip():
                        # File-specific restore: "restore file.py"
                        file_path = user_input[7:].strip()  # Everything after "restore "

                        # Get file revisions
                        revisions = nudge_completer._get_file_revisions(file_path)

                        # Show interactive revision selector
                        from rich.table import Table
                        from rich.panel import Panel

                        table = Table(show_header=True, header_style="bold cyan")
                        table.add_column("#", style="cyan", width=6)
                        table.add_column("Lines Changed", style="yellow", width=15)
                        table.add_column("Time Ago", style="green", width=12)
                        table.add_column("Description", style="white")

                        # Add session start option
                        snapshot_entry = None
                        if code_session.filesystem_history and code_session.filesystem_history.session_start_snapshot:
                            snapshot_entry = code_session.filesystem_history.session_start_snapshot.get(file_path)

                        if snapshot_entry:
                            table.add_row("0", "-", "-", "Session start (original version)")
                        elif revisions:
                            # File was created during session
                            table.add_row("0", "-", "-", "Session start (will DELETE file)")
                        else:
                            console.print(f"[red]No history found for {file_path}[/red]")
                            continue

                        # Add all revisions
                        for rev_num, lines_changed, time_str, _ in revisions:
                            table.add_row(
                                str(rev_num),
                                f"{lines_changed} lines",
                                f"{time_str} ago",
                                f"Revision #{rev_num}"
                            )

                        # Show the panel
                        panel = Panel(
                            table,
                            title=f"[bold white]Select Revision for {file_path}[/bold white]",
                            subtitle="[dim]Type revision number (0 for session start) or 'cancel'[/dim]",
                            border_style="blue"
                        )
                        console.print()
                        console.print(panel)
                        console.print()

                        # Get user selection (with escape support and hotkeys)
                        console.print("[cyan]→[/cyan] [white]Enter revision # (0! for quick restore to session start):[/white] ", end="")
                        try:
                            revision_input = await input_queue.get()
                        except (KeyboardInterrupt, EOFError):
                            console.print("\n[cyan]↩ Restore cancelled[/cyan]")
                            continue

                        if revision_input.lower() in ['cancel', 'c', 'q', 'quit', '']:
                            console.print("[cyan]↩ Restore cancelled[/cyan]")
                            continue

                        # Parse revision selection - check for auto-confirm hotkey (e.g., "0!", "1!")
                        auto_confirm = revision_input.strip().endswith('!')
                        revision_str = revision_input.strip().rstrip('!')

                        try:
                            revision_num = int(revision_str)
                        except ValueError:
                            console.print(f"[red]Invalid input: {revision_input}[/red]")
                            continue

                        # Validate revision number
                        if revision_num < 0 or revision_num > len(revisions):
                            console.print(f"[red]Invalid revision #{revision_num}. Valid range: 0-{len(revisions)}[/red]")
                            continue

                        # Helper function to calculate diff stats
                        def calculate_diff_stats(current_content: str, target_content: str) -> dict:
                            """Calculate diff statistics between current and target content."""
                            if current_content is None:
                                current_lines = []
                            else:
                                current_lines = current_content.split('\n')

                            if target_content is None:
                                target_lines = []
                            else:
                                target_lines = target_content.split('\n')

                            # Simple line-based diff
                            added = len(target_lines) - len(current_lines)
                            return {
                                'current_lines': len(current_lines),
                                'target_lines': len(target_lines),
                                'delta': added,
                                'delta_str': f"+{added}" if added > 0 else str(added)
                            }

                        # Get current file content for diff comparison
                        current_content = None
                        try:
                            full_path = Path(code_session.working_directory) / file_path
                            if full_path.exists():
                                with open(full_path, 'r', encoding='utf-8', newline='') as f:
                                    current_content = f.read()
                        except Exception:
                            pass

                        # Determine which content to restore
                        if revision_num == 0:
                            # Session start
                            if snapshot_entry:
                                # File existed at session start
                                if snapshot_entry.is_binary:
                                    console.print(f"[red]Cannot restore binary file {file_path}[/red]")
                                    continue
                                content_to_restore = snapshot_entry.content
                                restore_description = "session start"

                                # Show diff synopsis
                                diff_stats = calculate_diff_stats(current_content, content_to_restore)
                                console.print(f"\n[cyan]📊 Change Synopsis:[/cyan]")
                                console.print(f"  Current: [yellow]{diff_stats['current_lines']} lines[/yellow]")
                                console.print(f"  Target:  [green]{diff_stats['target_lines']} lines[/green]")
                                console.print(f"  Delta:   [magenta]{diff_stats['delta_str']} lines[/magenta]\n")
                            else:
                                # File was created during session - delete it
                                console.print(f"\n[yellow]⚠️  This will DELETE {file_path}[/yellow]")
                                console.print(f"[dim]File was created during this session[/dim]\n")

                                if not auto_confirm:
                                    console.print("[yellow]Confirm deletion? [y/N]:[/yellow] ", end="")
                                    confirm_input = await input_queue.get()
                                    if confirm_input.lower() not in ['y', 'yes']:
                                        console.print("[cyan]↩ Restore cancelled[/cyan]")
                                        continue

                                try:
                                    full_path = Path(code_session.working_directory) / file_path
                                    if full_path.exists():
                                        full_path.unlink()
                                        console.print(f"[green]✓ Deleted {file_path} (restored to session start)[/green]")
                                    else:
                                        console.print(f"[yellow]File {file_path} already doesn't exist[/yellow]")
                                except Exception as e:
                                    console.print(f"[red]❌ Failed to delete {file_path}: {str(e)}[/red]")
                                    logger.error(f"File delete error: {e}", exc_info=True)
                                continue
                        elif revision_num > 0:
                            # Restore to specific revision
                            if revision_num < 1 or revision_num > len(revisions):
                                console.print(f"[red]Invalid revision #{revision_num}. Valid range: 1-{len(revisions)}[/red]")
                                continue

                            # Get the change at this revision (revisions are 1-indexed)
                            target_change = None
                            change_idx = 0
                            for change in code_session.filesystem_history.changes:
                                if change.relative_path == file_path:
                                    change_idx += 1
                                    if change_idx == revision_num:
                                        target_change = change
                                        break

                            if not target_change or not target_change.content_snapshot:
                                console.print(f"[red]No content snapshot for revision #{revision_num}[/red]")
                                continue

                            content_to_restore = target_change.content_snapshot
                            restore_description = f"revision #{revision_num}"

                            # Show diff synopsis for specific revision
                            diff_stats = calculate_diff_stats(current_content, content_to_restore)
                            console.print(f"\n[cyan]📊 Change Synopsis:[/cyan]")
                            console.print(f"  Current: [yellow]{diff_stats['current_lines']} lines[/yellow]")
                            console.print(f"  Target:  [green]{diff_stats['target_lines']} lines[/green]")
                            console.print(f"  Delta:   [magenta]{diff_stats['delta_str']} lines[/magenta]\n")
                        else:
                            # No revision specified - restore to session start
                            if not code_session.filesystem_history or not code_session.filesystem_history.session_start_snapshot:
                                console.print(f"[red]No session start snapshot available[/red]")
                                continue

                            snapshot_entry = code_session.filesystem_history.session_start_snapshot.get(file_path)
                            if not snapshot_entry:
                                # File not in session start snapshot - was it created during the session?
                                # Check if this file has any history (meaning it was created this session)
                                if revisions:
                                    # File was created during session - deleting it restores to session start
                                    console.print(f"[yellow]⚠️  {file_path} was created during this session[/yellow]")
                                    console.print(f"[yellow]Restoring to session start will DELETE this file[/yellow]")
                                    console.print("[yellow]Are you sure? Type 'yes' to confirm:[/yellow]")

                                    confirm_input = await input_queue.get()
                                    if confirm_input.lower() != 'yes':
                                        console.print("[cyan]Restore cancelled[/cyan]")
                                        continue

                                    # Delete the file
                                    try:
                                        full_path = Path(code_session.working_directory) / file_path
                                        if full_path.exists():
                                            full_path.unlink()
                                            console.print(f"[green]✓ Deleted {file_path} (restored to session start)[/green]")
                                        else:
                                            console.print(f"[yellow]File {file_path} already doesn't exist[/yellow]")
                                    except Exception as e:
                                        console.print(f"[red]❌ Failed to delete {file_path}: {str(e)}[/red]")
                                        logger.error(f"File delete error: {e}", exc_info=True)
                                    continue
                                else:
                                    # File has no history and wasn't in session start - shouldn't happen
                                    console.print(f"[red]File {file_path} not found in session history[/red]")
                                    continue

                            if snapshot_entry.is_binary:
                                console.print(f"[red]Cannot restore binary file {file_path}[/red]")
                                continue

                            content_to_restore = snapshot_entry.content
                            restore_description = "session start"

                        # Confirm restore (skip if auto_confirm hotkey was used)
                        if not auto_confirm:
                            console.print("[yellow]Confirm restore? [y/N]:[/yellow] ", end="")
                            confirm_input = await input_queue.get()
                            if confirm_input.lower() not in ['y', 'yes']:
                                console.print("[cyan]↩ Restore cancelled[/cyan]")
                                continue

                        # Perform restore
                        try:
                            full_path = Path(code_session.working_directory) / file_path
                            # Use open() with newline='' to preserve exact line endings without translation
                            with open(full_path, 'w', encoding='utf-8', newline='') as f:
                                f.write(content_to_restore)
                            console.print(f"[green]✓ Restored {file_path} to {restore_description}[/green]")
                        except Exception as e:
                            console.print(f"[red]❌ Restore failed: {str(e)}[/red]")
                            logger.error(f"File restore error: {e}", exc_info=True)

                        continue
                    else:
                        # Full session restore: "restore"
                        console.print("[yellow]⚠️  This will revert ALL file changes since session start![/yellow]")
                        console.print("[yellow]Are you sure? Type 'yes' to confirm:[/yellow]")

                        # Wait for confirmation
                        confirm_input = await input_queue.get()
                        if confirm_input.lower() != 'yes':
                            console.print("[cyan]Restore cancelled[/cyan]")
                            continue

                        console.print("[cyan]Reverting all changes...[/cyan]")
                        try:
                            if code_session.filesystem_history:
                                result = code_session.filesystem_history.revert_all_changes()

                                if result["status"] == "error":
                                    console.print(f"[red]❌ Restore failed: {result.get('message', 'Unknown error')}[/red]")
                                elif result["status"] == "completed":
                                    stats = result["stats"]
                                    if stats['files_affected'] == 0:
                                        console.print("[green]✓ No changes to revert[/green]")
                                    else:
                                        console.print(f"[green]✓ Restore complete![/green]")
                                        console.print(f"  • Files deleted: {stats['deleted']}")
                                        console.print(f"  • Files restored: {stats['restored']}")
                                        console.print(f"  • Total files affected: {stats['files_affected']}")

                                        if stats['errors']:
                                            console.print(f"\n[yellow]⚠️  Errors ({len(stats['errors'])}):[/yellow]")
                                            for error in stats['errors'][:5]:  # Show first 5 errors
                                                console.print(f"  • {error}")
                                            if len(stats['errors']) > 5:
                                                console.print(f"  ... and {len(stats['errors']) - 5} more")
                            else:
                                console.print("[yellow]No filesystem history available[/yellow]")
                        except Exception as e:
                            console.print(f"[red]❌ Restore failed: {str(e)}[/red]")
                            logger.error(f"Restore error: {e}", exc_info=True)
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
                
                elif user_input.startswith('add_voice '):
                    # Handle voice server configuration (CLI feature, not agent tool)
                    try:
                        voice_url = user_input[10:].strip()

                        if not voice_url:
                            console.print("[red]Usage: add_voice <url>[/red]")
                            console.print("[dim]Example: add_voice http://localhost:8765[/dim]")
                            continue

                        # Validate URL format
                        if not voice_url.startswith('http://') and not voice_url.startswith('https://'):
                            console.print("[red]URL must start with http:// or https://[/red]")
                            continue

                        # Test connection
                        console.print(f"[yellow]Testing connection to voice server: {voice_url}[/yellow]")
                        import requests
                        try:
                            response = requests.get(f"{voice_url.rstrip('/')}/", timeout=3)
                            if response.status_code == 200:
                                data = response.json()
                                if data.get('service') == 'achat':
                                    voice_server_url[0] = voice_url.rstrip('/')
                                    console.print(f"[green]✅ Voice server connected: {data.get('service')} v{data.get('version')}[/green]")
                                    console.print(f"[green]   Available tools: {', '.join(data.get('tools', []))}[/green]")
                                    console.print(f"[cyan]   Press Alt+V to start voice recording![/cyan]")
                                else:
                                    console.print(f"[yellow]⚠️  Server responded but is not an achat server[/yellow]")
                                    console.print(f"[yellow]   Received: {data}[/yellow]")
                            else:
                                console.print(f"[red]❌ Server returned HTTP {response.status_code}[/red]")
                        except requests.exceptions.ConnectionError:
                            console.print(f"[red]❌ Cannot connect to {voice_url}[/red]")
                            console.print("[dim]   Make sure achat is running on your local machine[/dim]")
                        except requests.exceptions.Timeout:
                            console.print(f"[red]❌ Connection timed out[/red]")
                        except Exception as e:
                            console.print(f"[red]❌ Connection test failed: {str(e)}[/red]")

                    except Exception as e:
                        console.print(f"[red]❌ Error configuring voice server: {str(e)}[/red]")
                        logger.error(f"Voice configuration error: {e}")
                    continue



                elif user_input.lower().startswith('help glob'):
                    console.print("\n[bold cyan]📁 GLOB Command - Find Files by Pattern[/bold cyan]\n")
                    console.print("[bold]Usage:[/bold]")
                    console.print("  [cyan]glob <pattern>[/cyan]\n")
                    console.print("[bold]Examples:[/bold]")
                    console.print("  [cyan]glob *.py[/cyan]           - All Python files in current dir")
                    console.print("  [cyan]glob **/*.py[/cyan]        - All Python files recursively")
                    console.print("  [cyan]glob src/**/*.ts[/cyan]    - All TypeScript files in src/")
                    console.print("  [cyan]glob **/test_*.py[/cyan]   - All test files\n")
                    console.print("[bold]How it works:[/bold]")
                    console.print("  1. Runs the search immediately")
                    console.print("  2. Shows you the results")
                    console.print("  3. Results are automatically added to your NEXT agent prompt\n")
                    console.print("[bold]Workflow:[/bold]")
                    console.print("  [cyan]glob **/*.py[/cyan]")
                    console.print("  📁 Found 42 files...")
                    console.print("  [cyan]refactor all these files to use async[/cyan]  ← Results included!\n")

                elif user_input.lower().startswith('help grep'):
                    console.print("\n[bold cyan]🔍 GREP Command - Search File Contents[/bold cyan]\n")
                    console.print("[bold]Usage:[/bold]")
                    console.print("  [cyan]grep <pattern> [options][/cyan]\n")
                    console.print("[bold]Examples:[/bold]")
                    console.print("  [cyan]grep 'async def'[/cyan]           - Find async function definitions")
                    console.print("  [cyan]grep TODO[/cyan]                  - Find all TODO comments")
                    console.print("  [cyan]grep 'class.*Test'[/cyan]         - Find test classes (regex)\n")
                    console.print("[bold]How it works:[/bold]")
                    console.print("  1. Searches file contents for the pattern")
                    console.print("  2. Shows matching files with line numbers")
                    console.print("  3. Results automatically added to NEXT agent prompt\n")
                    console.print("[bold]Workflow:[/bold]")
                    console.print("  [cyan]grep 'async def'[/cyan]")
                    console.print("  🔍 Found 12 matches in 5 files...")
                    console.print("  [cyan]document all these async functions[/cyan]  ← Results included!\n")
                    console.print("[bold]Tip:[/bold] Results respect .daignore - ignored files are skipped")

                elif user_input.lower().startswith('glob '):
                    # Extract pattern
                    pattern = user_input[5:].strip()
                    if not pattern:
                        console.print("[red]Usage: glob <pattern>[/red]")
                        console.print("[dim]Example: glob **/*.py[/dim]")
                        continue

                    # Strip shell-style quotes (single or double) for consistency
                    try:
                        pattern = shlex.split(pattern)[0] if pattern else ""
                    except (ValueError, IndexError):
                        if pattern and len(pattern) >= 2 and pattern[0] in ('"', "'") and pattern[-1] == pattern[0]:
                            pattern = pattern[1:-1]

                    try:
                        # Use agent's FileTool
                        import json
                        file_tool = None
                        for toolkit in agent.agent_tools:
                            if hasattr(toolkit, 'name') and toolkit.name == 'file_tool':
                                file_tool = toolkit
                                break

                        if not file_tool:
                            console.print("[red]FileTool not available[/red]")
                            continue

                        # Call glob_files
                        result_json = file_tool.glob_files(pattern=pattern)
                        result = json.loads(result_json)

                        if 'error' in result:
                            console.print(f"[red]❌ {result['error']}[/red]")
                            continue

                        files = result.get('files', [])
                        matches = result.get('matches', 0)

                        if matches == 0:
                            console.print(f"[yellow]No files found matching '{pattern}'[/yellow]")
                            continue

                        # Show results
                        console.print(f"\n[bold cyan]📁 Found {matches} file{'s' if matches != 1 else ''} matching '{pattern}':[/bold cyan]")
                        for i, file_path in enumerate(files[:20], 1):
                            console.print(f"  {i}. {file_path}")

                        if matches > 20:
                            console.print(f"  [dim]... and {matches - 20} more[/dim]")

                        console.print(f"\n[green]✓ Results will be included in your next agent prompt[/green]")

                        # Store results in search_content_storage for next prompt
                        placeholder = f"[[glob:{pattern}]]"
                        search_content_storage[placeholder] = {
                            'term': pattern,
                            'files': {f: {'line_numbers': [], 'matches': []} for f in files}  # Glob doesn't have line matches
                        }
                        logger.warning(f"📦 STORED glob results: placeholder='{placeholder}', {len(files)} files")
                        logger.warning(f"📦 search_content_storage keys: {list(search_content_storage.keys())}")

                    except Exception as e:
                        console.print(f"[red]❌ Glob error: {str(e)}[/red]")
                        logger.error(f"Glob command error: {e}", exc_info=True)
                    continue

                elif user_input.lower().startswith('grep '):
                    # Extract pattern
                    pattern = user_input[5:].strip()
                    if not pattern:
                        console.print("[red]Usage: grep <pattern>[/red]")
                        console.print("[dim]Example: grep 'async def'[/dim]")
                        continue

                    # Strip shell-style quotes (single or double)
                    try:
                        # shlex.split handles quote stripping like a shell
                        pattern = shlex.split(pattern)[0] if pattern else ""
                    except (ValueError, IndexError):
                        # If shlex fails (unclosed quotes), just strip outer quotes manually
                        if pattern and len(pattern) >= 2 and pattern[0] in ('"', "'") and pattern[-1] == pattern[0]:
                            pattern = pattern[1:-1]

                    try:
                        # Use agent's FileTool
                        import json
                        file_tool = None
                        for toolkit in agent.agent_tools:
                            if hasattr(toolkit, 'name') and toolkit.name == 'file_tool':
                                file_tool = toolkit
                                break

                        if not file_tool:
                            console.print("[red]FileTool not available[/red]")
                            continue

                        # Call grep_content
                        result_json = file_tool.grep_content(pattern=pattern, context_lines=0, max_results=100)
                        result = json.loads(result_json)

                        if 'error' in result:
                            console.print(f"[red]❌ {result['error']}[/red]")
                            continue

                        results_list = result.get('results', [])
                        matches = result.get('matches', 0)
                        files_searched = result.get('files_searched', 0)

                        if matches == 0:
                            console.print(f"[yellow]No matches found for '{pattern}' (searched {files_searched} files)[/yellow]")
                            continue

                        # Group by file
                        files_dict = {}
                        for match in results_list:
                            file_path = match['file']
                            if file_path not in files_dict:
                                files_dict[file_path] = {'line_numbers': [], 'matches': []}
                            files_dict[file_path]['line_numbers'].append(match['line'])
                            files_dict[file_path]['matches'].append({
                                'line_num': match['line'],
                                'content': match['content']
                            })

                        # Show results
                        console.print(f"\n[bold cyan]🔍 Found {matches} match{'es' if matches != 1 else ''} for '{pattern}' in {len(files_dict)} file{'s' if len(files_dict) != 1 else ''}:[/bold cyan]")
                        for file_path, match_data in list(files_dict.items())[:10]:
                            line_nums = match_data['line_numbers']
                            if len(line_nums) <= 5:
                                line_str = ', '.join(map(str, line_nums))
                            else:
                                line_str = f"{line_nums[0]}-{line_nums[-1]} ({len(line_nums)} matches)"
                            console.print(f"  • {file_path}: lines {line_str}")

                            # Show first match as preview
                            if match_data['matches']:
                                first_match = match_data['matches'][0]
                                preview = first_match['content'][:80]
                                if len(first_match['content']) > 80:
                                    preview += "..."
                                console.print(f"    [dim]L{first_match['line_num']}: {preview}[/dim]")

                        if len(files_dict) > 10:
                            console.print(f"  [dim]... and {len(files_dict) - 10} more files[/dim]")

                        console.print(f"\n[green]✓ Results will be included in your next agent prompt[/green]")

                        # Store results for next prompt
                        placeholder = f"[[grep:{pattern}]]"
                        search_content_storage[placeholder] = {
                            'term': pattern,
                            'files': files_dict
                        }
                        logger.warning(f"📦 STORED grep results: placeholder='{placeholder}', {len(files_dict)} files, {matches} matches")
                        logger.warning(f"📦 search_content_storage keys: {list(search_content_storage.keys())}")

                    except Exception as e:
                        console.print(f"[red]❌ Grep error: {str(e)}[/red]")
                        logger.error(f"Grep command error: {e}", exc_info=True)
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
                        # Check for directory changes
                        dir_update = dir_context.check_changes(cache_timestamp)
                        if dir_update:
                            directory_cache, cache_timestamp = dir_context.get_directory_listing()
                            logger.info(f"Directory updated - sending new listing to agent context")

                        # Gather all context sources
                        shell_context = shell_manager.get_shell_context_for_agent()
                        file_changes = code_session.get_file_changes_summary()
                        logger.info(f"File changes summary: {file_changes}")

                        # Build enhanced input with all context
                        enhanced_input = build_agent_context(
                            user_input=user_input,
                            pasted_storage=pasted_content_storage,
                            search_storage=search_content_storage,
                            dir_update=dir_update,
                            file_changes=file_changes,
                            shell_context=shell_context
                        )

                        sanitized_input = enhanced_input.encode('utf-8', 'replace').decode('utf-8')

                        # Optional: Estimate input tokens and warn if context is high (using TokenEstimator)
                        # This is a pre-call estimate to warn user before making the LLM call
                        try:
                            from .token_estimator import TokenEstimator
                            estimator = TokenEstimator()
                            input_tokens_est = estimator.count_tokens(sanitized_input)
                            max_tokens = 128000
                            usage_pct = (input_tokens_est / max_tokens) * 100

                            # Warn if estimated usage > 80%
                            if usage_pct > 80:
                                console.print(f"[yellow]⚠️  Estimated context usage: {usage_pct:.1f}% ({input_tokens_est:,} / {max_tokens:,} tokens)[/yellow]")
                                console.print(f"[dim]   Remaining: {max_tokens - input_tokens_est:,} tokens[/dim]")
                        except Exception as e:
                            logger.debug(f"Token estimation failed: {e}")

                        # Use random thinking phrase
                        thinking_str = get_random_thinking_phrase()
                        status_interface.start_execution(f"{thinking_str}")
                        output_message = ""
                        logger.info(f"Input Context : {enhanced_input}")
                        running_agent = tg.create_task(
                            agent.arun(sanitized_input, confirm_wrapper, status_queue, output_queue, user_id)
                        )
                        user_input = None
                    except Exception as e:
                        status_interface.stop_execution(False, str(e))
                        console.print(f"[red]Sorry, I encountered an error: {str(e)}[/red]")
                        logger.error(f"Agent chat error: {type(e).__name__}: {str(e)}", exc_info=True)
                        # Clean up agent-related state variables
                        running_agent = None
                        status_message = None
                        output_message = None

            except KeyboardInterrupt:
                if status_interface.current_status:
                    status_interface.stop_execution(False, "Interrupted by user")
                console.print("[yellow]⚠️ Interrupted[/yellow]")
                continue
            except EOFError:
                break



def main():
    """Entry point with argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="da_code - AI Coding Assistant")
    parser.add_argument('command', nargs='?', choices=['setup', 'status'],
                       help='Command to run (setup creates config files and exits, test checks connection)')
    parser.add_argument('--session', type=str, help='Resume a previous session by session ID')
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
        asyncio.run(async_main(session_id=args.session))
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        if _current_session_id:
            print(f"\nTo restart this session, run:")
            print(f"  da_code --session {_current_session_id}")
        print()
    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Main execution error: {e}")

if __name__ == '__main__':
    main()
