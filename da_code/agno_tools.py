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
logger = logging.getLogger(__name__)

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
        logger.warning(f"🔧 SHELL_COMMAND TOOL CALLED with command: {command}")

        try:
            working_dir = working_directory or os.getcwd()

            logger.warning(f"🔧 EXECUTING COMMAND: {command} in {working_dir}")
            start_time = time.time()
            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=300
            )

            logger.warning(f"🔧 COMMAND RESULT: returncode={result.returncode}, stdout_len={len(result.stdout) if result.stdout else 0}")

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
                self.replace_text,
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