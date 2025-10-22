import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Union, Literal
import httpx
from pathlib import Path
from agno.tools import Toolkit
from pydantic import BaseModel, Field, ConfigDict
from .models import (
    AgentConfig, CodeSession, CommandExecution, CommandStatus,
    LLMCall, LLMCallStatus, ToolCall, ToolCallStatus, UserResponse, da_mongo
)
from .daignore import DaIgnore
import subprocess
import os
import re
import glob

import logging
import difflib
import tempfile
import shutil
logger = logging.getLogger(__name__)

#====================================================================================================
# Patch Utilities (for produce_patch and apply_patch)
#====================================================================================================

def _is_within_root(target_path: str, root: str) -> bool:
    """Check if target path is within root directory."""
    root = os.path.abspath(root)
    target = os.path.abspath(target_path)
    try:
        return os.path.commonpath([root]) == os.path.commonpath([root, target])
    except ValueError:
        return False


def _read_text_file_preserve_newlines(path: str):
    """Read file preserving newline style."""
    from pathlib import Path
    b = Path(path).read_bytes()
    if b.find(b'\x00') != -1:
        raise ValueError("binary file (contains NUL bytes)")
    newline_style = '\r\n' if b.find(b'\r\n') != -1 else '\n'
    try:
        text = b.decode('utf-8')
    except Exception:
        text = b.decode('latin1')
    return text, newline_style


def _atomic_write(path: str, data: bytes):
    """Atomically write data to file."""
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dirpath)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _produce_patch_impl(path: str, new_contents: str) -> str:
    """Produce a unified diff between current file contents and new_contents."""
    from pathlib import Path
    path = os.fspath(path)
    try:
        old_text, _ = _read_text_file_preserve_newlines(path)
    except FileNotFoundError:
        old_text = ""
    except ValueError:
        raise

    old_lines = old_text.splitlines(keepends=False)
    new_lines = new_contents.splitlines(keepends=False)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm='\n'
        )
    )
    return "\n".join(diff_lines) + ("\n" if diff_lines else "")


