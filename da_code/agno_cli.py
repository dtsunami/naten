
"""Main CLI entry point for da_code tool."""

import asyncio
import logging
import os
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
from .context import ContextLoader, DirectoryContext, NUDGE_PHRASES
from .models import CodeSession, CommandExecution, UserResponse, ConfirmationResponse
from .agno_agent import AgnoAgent
from .mcp_tool import mcp2tool
from .ux import (
    show_splash,
    show_status_splash,
    SimpleStatusInterface,
    confirmation_handler,
    console  # Import the shared console from ux
)


logger = logging.getLogger(__name__)


#====================================================================================================
# Cli session, example config, and status functions
#====================================================================================================


def create_session(context_ldr: ContextLoader):
    
    if not os.path.exists(".da"):
        os.makedirs(".da")

    # Load project context
    project_context = context_ldr.load_project_context()

    # Load MCP servers
    mcp_servers = context_ldr.load_mcp_servers()

    # Determine working directory
    working_dir = os.getcwd()

    # Create session
    code_session = CodeSession(
        working_directory=working_dir,
        project_context=project_context,
        mcp_servers=mcp_servers,
    )
    return code_session


def create_example_configuration(config_mgr: ConfigManager, context_ldr: ContextLoader) -> int:
    """Setup configuration files."""
    show_status_splash()
    print("🔧 Setting up da_code configuration...")

    try:
        # Create sample environment file
        config_mgr.create_sample_env()

        # Create sample context files if they don't exist
        if not Path('AGENTS.md').exists():
            context_ldr.create_sample_agents_md()

        if not Path('DA.json').exists():
            context_ldr.create_sample_da_json()

        print("\n✅ Setup complete!")
        print("\nNext steps:")
        print("1. Edit .env with your Azure OpenAI credentials")
        print("2. Edit AGENTS.md with your project information")
        print("3. Edit DA.json with your MCP server configuration")
        print("4. Run 'da_code status' to verify configuration")
        print("5. Run 'da_code' to start interactive session")

        return 0

    except Exception as e:
        print(f"❌ Setup failed: {e}")
        return 1


def show_status(config_mgr: ConfigManager, context_ldr: ContextLoader) -> int:
    """Show configuration and system status."""
    try:
        config_mgr.print_config_status()

        # Check project context
        print("\n=== Project Context ===")
        project_context = context_ldr.load_project_context()
        if project_context:
            print(f"✓ AGENTS.md loaded: {project_context.project_name or 'Unnamed project'}")
        else:
            print("✗ AGENTS.md not found or empty")

        # Check MCP servers
        mcp_servers = context_ldr.load_mcp_servers()
        print(f"\n=== MCP Servers ===")
        if mcp_servers:
            print(f"✓ Found {len(mcp_servers)} MCP servers:")
            for server in mcp_servers:
                print(f"  - {server.name}: {server.url}")
        else:
            print("✗ No MCP servers configured")

        return 0

    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return 1


#====================================================================================================
# Shell mode and command execution
#====================================================================================================


class ShellCompleter(Completer):
    """Custom completer for shell commands with file/directory completion."""

    def __init__(self):
        # Common shell commands
        self.shell_commands = [
            'ls', 'cd', 'pwd', 'mkdir', 'rmdir', 'rm', 'cp', 'mv', 'cat', 'less', 'more',
            'grep', 'find', 'which', 'whereis', 'locate', 'chmod', 'chown', 'touch',
            'head', 'tail', 'wc', 'sort', 'uniq', 'cut', 'awk', 'sed', 'tar', 'gzip',
            'gunzip', 'zip', 'unzip', 'ps', 'top', 'htop', 'kill', 'killall', 'jobs',
            'bg', 'fg', 'nohup', 'screen', 'tmux', 'ssh', 'scp', 'rsync', 'curl', 'wget',
            'git', 'python', 'python3', 'pip', 'pip3', 'node', 'npm', 'yarn', 'docker',
            'docker-compose', 'make', 'cmake', 'gcc', 'g++', 'javac', 'java', 'go',
            'cargo', 'rustc', 'echo', 'printf', 'date', 'cal', 'uptime', 'df', 'du',
            'free', 'uname', 'whoami', 'id', 'groups', 'su', 'sudo', 'history', 'alias',
            'export', 'env', 'printenv', 'source', 'bash', 'sh', 'zsh', 'fish'
        ]
        self.path_completer = PathCompleter()
        self.command_completer = WordCompleter(self.shell_commands)

    def get_completions(self, document, complete_event):
        text = document.text

        # If empty, complete commands
        if not text.strip():
            yield from self.command_completer.get_completions(document, complete_event)
            return

        words = text.split()

        # If we have multiple words OR the text ends with space, complete file paths
        if len(words) > 1 or (len(words) == 1 and text.endswith(' ')):
            yield from self.path_completer.get_completions(document, complete_event)
        else:
            # Single word without trailing space - could be command or path
            # Try both command completion and path completion
            command_completions = list(self.command_completer.get_completions(document, complete_event))
            path_completions = list(self.path_completer.get_completions(document, complete_event))

            # Yield command completions first, then path completions
            yield from command_completions
            yield from path_completions


