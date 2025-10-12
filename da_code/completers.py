"""Custom completers for da_code CLI - NudgeCompleter and ShellCompleter."""

import logging
import time
from pathlib import Path
from typing import Optional

from prompt_toolkit.completion import Completer, Completion, PathCompleter, WordCompleter

from .context import NUDGE_PHRASES

logger = logging.getLogger(__name__)


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

    def __init__(self, working_dir: str = None, code_session=None, search_storage: dict = None):
        self.nudge_phrases = NUDGE_PHRASES
        self.path_completer = PathCompleter(expanduser=True)
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self.code_session = code_session  # Access to session snapshot for content search
        self._all_files_cache = None
        self._cache_timestamp = 0  # Timestamp of last cache refresh
        self._cache_ttl = 30  # Cache TTL in seconds
        self.search_storage = search_storage if search_storage is not None else {}

    def _get_all_project_files(self):
        """Get all files in project recursively (cached with TTL)."""
        import time
        current_time = time.time()

        # Check if cache is valid (exists and not expired)
        if self._all_files_cache is not None and (current_time - self._cache_timestamp) < self._cache_ttl:
            return self._all_files_cache

        # Cache expired or doesn't exist - refresh it
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
            self._cache_timestamp = current_time
        except Exception as e:
            logger.error(f"Error scanning project files: {e}")
            self._all_files_cache = []
            self._cache_timestamp = current_time

        return self._all_files_cache

    def invalidate_file_cache(self):
        """Manually invalidate the file cache (e.g., after file system changes)."""
        self._all_files_cache = None
        self._cache_timestamp = 0

    def _get_modified_files(self):
        """Get list of files modified during this session."""
        if not self.code_session or not self.code_session.filesystem_history:
            return []

        modified_files = set()
        for change in self.code_session.filesystem_history.changes:
            if change.relative_path:
                modified_files.add(change.relative_path)

        return sorted(modified_files)

    def _get_file_revisions(self, relative_path: str):
        """Get all revisions for a specific file with metadata.

        Returns list of tuples: (revision_number, lines_changed, time_ago_str, timestamp)
        Only includes revisions where content actually changed (deduplicates).
        """
        if not self.code_session or not self.code_session.filesystem_history:
            return []

        revisions = []
        changes_for_file = []

        # Collect all changes for this file
        for change in self.code_session.filesystem_history.changes:
            if change.relative_path == relative_path:
                changes_for_file.append(change)

        if not changes_for_file:
            return []

        # Deduplicate: only keep changes where content actually changed
        unique_changes = []
        last_content = None

        for change in changes_for_file:
            # Only include if content is different from last revision
            if change.content_snapshot != last_content:
                unique_changes.append(change)
                last_content = change.content_snapshot

        # Number revisions chronologically (#1 = oldest, #N = newest)
        import time
        current_time = time.time()

        for idx, change in enumerate(unique_changes, start=1):
            # Calculate lines changed
            lines_changed = self._calculate_lines_changed(change)

            # Calculate time delta
            if hasattr(change, 'timestamp') and change.timestamp:
                delta_seconds = current_time - change.timestamp.timestamp()
            else:
                delta_seconds = 0

            time_str = self._format_time_ago(delta_seconds)

            revisions.append((idx, lines_changed, time_str, change.timestamp if hasattr(change, 'timestamp') else None))

        return revisions

    def _calculate_lines_changed(self, change):
        """Calculate number of lines changed in a FileChange."""
        try:
            if change.content_snapshot and change.pre_change_snapshot:
                old_lines = change.pre_change_snapshot.count('\n') + 1
                new_lines = change.content_snapshot.count('\n') + 1
                return abs(new_lines - old_lines)
            elif change.content_snapshot:
                # New file or only have current content
                return change.content_snapshot.count('\n') + 1
            else:
                return 0
        except:
            return 0

    def _format_time_ago(self, seconds: float) -> str:
        """Format seconds into human-readable time ago string."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds/60)}m"
        elif seconds < 86400:
            return f"{int(seconds/3600)}h"
        else:
            return f"{int(seconds/86400)}d"

    def _search_snapshot(self, search_term: str, include_lines: bool = True):
        """Search file contents using the session snapshot index (respects .daignore).

        Uses the session_start_snapshot which is already filtered by .daignore.

        Args:
            search_term: The term to search for
            include_lines: If True, include line numbers and matching lines in results

        Returns:
            Dict mapping file paths to match details:
            {
                'file.py': {
                    'line_numbers': [10, 25, 47],
                    'matches': [
                        {'line_num': 10, 'content': 'async def foo():'},
                        ...
                    ]
                }
            }
        """
        # Strip quotes if present
        search_term = search_term.strip('\'"')
        if not search_term:
            return {}

        # Use session snapshot if available
        if self.code_session and self.code_session.filesystem_history:
            snapshot = self.code_session.filesystem_history.session_start_snapshot
            if not snapshot:
                return {}

            matching_files = {}
            search_lower = search_term.lower()

            # Search through snapshot content
            for relative_path, file_snapshot in snapshot.items():
                # Only search text files with content
                if file_snapshot.is_binary or not file_snapshot.content:
                    continue

                lines = file_snapshot.content.split('\n')
                line_matches = []
                line_numbers = []

                for line_num, line in enumerate(lines, start=1):
                    if search_lower in line.lower():
                        line_numbers.append(line_num)
                        if include_lines:
                            # Trim long lines for display
                            trimmed_line = line.strip()
                            if len(trimmed_line) > 80:
                                trimmed_line = trimmed_line[:77] + '...'
                            line_matches.append({
                                'line_num': line_num,
                                'content': trimmed_line
                            })

                if line_numbers:
                    matching_files[relative_path] = {
                        'line_numbers': line_numbers,
                        'matches': line_matches
                    }

            return matching_files

        # Fallback if no snapshot available
        return {}

    def get_completions(self, document, complete_event):
        """Provide completions based on trigger symbols: ! @ ~ and restore command"""
        text = document.text

        # Check for "restore " command (file-specific restore)
        if text.startswith('restore '):
            restore_arg = text[8:document.cursor_position]  # Everything after "restore "

            # Simple single-level completion - just show modified files
            # User can manually type revision number after: "restore file.py #2"
            file_prefix = restore_arg.strip()
            modified_files = self._get_modified_files()

            if modified_files:
                for file_path in modified_files:
                    if not file_prefix or file_path.lower().startswith(file_prefix.lower()):
                        # Get revision info for display
                        revisions = self._get_file_revisions(file_path)
                        rev_count = len(revisions)

                        # Build display metadata showing revision options
                        if rev_count > 0:
                            display_meta = f"📝 {rev_count} rev{'s' if rev_count != 1 else ''} (session start or #1-#{rev_count})"
                        else:
                            display_meta = f"📝 (session start only)"

                        yield Completion(
                            file_path,
                            start_position=-len(file_prefix),
                            display=file_path,
                            display_meta=display_meta,
                        )
            else:
                yield Completion(
                    "",
                    start_position=0,
                    display="No modified files in this session",
                    display_meta="ℹ️",
                )
            return  # Don't show other completions

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
                if search_text:  # Only search if there's a search term
                    # Minimum search term length validation
                    if len(search_text) < 2:
                        yield Completion(
                            "",
                            start_position=0,
                            display="Type at least 2 characters to search",
                            display_meta="⚠️",
                        )
                        return

                    matching_files_dict = self._search_snapshot(search_text, include_lines=True)
                    if matching_files_dict:
                        file_count = len(matching_files_dict)

                        # Warn if too many matches (term too broad)
                        if file_count > 100:
                            yield Completion(
                                "",
                                start_position=0,
                                display=f"⚠️ {file_count} files found - term too broad, refine search",
                                display_meta="⚠️",
                            )
                            return

                        # Use search term as identifier instead of incrementing number
                        # Format: [[search:term: N files]]
                        placeholder = f"[[search:{search_text}: {file_count} file{'s' if file_count != 1 else ''}]]"

                        # Store rich match data in search_storage
                        # This allows the main loop to find it when user accepts
                        self.search_storage[placeholder] = {
                            'term': search_text,
                            'files': matching_files_dict
                        }

                        # Offer the placeholder as completion
                        yield Completion(
                            placeholder + ", ",
                            start_position=-(len(search_text) + 1),  # Remove ~ + search term
                            display=f"{file_count} file{'s' if file_count != 1 else ''} containing '{search_text}'",
                            display_meta="🔍",
                        )
                    else:
                        # No results found
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