def _apply_patch_impl(patch_text: str, dry_run: bool = True, backup: bool = True,
                      workspace_root: Optional[str] = None, fuzzy: bool = False):
    """Apply a unified diff patch."""
    import time
    import datetime

    workspace_root = os.path.abspath(workspace_root or os.getcwd())
    results = []

    # Fallback parser
    lines = patch_text.splitlines()
    i = 0
    files = []
    while i < len(lines):
        line = lines[i]
        if line.startswith('--- '):
            fromfile = line[4:].strip()
            i += 1
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            if i >= len(lines):
                break
            tofile_line = lines[i]
            if not tofile_line.startswith('+++ '):
                i += 1
                continue
            tofile = tofile_line[4:].strip()
            for pref in ('a/', 'b/'):
                if fromfile.startswith(pref):
                    fromfile = fromfile[len(pref):]
                if tofile.startswith(pref):
                    tofile = tofile[len(pref):]
            current = {"fromfile": fromfile, "tofile": tofile, "hunks": []}
            i += 1
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            while i < len(lines) and lines[i].startswith('@@'):
                hunk_header = lines[i]
                i += 1
                hunk_lines = []
                while i < len(lines) and not lines[i].startswith('@@') and not lines[i].startswith('--- '):
                    hunk_lines.append(lines[i])
                    i += 1
                current['hunks'].append({"header": hunk_header, "lines": hunk_lines})
            files.append(current)
        else:
            i += 1

    # Get daignore instance for checking ignored paths
    daignore = get_daignore()

    for file_entry in files:
        tofile = file_entry['tofile']
        abs_target = os.path.abspath(tofile)

        # Check workspace boundary
        if not _is_within_root(abs_target, workspace_root):
            results.append({"file": abs_target, "status": "error", "message": "path outside workspace"})
            continue

        # Check .daignore rules
        if daignore.is_ignored(abs_target):
            results.append({"file": abs_target, "status": "error", "message": "access denied: path is ignored by .daignore"})
            continue

        file_result = {"file": abs_target, "status": None, "hunks": []}
        exists = os.path.exists(abs_target)
        if not exists:
            if dry_run:
                file_result['status'] = "created"
                file_result['message'] = "file would be created"
            else:
                pass
        try:
            old_text, newline = _read_text_file_preserve_newlines(abs_target) if exists else ("", "\n")
        except ValueError:
            file_result['status'] = "error"
            file_result['message'] = "binary file"
            results.append(file_result)
            continue
        old_lines = old_text.splitlines(keepends=True)
        new_lines = list(old_lines)
        hunk_index = 0
        overall_conflict = False
        for hunk in file_entry['hunks']:
            header = hunk['header']
            try:
                parts = header.split()
                minus = parts[1]
                plus = parts[2]
                def parse_range(r):
                    r = r.lstrip('+-')
                    if ',' in r:
                        start, cnt = r.split(',', 1)
                        return int(start), int(cnt)
                    else:
                        return int(r), 1
                from_start, from_count = parse_range(minus)
                to_start, to_count = parse_range(plus)
            except Exception:
                file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": "invalid hunk header"})
                overall_conflict = True
                hunk_index += 1
                continue

            old_pos = from_start - 1
            idx_cursor = old_pos
            expected_ok = True
            consumed_old = 0
            for l in hunk['lines']:
                if l.startswith(' '):
                    expected_line = l[1:]
                    if idx_cursor >= len(new_lines):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": f"context line beyond EOF: expected {expected_line!r}"})
                        break
                    if new_lines[idx_cursor].rstrip('\r\n') != expected_line.rstrip('\r\n'):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": f"context mismatch at line {idx_cursor+1}"})
                        break
                    idx_cursor += 1
                    consumed_old += 1
                elif l.startswith('-'):
                    expected_line = l[1:]
                    if idx_cursor >= len(new_lines):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": "removal beyond EOF"})
                        break
                    if new_lines[idx_cursor].rstrip('\r\n') != expected_line.rstrip('\r\n'):
                        expected_ok = False
                        file_result['hunks'].append({"hunk_index": hunk_index, "status": "conflict", "message": f"removal mismatch at line {idx_cursor+1}"})
                        break
                    idx_cursor += 1
                    consumed_old += 1
                elif l.startswith('+'):
                    pass
                else:
                    pass

            if not expected_ok:
                overall_conflict = True
                hunk_index += 1
                continue

            if dry_run:
                file_result['hunks'].append({"hunk_index": hunk_index, "status": "appliable", "message": "hunk matches current file"})
            else:
                apply_idx = from_start - 1
                out_block = []
                scan_idx = apply_idx
                for l in hunk['lines']:
                    if l.startswith(' '):
                        out_block.append(new_lines[scan_idx])
                        scan_idx += 1
                    elif l.startswith('-'):
                        scan_idx += 1
                    elif l.startswith('+'):
                        content = l[1:]
                        if content and not content.endswith(('\n', '\r\n')):
                            content += '\n'
                        elif not content:
                            content = '\n'
                        out_block.append(content)
                    else:
                        pass
                end_idx = apply_idx + consumed_old
                new_lines[apply_idx:end_idx] = out_block
                file_result['hunks'].append({"hunk_index": hunk_index, "status": "applied", "message": "hunk applied"})
            hunk_index += 1

        if overall_conflict:
            file_result['status'] = "conflict"
        else:
            file_result['status'] = "appliable" if dry_run else "applied"

        if not dry_run and not overall_conflict:
            new_text = "".join(new_lines)
            try:
                encoded = new_text.encode("utf-8")
            except Exception:
                encoded = new_text.encode("latin1", errors="replace")
            if exists and backup:
                ts = int(time.time())
                bak = f"{abs_target}.bak.{ts}"
                shutil.copy2(abs_target, bak)
            try:
                _atomic_write(abs_target, encoded)
                file_result['message'] = "written"
            except Exception as e:
                file_result['status'] = "error"
                file_result['message'] = f"write failed: {e}"

        results.append(file_result)

    return {"results": results}


#====================================================================================================
# Utilities
#====================================================================================================

# Global daignore instance (lazily initialized)
_daignore_instance = None

def get_daignore() -> DaIgnore:
    """Get or create the global DaIgnore instance."""
    global _daignore_instance
    if _daignore_instance is None:
        _daignore_instance = DaIgnore(project_root=get_workspace_root())
    return _daignore_instance


def get_workspace_root() -> str:
    """Get workspace root from environment variable or current directory."""
    return os.getenv('DA_CODE_WORKSPACE_ROOT', os.getcwd())