class NudgeCompleter(Completer):
    """Custom completer for agent mode with symbol-triggered completions."""

    def __init__(self, working_dir: str = None):
        self.nudge_phrases = NUDGE_PHRASES
        self.path_completer = PathCompleter(expanduser=True)
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self._all_files_cache = None

    def _get_all_project_files(self):
        """Get all files in project recursively (cached)."""
        if self._all_files_cache is not None:
            return self._all_files_cache

        all_files = []
        ignored = {'.git', '.env', '__pycache__', 'node_modules', '.venv', 'venv', '.da', 'dist', 'build', '*-egg-info'}

        try:
            for item in self.working_dir.rglob('*'):
                # Skip ignored directories
                if any(ignored_dir in item.parts for ignored_dir in ignored):
                    continue

                if item.is_file():
                    # Store relative path from working dir
                    try:
                        rel_path = item.relative_to(self.working_dir)
                        all_files.append(str(rel_path))
                    except ValueError:
                        continue

            self._all_files_cache = sorted(all_files)
        except Exception as e:
            logger.error(f"Error scanning project files: {e}")
            self._all_files_cache = []

        return self._all_files_cache

    def _grep_files(self, search_term: str):
        """Search file contents using grep/ripgrep."""
        # Strip quotes if present
        search_term = search_term.strip('\'"')
        if not search_term:
            return []

        ignored_dirs = ['--exclude-dir=.git', '--exclude-dir=__pycache__',
                       '--exclude-dir=node_modules', '--exclude-dir=.venv',
                       '--exclude-dir=venv', '--exclude-dir=.da']

        try:
            # Try ripgrep first (faster)
            result = subprocess.run(
                ['rg', '--files-with-matches', '--no-heading', search_term] +
                ['--glob', '!.git/', '--glob', '!__pycache__/', '--glob', '!node_modules/',
                 '--glob', '!.venv/', '--glob', '!venv/', '--glob', '!.da/'],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            # Fallback to grep
            result = subprocess.run(
                ['grep', '-rl'] + ignored_dirs + [search_term, '.'],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return [f.lstrip('./') for f in result.stdout.strip().split('\n')]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return []

    def get_completions(self, document, complete_event):
        """Provide completions based on trigger symbols: ! @ ~"""
        text = document.text

        # Check for ! (nudge phrases)
        exclaim_pos = text.rfind('!')
        if exclaim_pos != -1 and exclaim_pos <= document.cursor_position:
            phrase_start = exclaim_pos + 1
            phrase_text = text[phrase_start:document.cursor_position]

            for phrase in self.nudge_phrases:
                if phrase.lower().startswith(phrase_text.lower()):
                    # Remove ! and partial text, add full phrase + comma
                    yield Completion(
                        phrase + ", ",
                        start_position=-(len(phrase_text) + 1),  # Remove ! + typed text
                        display=phrase,
                        display_meta="💡",
                    )
            return

        # Check for ~ (content search)
        tilde_pos = text.rfind('~')
        if tilde_pos != -1 and tilde_pos <= document.cursor_position:
            search_start = tilde_pos + 1
            search_text = text[search_start:document.cursor_position]

            # Always try to search (even if empty, to show an indicator)
            try:
                matching_files = self._grep_files(search_text) if search_text else []
                if matching_files:
                    for file_path in matching_files[:20]:  # Limit to 20 results
                        yield Completion(
                            file_path + ", ",
                            start_position=-(len(search_text) + 1),  # Remove ~ + search term
                            display=file_path,
                            display_meta="🔍",
                        )
                elif search_text:  # Show message if no results
                    yield Completion(
                        "",
                        start_position=0,
                        display=f"No files found containing '{search_text}'",
                        display_meta="❌",
                    )
            except Exception as e:
                logger.error(f"Content search error: {e}")
                yield Completion(
                    "",
                    start_position=0,
                    display=f"Search error: {str(e)}",
                    display_meta="❌",
                )
            return

        # Check for @ (file path mode)
        at_pos = text.rfind('@')
        if at_pos != -1 and at_pos <= document.cursor_position:
            path_start = at_pos + 1
            path_text = text[path_start:document.cursor_position]

            # Check for @@ (fuzzy search all files)
            if path_text.startswith('@'):
                search_term = path_text[1:].lower()
                all_files = self._get_all_project_files()

                for file_path in all_files:
                    if not search_term or search_term in file_path.lower():
                        yield Completion(
                            file_path + ", ",
                            start_position=-(len(path_text)),  # Remove @@ + search term
                            display=file_path,
                            display_meta="📁",
                        )
            else:
                # Normal path completion
                from prompt_toolkit.document import Document
                path_doc = Document(path_text, len(path_text))

                for completion in self.path_completer.get_completions(path_doc, complete_event):
                    # PathCompleter gives us the right start_position for the path part
                    # Add comma only for files, not directories
                    # Directories end with / or \
                    completed_path = "@" + path_text[:len(path_text) + completion.start_position] + completion.text

                    # Check if it's a directory (ends with path separator)
                    if completed_path.endswith('/') or completed_path.endswith('\\'):
                        # Directory - no comma, allow continued navigation
                        suffix = ""
                    else:
                        # File - add comma and space
                        suffix = ", "

                    yield Completion(
                        completed_path + suffix,
                        start_position=-(len(path_text) + 1),  # Remove @ + entire path_text
                        display=completion.display,
                        display_meta=completion.display_meta,
                    )


class ShellModeManager:
    """Manages shell mode and captures command output for agent context."""

    def __init__(self):
        self.is_shell_mode = False
        self.shell_history = []
        self.max_history_entries = 50
        self.shell_command_history = []  # Separate history for shell commands only

    def toggle_shell_mode(self):
        """Toggle between shell mode and agent mode."""
        self.is_shell_mode = not self.is_shell_mode
        mode_name = "shell" if self.is_shell_mode else "agent"
        console.print(f"[cyan]🔧 Switched to {mode_name} mode[/cyan]")

    def execute_shell_command(self, command: str) -> str:
        """Execute shell command and capture output."""
        # Add command to shell command history for up/down arrow navigation
        if command.strip() and (not self.shell_command_history or command != self.shell_command_history[-1]):
            self.shell_command_history.append(command)
            # Keep shell command history manageable
            if len(self.shell_command_history) > 1000:
                self.shell_command_history = self.shell_command_history[-1000:]
        

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Combine stdout and stderr
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            # Add to history for agent context
            self.shell_history.append({
                'command': command,
                'output': output,
                'return_code': result.returncode,
                'timestamp': time.time()
            })

            # Keep only recent entries
            if len(self.shell_history) > self.max_history_entries:
                self.shell_history = self.shell_history[-self.max_history_entries:]

            return output

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after 30 seconds: {command}"
            self.shell_history.append({
                'command': command,
                'output': error_msg,
                'return_code': -1,
                'timestamp': time.time()
            })
            return error_msg

        except Exception as e:
            error_msg = f"Shell execution error: {str(e)}"
            self.shell_history.append({
                'command': command,
                'output': error_msg,
                'return_code': -1,
                'timestamp': time.time()
            })
            return error_msg

    def get_shell_context_for_agent(self) -> str:
        """Get recent shell commands and output as context for the agent."""
        if not self.shell_history:
            return ""

        context_lines = ["Recent shell commands and their output:"]

        # Get last 5 commands for context
        recent_commands = self.shell_history[-5:]

        for entry in recent_commands:
            context_lines.append(f"\n$ {entry['command']}")
            if entry['return_code'] == 0:
                context_lines.append(f"Output:\n{entry['output'][:1000]}")  # Limit output length
            else:
                context_lines.append(f"Error (code {entry['return_code']}):\n{entry['output'][:1000]}")

        return "\n".join(context_lines)



#====================================================================================================
# async main with status interface and command loop
#====================================================================================================


# Available commands
commands = ['help', 'setup', 'status', 'add_mcp', 'shell', 'exit', 'quit', 'q']

async def async_main():
    """Async main with simple status interface."""
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
        # Initialize agent if config is valid
        status_interface.start_execution("Initializing session...")
        code_session = create_session(context_ldr=ContextLoader())
        if code_session is None:
            status_interface.stop_execution(False, "Session creation failed")
            raise ValueError("Failed to create code session!")

        status_interface.update_status("Initializing Agno agent...")

        # Directory context for change detection
        dir_context = DirectoryContext(code_session.working_directory)
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
                if agent.db_type == 'postgres':
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

            # Combined status line
            status_interface.stop_execution(True, f"🤖 {deployment_name} | 🤔 {reasoning_deployment} | 💾 {memory_status} | 📡 {mongo_status_str}{mcp_servers}")

    # Set up history files
    agent_history = FileHistory(agent.config.history_file_path)
    shell_history_path = os.getenv('DA_CODE_SHELL_HISTORY', f'.da{os.sep}shell_history')
    shell_history = FileHistory(shell_history_path)

    # Set up completers
    shell_completer = ShellCompleter()
    nudge_completer = NudgeCompleter(working_dir=code_session.working_directory)  # Nudge phrase autocomplete for agent mode

    # Create key bindings for shell mode toggle and completion
    bindings = KeyBindings()

    # Storage for pasted content (maps placeholder to content)
    pasted_content_storage = {}
    paste_counter = [0]  # Mutable counter for unique paste IDs

    # Use '#' (Shift+3) to toggle shell/agent mode and provide shell history navigation
    shell_history_index = [None]  # Mutable index for navigating shell_command_history

    @bindings.add('#')  # '#' (Shift+3)
    def _(event):
        """Toggle shell mode with '#' key (Shift+3)."""
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
            pasted_text = event.data
            if pasted_text:
                pasted_text = pasted_text.rstrip('\n')
                lines = pasted_text.split('\n')
                line_count = len(lines)

                # Create unique placeholder with ID
                paste_counter[0] += 1
                paste_id = paste_counter[0]
                placeholder = f"[[paste#{paste_id}: {line_count} line{'s' if line_count != 1 else ''}]]"

                # Store the actual pasted content with placeholder as key
                pasted_content_storage[placeholder] = pasted_text

                # Insert placeholder in buffer
                event.current_buffer.insert_text(placeholder)

        except Exception as e:
            logger.error(f"Paste error: {e}")
            # On error, do default paste if possible
            try:
                event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
            except Exception:
                pass

    @bindings.add('c-v')  # Ctrl+V
    def _(event):
        """Handle Ctrl+V paste from clipboard (desktop terminals)."""
        try:
            data = None
            try:
                data = event.app.clipboard.get_data().text
            except Exception:
                # Some clipboards return ClipboardData with 'data' attr
                try:
                    data = event.app.clipboard.get_data().data
                except Exception:
                    data = None

            if data:
                pasted_text = data.rstrip('\n')
                lines = pasted_text.split('\n')
                line_count = len(lines)

                paste_counter[0] += 1
                paste_id = paste_counter[0]
                placeholder = f"[[paste#{paste_id}: {line_count} line{'s' if line_count != 1 else ''}]]"

                pasted_content_storage[placeholder] = pasted_text
                event.current_buffer.insert_text(placeholder)
            else:
                # Fallback to default paste behavior
                event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
        except Exception as e:
            logger.error(f"Ctrl+V paste error: {e}")
            try:
                event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
            except Exception:
                pass

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
        user_id = "dang"
    
    
    async with asyncio.TaskGroup() as tg:
        wait_for_input = tg.create_task(get_user_input_with_history(input_queue))
        #task2 = tg.create_task(another_coro(...))
 
        running_agent = None
        status_message = None
        output_message = None
        while True:
            try:
                # If agent is not running then wait for input command 
                if running_agent is None:
                    if wait_for_input.done():
                        console.print(f"ERROR: wait_for_input is done!! {wait_for_input.result()}")
                    user_input = await input_queue.get()
                elif running_agent.done():
                    try:
                        final_response = running_agent.result()
                        status_message = None
                        running_agent = None
                        status_interface.stop_execution(True)
                        console.print()
                        console.print(output_message)
                        output_message = None
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
                        status_message = await status_queue.get()
                    status_interface.update_status(f"{status_message}")
                    await asyncio.sleep(0.01)
                    continue

                if user_input is None:
                    continue

                if user_input.lower() in ['exit', 'quit', 'q']:
                    console.print("👋 Goodbye!")
                    break
                elif user_input.lower() == 'help':
                    console.print("[bold]Available commands:[/bold]")
                    console.print("  • help - Show this help message")
                    console.print("  • setup - Create configuration files")
                    console.print("  • status - Show current configuration status")
                    console.print("  • add_mcp <url> [name] - Add MCP server dynamically")
                    console.print("  • exit/quit/q - Exit the application")
                    console.print("\n[bold]Agent Mode - Left-hand Ergonomic Triggers:[/bold]")
                    console.print("  • [cyan]![/cyan] - AI nudge phrases: '!be<Tab>' → 'be careful and check your work' 💡")
                    console.print("  • [cyan]@[/cyan] - File paths: '@src/<Tab>' → navigate directories 📁")
                    console.print("  • [cyan]@@[/cyan] - Fuzzy filename: '@@auth<Tab>' → all files with 'auth' in name 📁")
                    console.print("  • [cyan]~[/cyan] - Content search: '~async def<Tab>' → files containing 'async def' 🔍")
                    console.print("  • [cyan]#[/cyan] - Toggle shell mode (Shift+3)")
                    console.print("  • [cyan]$[/cyan] - Reserved for future use")
                    console.print("\n[bold]Clipboard:[/bold]")
                    console.print("  • [cyan]Ctrl+V or terminal paste[/cyan] - Paste shows '[[paste#N: X lines]]' placeholder, actual content sent to agent")
                    console.print("  • Delete placeholder to exclude that paste from context")
                    console.print("\n[bold]Shell Mode:[/bold]")
                    console.print("  • Type [cyan]shell[/cyan] or press [cyan]#[/cyan] to toggle between modes")
                    console.print("  • In shell mode, commands are executed directly")
                    console.print("  • [cyan]Tab[/cyan] completion for commands and file paths")
                    console.print("  • Shell output is automatically included in next agent prompt")
                elif user_input.lower() == 'setup':
                    create_example_configuration(config_mgr=ConfigManager(), context_ldr=ContextLoader())
                    console.print("[green]Edit files and reload to update agent context[/green]")
                elif user_input.lower() == 'status':
                    show_status(config_mgr=ConfigManager(), context_ldr=ContextLoader())
                elif user_input.lower() == 'shell':
                    shell_manager.toggle_shell_mode()
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
                        # Check for directory changes and add to user input if needed
                        dir_update = dir_context.check_changes(cache_timestamp)
                        if dir_update:
                            # Update cache with fresh listing
                            directory_cache, cache_timestamp = dir_context.get_directory_listing()

                        # Add shell context to the user input if available
                        shell_context = shell_manager.get_shell_context_for_agent()
                        enhanced_input = user_input

                        # Prepend contexts in order: pasted content, directory updates, then shell context
                        context_parts = []

                        # Add pasted content ONLY if placeholder still exists in user_input
                        if pasted_content_storage:
                            pasted_sections = []
                            for placeholder, pasted_text in pasted_content_storage.items():
                                # Only include if placeholder is still in the input
                                if placeholder in user_input:
                                    pasted_sections.append(f"Pasted content from {placeholder}:\n```\n{pasted_text}\n```")

                            if pasted_sections:
                                context_parts.append("\n\n".join(pasted_sections))

                            # Clear pasted content after using it
                            pasted_content_storage.clear()

                        if dir_update:
                            context_parts.append(dir_update)
                        if shell_context:
                            context_parts.append(shell_context)

                        if context_parts:
                            context_str = "\n\n".join(context_parts)
                            enhanced_input = f"{context_str}\n\nUser request: {user_input}"
                        
                        sanitized_input = enhanced_input.encode('utf-8', 'replace').decode('utf-8')

                        status_message = f"Calculating: {user_input[:40]}..."
                        status_interface.start_execution(status_message)
                        output_message = ""
                        logger.warning(f"Input Context : {enhanced_input}")
                        running_agent = tg.create_task(
                            agent.arun(sanitized_input, confirm_wrapper, status_queue, output_queue, user_id)
                        )
                        user_input = None
                    except Exception as e:
                        status_interface.stop_execution(False, str(e))
                        console.print(f"[red]Sorry, I encountered an error: {str(e)}[/red]")
                        logger.error(f"Agent chat error: {type(e).__name__}: {str(e)}", exc_info=True)

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
    parser.add_argument('--working-dir', type=str, help='Working directory')
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
        
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Main execution error: {e}")

if __name__ == '__main__':
    main()