def within_workspace(path: str) -> bool:
    """Ensure the given path is within the allowed workspace."""
    workspace_root = os.path.abspath(get_workspace_root())
    abs_path = os.path.abspath(path)
    abs_workspace = os.path.abspath(workspace_root)
    return abs_path.startswith(abs_workspace)


def safe_path(path: str) -> str:
    """Resolve and validate a path inside the workspace and check .daignore."""
    workspace_root = os.path.abspath(get_workspace_root())

    # Handle absolute paths on Windows and Unix
    if os.path.isabs(path):
        abs_path = os.path.abspath(path)
    else:
        # Relative paths are resolved from workspace root
        abs_path = os.path.abspath(os.path.join(workspace_root, path))

    if not within_workspace(abs_path):
        raise ValueError(f"Path {abs_path} is outside workspace {workspace_root}")

    # Check if path is ignored by .daignore
    daignore = get_daignore()
    if daignore.is_ignored(abs_path):
        raise ValueError(f"Access denied: {abs_path} is ignored by .daignore")

    return abs_path


#====================================================================================================
# TODO Tool
#====================================================================================================

class TodoTool(Toolkit):
    """Todo.md file management tool."""

    def __init__(self, working_directory: str = None, **kwargs):
        """Initialize todo tool."""
        self.working_dir = working_directory or os.getcwd()
        self.todo_file = Path(self.working_dir) / "todo.md"

        super().__init__(
            name="todo_tool",
            tools=[
                self.read_todo,
                self.update_todo,
            ],
            **kwargs
        )

    def read_todo(self) -> str:
        """Read current contents of todo.md file."""
        try:
            if not self.todo_file.exists():
                return "No todo.md file exists in the current directory."

            content = self.todo_file.read_text(encoding='utf-8')
            if not content.strip():
                return "todo.md file exists but is empty."

            return content.strip()
        except Exception as e:
            return f"Error reading todo file: {str(e)}"

    def update_todo(self, content: str) -> str:
        """Create or update todo.md file with provided content."""
        try:
            # Ensure content follows proper markdown format
            if not content.strip().startswith('# '):
                content = f"# TODO\n\n{content.strip()}"

            self.todo_file.write_text(content.strip() + '\n', encoding='utf-8')
            return f"✅ Created/updated todo.md file"
        except Exception as e:
            return f"Error updating todo file: {str(e)}"


#====================================================================================================
# Command Tool
#====================================================================================================

class CommandTool(Toolkit):
    """Command execution tool."""

    def __init__(self, **kwargs):
        super().__init__(
            name="command_tool",
            tools=[self.execute_command],
            requires_confirmation_tools=['execute_command'],
            **kwargs
        )

    def execute_command(self, command: str, working_directory: str = None, explanation: str = None) -> str:
        """Execute shell/bash commands with user confirmation."""
        logger.info(f"🔧 SHELL_COMMAND TOOL CALLED with command: {command}")

        try:
            working_dir = working_directory or os.getcwd()

            logger.info(f"🔧 EXECUTING COMMAND: {command} in {working_dir}")
            start_time = time.time()
            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=300
            )

            logger.info(f"🔧 COMMAND RESULT: returncode={result.returncode}, stdout_len={len(result.stdout) if result.stdout else 0}")

            exec_time = time.time() - start_time

            if result.returncode == 0:
                output = f"✅ Command executed successfully ({exec_time:.2f}s)\n"
                if result.stdout:
                    stdout = result.stdout.strip()
                    output += f"Output:\n{stdout[:2000]}" + ("...\n(truncated)" if len(stdout) > 2000 else "")
                else:
                    output += "No output"
                return output
            else:
                output = f"❌ Command failed (exit code: {result.returncode})\n"
                if result.stderr:
                    stderr = result.stderr.strip()
                    output += f"Error:\n{stderr[:1000]}" + ("...\n(truncated)" if len(stderr) > 1000 else "")
                return output

        except subprocess.TimeoutExpired:
            return "❌ Command timed out after 5 minutes"
        except Exception as e:
            return f"❌ Command execution failed: {str(e)}"


#====================================================================================================
# File Tool
#====================================================================================================

class FileTool(Toolkit):
    """File operations tool - focused on core file operations."""

    def __init__(self, **kwargs):
        super().__init__(
            name="file_tool",
            tools=[
                self.read_file,
                self.create_file,
                # replace_text is deprecated — use produce_patch/apply_patch via patch_tool
                # keep shim for backward compatibility
                self.replace_text,
                self.produce_patch,
                self.apply_patch,
                self.copy_file,
                self.glob_files,
                self.grep_content,
            ],
            **kwargs
        )

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Read file contents (or specific line range).

        Args:
            path: Relative or absolute file path within workspace
            start_line: First line to read (1-indexed, default: 1)
            end_line: Last line to read (inclusive, default: None = read to end)

        Returns:
            File contents as string (UTF-8, with fallback error handling)

        Example:
            read_file("src/main.py")           # Read entire file
            read_file("src/main.py", 10, 20)   # Read lines 10-20
        """
        path = safe_path(path)
        with open(path, "r", encoding='utf-8', errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[start_line-1:end_line]) if end_line else "".join(lines[start_line-1:])

    def create_file(self, path: str, content: str = "") -> str:
        """Create a new file with the specified content.

        Args:
            path: Relative or absolute path to the file. Relative paths are resolved
                  from workspace root. Path must be within workspace and not .daignored.
            content: File content (default: empty string).

        Returns:
            Success: "Created file: {path} ({size} bytes)"
            Error: JSON object with "error" key

        Behavior:
            - Fails if file already exists (use replace_text to modify existing files)
            - Creates parent directories if they don't exist
            - Only accepts 'path' and 'content' parameters (no 'explanation' kwarg)

        Example:
            create_file("tests/test.txt", "line1\\nline2\\n")
            => "Created file: F:\\workspace\\tests\\test.txt (12 bytes)"
        """
        path = safe_path(path)

        # Check if file already exists
        if os.path.exists(path):
            return json.dumps({"error": f"File already exists: {path}. Use replace_text to modify."})

        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Create the file
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Created file: {path} ({len(content)} bytes)"
        except Exception as e:
            return json.dumps({"error": f"Failed to write file: {str(e)}"})

    def glob_files(self, pattern: str, path: Optional[str] = None, max_results: int = 100) -> str:
        """Find files matching glob pattern (respects .daignore).

        Args:
            pattern: Glob pattern (e.g., "**/*.txt", "src/**/*.py")
            path: Search root directory (default: workspace root)
            max_results: Maximum files to return (default: 100)

        Returns:
            JSON object containing:
            - pattern: The glob pattern used
            - search_root: Directory searched
            - matches: Number of files found
            - files: Array of file paths (sorted by modification time, newest first)

        Example:
            glob_files("**/*.txt", max_results=50)
        """
        daignore = get_daignore()
        search_root = path if path else get_workspace_root()

        try:
            search_root = safe_path(search_root)
        except Exception as e:
            return json.dumps({"error": f"Invalid path: {str(e)}"})

        # Build full glob pattern
        full_pattern = os.path.join(search_root, pattern)

        results = []
        try:
            for file_path in glob.glob(full_pattern, recursive=True):
                if os.path.isfile(file_path):
                    # Skip files ignored by .daignore
                    if daignore.is_ignored(file_path):
                        continue

                    try:
                        stat = Path(file_path).stat()
                        results.append({
                            "path": file_path,
                            "size": stat.st_size,
                            "modified": stat.st_mtime
                        })

                        if len(results) >= max_results:
                            break
                    except Exception:
                        continue

            # Sort by modification time (newest first)
            results.sort(key=lambda x: x['modified'], reverse=True)

            return json.dumps({
                "pattern": pattern,
                "search_root": search_root,
                "matches": len(results),
                "files": [r["path"] for r in results]
            })
        except Exception as e:
            return json.dumps({"error": f"Glob failed: {str(e)}"})

    def grep_content(self, pattern: str, path: Optional[str] = None,
                     file_pattern: Optional[str] = None, case_insensitive: bool = False,
                     context_lines: int = 0, max_results: int = 100) -> str:
        """Search file contents using regex pattern (respects .daignore).

        Args:
            pattern: Regular expression pattern to search for
            path: Search root directory (default: workspace root)
            file_pattern: Glob pattern to filter files (e.g., "*.txt", "*.{py,js}")
            case_insensitive: Perform case-insensitive search (default: False)
            context_lines: Number of lines to include before/after matches (default: 0)
            max_results: Maximum number of matches to return (default: 100)

        Returns:
            JSON object containing:
            - pattern: The search pattern used
            - search_root: Directory searched
            - files_searched: Number of files examined
            - matches: Number of matches found (after deduplication)
            - results: Array of match objects with file, line, content, and optional context

        Behavior:
            - Stops searching after max_results matches
            - Deduplicates matches by (file, line_number) to prevent duplicates
            - Skips binary files and .daignored paths

        Example:
            grep_content("TODO", file_pattern="**/*.py", case_insensitive=True, max_results=10)
        """
        daignore = get_daignore()
        search_root = path if path else get_workspace_root()

        try:
            search_root = safe_path(search_root)
        except Exception as e:
            return json.dumps({"error": f"Invalid path: {str(e)}"})

        # Compile regex pattern
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            return json.dumps({"error": f"Invalid regex pattern: {str(e)}"})

        # Determine files to search
        if file_pattern:
            glob_pattern = os.path.join(search_root, '**', file_pattern)
        else:
            glob_pattern = os.path.join(search_root, '**', '*')

        results = []
        seen_matches = set()  # Track (file_path, line_number) to prevent duplicates
        files_searched = 0

        try:
            for file_path in glob.glob(glob_pattern, recursive=True):
                if not os.path.isfile(file_path):
                    continue

                # Skip files ignored by .daignore
                if daignore.is_ignored(file_path):
                    continue

                files_searched += 1

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()

                    for i, line in enumerate(lines, start=1):
                        if regex.search(line):
                            # Deduplicate: skip if we've already seen this file:line combination
                            match_key = (file_path, i)
                            if match_key in seen_matches:
                                continue
                            seen_matches.add(match_key)

                            match_result = {
                                "file": file_path,
                                "line": i,
                                "content": line.rstrip('\n')
                            }

                            # Add context lines if requested
                            if context_lines > 0:
                                context_before = []
                                context_after = []

                                for j in range(1, context_lines + 1):
                                    if i - j > 0:
                                        context_before.insert(0, {
                                            "line": i - j,
                                            "content": lines[i - j - 1].rstrip('\n')
                                        })
                                    if i + j <= len(lines):
                                        context_after.append({
                                            "line": i + j,
                                            "content": lines[i + j - 1].rstrip('\n')
                                        })

                                if context_before:
                                    match_result["context_before"] = context_before
                                if context_after:
                                    match_result["context_after"] = context_after

                            results.append(match_result)

                            if len(results) >= max_results:
                                break

                    if len(results) >= max_results:
                        break

                except Exception:
                    continue

            return json.dumps({
                "pattern": pattern,
                "search_root": search_root,
                "files_searched": files_searched,
                "matches": len(results),
                "results": results
            })
        except Exception as e:
            return json.dumps({"error": f"Grep failed: {str(e)}"})

    def replace_text(self, path: str, search_text: str, replace_text: str,
                     use_regex: bool = False, case_sensitive: bool = True) -> str:
        """Replace text in a file (literal or regex).

        Args:
            path: File path within workspace
            search_text: Text to find (literal string or regex if use_regex=True)
            replace_text: Replacement text
            use_regex: Treat search_text as regex pattern (default: False)
            case_sensitive: Case-sensitive matching (default: True)

        Returns:
            "Replaced {count} occurrence(s) in {path}" or
            "No matches found — {path} left unchanged"

        Behavior:
            - Only writes file if at least one replacement made
            - For regex mode: supports capture groups in replace_text

        Example:
            replace_text("test.txt", "old", "new", case_sensitive=True)
        """
        path = safe_path(path)

        with open(path, "r", encoding='utf-8', errors="ignore") as f:
            content = f.read()

        if use_regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            new_content, count = re.subn(search_text, replace_text, content, flags=flags)
        else:
            if not case_sensitive:
                pattern = re.compile(re.escape(search_text), re.IGNORECASE)
                new_content, count = pattern.subn(replace_text, content)
            else:
                new_content = content.replace(search_text, replace_text)
                count = content.count(search_text)

        # safeguard: only overwrite if something was actually replaced
        if count > 0:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Replaced {count} occurrence(s) in {path}"
        else:
            return f"No matches found — {path} left unchanged"

    def produce_patch(self, path: str, new_contents: str) -> str:
        """Produce a unified diff between the current file contents and new_contents.

        Returns unified diff text (empty string if identical).
        """
        try:
            path_abs = safe_path(path)
        except Exception:
            # If path is invalid per safe_path, let caller handle the error via exception
            path_abs = path
        try:
            diff = _produce_patch_impl(path_abs, new_contents)
            return diff
        except Exception:
            return ""

    def apply_patch(self, patch_text: str, dry_run: bool = True, backup: bool = True, force: bool = False) -> str:
        """Apply a unified diff produced by produce_patch.

        Returns a JSON string summarizing per-file application results.
        In dry_run mode no files are modified; in non-dry-run mode files are written
        atomically and backups are created when backup=True.
        """
        import json

        # Use local implementation
        try:
            res = _apply_patch_impl(patch_text, dry_run=dry_run, backup=backup, workspace_root=get_workspace_root(), fuzzy=force)
            return json.dumps(res)
        except Exception as e:
            return json.dumps({"error": f"Patch application failed: {str(e)}"})

        # Legacy fallback code (keeping for reference)

        # Try to use python-patch if available
        try:
            import patch as patchlib
        except Exception:
            patchlib = None

        if patchlib is not None:
            try:
                # Different versions of python-patch expose different APIs. Try common factories.
                if hasattr(patchlib, 'fromstring'):
                    pset = patchlib.fromstring(patch_text)
                elif hasattr(patchlib, 'PatchSet'):
                    # Some variants may accept the raw text
                    try:
                        pset = patchlib.PatchSet(patch_text)
                    except Exception:
                        pset = patchlib.PatchSet.from_string(patch_text)
                else:
                    pset = None

                if pset is None:
                    raise RuntimeError('python-patch installed but unable to parse patch')

                workspace = get_workspace_root()

                # For dry_run: attempt to validate by applying to a temporary copy of the files
                # involved (python-patch may provide a dry-run flag; try common 'apply' signatures).
                def try_apply(ps, do_apply: bool):
                    # ps.apply may accept different args depending on library version
                    try:
                        # Preferred: ps.apply(root=..., strip=1, dry_run=...)
                        return ps.apply(root=workspace, strip=1, dry_run=(not do_apply))
                    except TypeError:
                        # Fallback: try ps.apply() without kwargs
                        try:
                            return ps.apply()
                        except Exception:
                            # Some versions return None/True/False; treat None as success
                            return True
                    except Exception:
                        return False

                ok = try_apply(pset, do_apply=not dry_run)

                # Build per-file results if possible
                results = []
                try:
                    # patchlib PatchSet may have 'patched_files' or 'items'
                    files = []
                    if hasattr(pset, 'patched_files'):
                        files = list(pset.patched_files)
                    elif hasattr(pset, 'items'):
                        # each item may have target or path
                        for it in pset.items:
                            p = None
                            if hasattr(it, 'target'):
                                p = it.target
                            elif hasattr(it, 'path'):
                                p = it.path
                            elif hasattr(it, 'source'):
                                p = it.source
                            if p:
                                files.append(os.path.join(workspace, p))

                    if not files:
                        # Unknown API — present a generic result
                        if dry_run:
                            return json.dumps({"results": [{"file": "<unknown>", "status": "dry_run_ok"}]})
                        else:
                            return json.dumps({"results": [{"file": "<unknown>", "status": ("applied" if ok else "conflict")} ]})

                    for f in files:
                        # Normalize and validate path
                        try:
                            tp = safe_path(f)
                        except Exception as e:
                            results.append({"file": f, "status": "error", "error": str(e)})
                            continue
                        if dry_run:
                            results.append({"file": tp, "status": "dry_run_ok"})
                        else:
                            # If backup requested, create backup before applying
                            if backup and os.path.exists(tp):
                                bak_name = f"{tp}.bak.{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.bak"
                                shutil.copy2(tp, bak_name)
                            results.append({"file": tp, "status": ("applied" if ok else "conflict")})

                    # If we were in real-apply mode and python-patch didn't actually write, attempt to call apply again
                    if (not dry_run) and ok:
                        # Some python-patch variants perform apply() as part of ps.apply(), but if not,
                        # try to call ps.apply(root=workspace) to ensure the patch is written.
                        try:
                            _ = try_apply(pset, do_apply=True)
                        except Exception:
                            pass

                    return json.dumps({"results": results})
                except Exception:
                    # If anything goes wrong, fall back to manual implementation below
                    pass

            except Exception:
                # Any error with python-patch usage -> fall back to manual parser
                patchlib = None

        # ---------------------------------------------------------------------
        # Fallback: manual parser & applier (existing implementation)
        # ---------------------------------------------------------------------
        lines = patch_text.splitlines()
        i = 0
        results = []

        def parse_hunk_header(hdr: str):
            # header format: @@ -start,count +start,count @@
            parts = hdr.split()
            if len(parts) < 3:
                return None
            a_range = parts[1]  # -start,count
            b_range = parts[2]  # +start,count
            def parse_range(r):
                r = r.lstrip('+-')
                if ',' in r:
                    start, count = r.split(',', 1)
                    return int(start), int(count)
                else:
                    return int(r), 1
            return parse_range(a_range), parse_range(b_range)

        while i < len(lines):
            line = lines[i]
            if line.startswith('--- '):
                # parse file headers
                orig = line[4:]
                i += 1
                if i >= len(lines) or not lines[i].startswith('+++ '):
                    return json.dumps({"error": "Malformed patch: missing +++ header"})
                newh = lines[i][4:]

                # Extract path (strip a/ or b/ prefix if present)
                def extract_path(hdr):
                    p = hdr
                    if hdr.startswith('a/') or hdr.startswith('b/'):
                        p = hdr[2:]
                    return p

                relpath = extract_path(orig)
                try:
                    target_path = safe_path(relpath)
                except Exception as e:
                    results.append({"file": relpath, "status": "error", "error": str(e)})
                    # Skip to next file header
                    i += 1
                    continue

                # Collect hunks
                i += 1
                hunks = []
                while i < len(lines) and not lines[i].startswith('--- '):
                    if lines[i].startswith('@@ '):
                        hdr = lines[i]
                        i += 1
                        hunk_lines = []
                        while i < len(lines) and not (lines[i].startswith('@@ ') or lines[i].startswith('--- ')):
                            hunk_lines.append(lines[i])
                            i += 1
                        hunks.append((hdr, hunk_lines))
                    else:
                        # skip unexpected lines between hunks
                        i += 1

                # Read current content
                try:
                    with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                        curr_lines = f.read().splitlines(keepends=False)
                except FileNotFoundError:
                    curr_lines = []

                out_lines = []
                curr_index = 0  # 0-based index into curr_lines
                conflict = False

                for hdr, hunk_lines in hunks:
                    parsed = parse_hunk_header(hdr)
                    if parsed is None:
                        conflict = True
                        break
                    (a_start, a_count), (b_start, b_count) = parsed
                    # Convert to 0-based index
                    a_start_idx = a_start - 1

                    # Append any lines before this hunk from curr_lines
                    while curr_index < a_start_idx and curr_index < len(curr_lines):
                        out_lines.append(curr_lines[curr_index])
                        curr_index += 1

                    # Now process hunk lines
                    # We will validate context lines (starting with space) against curr_lines
                    temp_index = curr_index
                    for hl in hunk_lines:
                        if not hl:
                            # blank line — treat as context of ''
                            sign = ' '
                            text = ''
                        else:
                            sign = hl[0]
                            text = hl[1:]
                        if sign == ' ':
                            # context: must match curr_lines[temp_index]
                            if temp_index >= len(curr_lines) or curr_lines[temp_index] != text:
                                conflict = True
                                break
                            out_lines.append(text)
                            temp_index += 1
                        elif sign == '-':
                            # removal: ensure matches
                            if temp_index >= len(curr_lines) or curr_lines[temp_index] != text:
                                conflict = True
                                break
                            # skip this line (remove)
                            temp_index += 1
                        elif sign == '+':
                            # addition: add to out_lines
                            out_lines.append(text)
                        else:
                            # unexpected
                            conflict = True
                            break
                    if conflict:
                        break
                    # advance curr_index to temp_index
                    curr_index = temp_index

                # Append any remaining lines
                while curr_index < len(curr_lines):
                    out_lines.append(curr_lines[curr_index])
                    curr_index += 1

                if conflict and not force:
                    results.append({"file": target_path, "status": "conflict"})
                    continue

                # Prepare final content with newlines
                final_content = "\n".join(out_lines)
                if final_content and not final_content.endswith('\n'):
                    final_content += '\n'

                if dry_run:
                    results.append({"file": target_path, "status": "dry_run_ok", "preview_len": len(final_content)})
                else:
                    # Make backup if requested
                    if backup and os.path.exists(target_path):
                        bak_name = f"{target_path}.bak.{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.bak"
                        shutil.copy2(target_path, bak_name)
                    # Atomic write
                    dirn = os.path.dirname(target_path) or '.'
                    fd, tmp_path = tempfile.mkstemp(dir=dirn)
                    os.close(fd)
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        f.write(final_content)
                    # Replace
                    os.replace(tmp_path, target_path)
                    results.append({"file": target_path, "status": "applied"})

            else:
                i += 1

        return json.dumps({"results": results})

    def copy_file(self, source_path: str, destination_path: str) -> str:
        """Copy a file to a new location (preserves metadata).

        Args:
            source_path: Source file path within workspace
            destination_path: Destination file path within workspace

        Returns:
            Success: "Copied {src} to {dst}"
            Error: JSON object with "error" key

        Behavior:
            - Uses shutil.copy2 (preserves metadata: timestamps, permissions)
            - Both paths must be within workspace and not .daignored

        Example:
            copy_file("src/file.txt", "backup/file.txt")
        """
        import shutil
        try:
            src = safe_path(source_path)
            dst = safe_path(destination_path)
            shutil.copy2(src, dst)
            return f"Copied {src} to {dst}"
        except Exception as e:
            return json.dumps({"error": f"Failed to copy file: {str(e)}"})


#====================================================================================================
# HTTP Toolkit
#====================================================================================================

class HttpTool(Toolkit):
    """HTTP fetch toolkit."""

    def __init__(self, **kwargs):
        super().__init__(
            name="http_toolkit",
            tools=[self.fetch],
            **kwargs
        )

    def fetch(self, url: str, method: str = "GET", timeout: int = 10) -> str:
        """Fetch content from HTTP/HTTPS URLs."""
        # Validate URL
        if not (url.startswith("http://") or url.startswith("https://")):
            return "Error: URL must start with http:// or https://"

        # Set safe headers
        headers = {
            "User-Agent": "da_code/1.0 (AI Assistant)",
            "Accept": "text/html,application/json,text/plain,*/*"
        }

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                if method.upper() == "GET":
                    response = client.get(url, headers=headers)
                elif method.upper() == "HEAD":
                    response = client.head(url, headers=headers)
                else:
                    return f"Error: Unsupported HTTP method: {method} (only GET, HEAD allowed)"

            result = f"🌐 HTTP {method.upper()} {url}\n"
            result += f"Status: {response.status_code} {response.reason_phrase}\n\n"

            # Add key response headers
            if response.headers:
                result += "📋 Headers:\n"
                key_headers = ["content-type", "content-length", "server", "last-modified"]
                for header in key_headers:
                    if header in response.headers:
                        result += f"  {header}: {response.headers[header]}\n"
                result += "\n"

            # Add content (for GET only, not HEAD)
            if method.upper() == "GET" and response.content:
                content_type = response.headers.get("content-type", "").lower()

                if "json" in content_type:
                    try:
                        # Pretty print JSON
                        json_data = response.json()
                        formatted_json = json.dumps(json_data, indent=2)
                        result += f"📄 Content (JSON):\n{formatted_json[:1500]}"
                        if len(formatted_json) > 1500:
                            result += "...\n(truncated)"
                    except:
                        result += f"📄 Content:\n{response.text[:1500]}"
                        if len(response.text) > 1500:
                            result += "...\n(truncated)"
                else:
                    # Plain text or HTML
                    result += f"📄 Content:\n{response.text[:1500]}"
                    if len(response.text) > 1500:
                        result += "...\n(truncated)"

            return result

        except httpx.TimeoutException:
            return f"❌ HTTP request timed out after {timeout} seconds"
        except httpx.RequestError as e:
            return f"❌ HTTP request failed: {str(e)}"
        except Exception as e:
            return f"❌ HTTP fetch error: {str(e)}"