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
import subprocess
import os

import logging
logger = logging.getLogger(__name__)

#====================================================================================================
# Utilities
#====================================================================================================

def get_workspace_root() -> str:
    """Get workspace root from environment variable or current directory."""
    return os.getenv('DA_CODE_WORKSPACE_ROOT', os.getcwd())

def within_workspace(path: str) -> bool:
    """Ensure the given path is within the allowed workspace."""
    workspace_root = os.path.abspath(get_workspace_root())
    abs_path = os.path.abspath(path)
    return abs_path == workspace_root or abs_path.startswith(workspace_root + os.sep)

def safe_path(path: str) -> str:
    """Resolve and validate a path inside the workspace."""
    workspace_root = os.path.abspath(get_workspace_root())

    # Handle absolute paths on Windows and Unix
    if os.path.isabs(path):
        abs_path = os.path.abspath(path)
    else:
        # Relative paths are resolved from workspace root
        abs_path = os.path.abspath(os.path.join(workspace_root, path))

    if not within_workspace(abs_path):
        raise ValueError(f"Path {abs_path} is outside workspace {workspace_root}")
    return abs_path

def get_file_emoji(filename: str) -> str:
    """Get emoji for file type"""
    name_lower = filename.lower()
    if name_lower.endswith(('.py', '.pyw')):
        return "🐍"
    elif name_lower.endswith(('.js', '.jsx', '.ts', '.tsx')):
        return "🟨"
    elif name_lower.endswith(('.md', '.markdown')):
        return "📖"
    elif name_lower.endswith(('.json', '.yaml', '.yml', '.toml')):
        return "⚙️"
    elif name_lower.endswith(('.env', '.gitignore', '.dockerignore')):
        return "🔧"
    elif name_lower.endswith(('.txt', '.log')):
        return "📝"
    elif name_lower.endswith(('.sh', '.bash', '.zsh')):
        return "🔸"
    elif name_lower.endswith(('.html', '.htm', '.css')):
        return "🌐"
    elif name_lower.endswith(('.sql', '.db', '.sqlite')):
        return "🗄️"
    elif name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
        return "🖼️"
    else:
        return "📄"


#====================================================================================================
# TODO Toolkit
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
                self.check_exists,
                self.create_todo,
                self.update_todo,
            ],
            **kwargs
        )

    def read_todo(self) -> str:
        """Read current contents of todo.md file.

        Returns:
            Contents of todo.md file or status message
        """
        try:
            if not self.todo_file.exists():
                return "No todo.md file exists in the current directory."

            content = self.todo_file.read_text(encoding='utf-8')
            if not content.strip():
                return "todo.md file exists but is empty."

            return content.strip()

        except Exception as e:
            return f"Error reading todo file: {str(e)}"

    def check_exists(self) -> str:
        """Check if todo.md file exists.

        Returns:
            Status message indicating if file exists and its size
        """
        try:
            exists = self.todo_file.exists()
            if exists:
                size = self.todo_file.stat().st_size
                return f"✅ todo.md exists ({size} bytes)"
            else:
                return "� todo.md does not exist"

        except Exception as e:
            return f"Error checking file existence: {str(e)}"

    def create_todo(self, content: str) -> str:
        """Create or completely replace todo.md file with provided content.

        Args:
            content: Content to write to todo.md file

        Returns:
            Success message
        """
        try:
            # Ensure content follows proper markdown format
            if not content.strip().startswith('# '):
                content = f"# TODO\n\n{content.strip()}"

            self.todo_file.write_text(content.strip() + '\n', encoding='utf-8')
            return f"✅ Created/updated todo.md file"

        except Exception as e:
            return f"Error creating todo file: {str(e)}"

    def update_todo(self, content: str) -> str:
        """Update todo.md file by replacing its contents.

        Args:
            content: New content for the todo.md file

        Returns:
            Success message
        """
        return self.create_todo(content)


#====================================================================================================
# Command Toolkit
#====================================================================================================

class CommandTool(Toolkit):
    """Command execution tool."""

    def __init__(self, **kwargs):
        super().__init__(
            name="command_tool",
            tools=[self.execute_command],
            requires_confirmation_tools=["execute_command"],
            **kwargs
        )

    def execute_command(self, command: str, working_directory: str = None, explanation: str = None) -> str:
        """Execute shell/bash commands with user confirmation.

        Args:
            command: The shell command to execute
            working_directory: Directory to run in (optional)
            explanation: What the command does (optional)

        Returns:
            Command execution result with stdout/stderr
        """
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
                output = f"� Command failed (exit code: {result.returncode})\n"
                if result.stderr:
                    stderr = result.stderr.strip()
                    output += f"Error:\n{stderr[:1000]}" + ("...\n(truncated)" if len(stderr) > 1000 else "")
                return output

        except subprocess.TimeoutExpired:
            return "� Command timed out after 5 minutes"
        except Exception as e:
            return f"� Command execution failed: {str(e)}"


#====================================================================================================
# Web Search Toolkit
#====================================================================================================

class WebSearchTool(Toolkit):
    """Web search toolkit using DuckDuckGo."""

    def __init__(self, **kwargs):
        super().__init__(
            name="web_search",
            tools=[self.search],
            requires_confirmation_tools=["search"],
            **kwargs
        )

    def search(self, query: str, num_results: int = 5) -> str:
        """Search web using DuckDuckGo.

        Args:
            query: Search terms
            num_results: Number of results to return (default: 5)

        Returns:
            Search results with instant answers, related topics, and source links
        """
        try:
            import urllib.parse

            result = f"� Search results for: {query}\n\n"

            try:
                # Primary: DuckDuckGo instant answers
                encoded_query = urllib.parse.quote(query)
                url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_redirect=1&no_html=1"

                with httpx.Client(timeout=10) as client:
                    response = client.get(url)

                if response.status_code == 200:
                    data = response.json()

                    # Add instant answer if available
                    if data.get("AbstractText"):
                        result += f"📖 Summary: {data['AbstractText']}\n"
                        if data.get("AbstractURL"):
                            result += f"   Source: {data['AbstractURL']}\n\n"

                    # Add related topics
                    if data.get("RelatedTopics"):
                        result += "🔗 Related topics:\n"
                        for i, topic in enumerate(data["RelatedTopics"][:num_results]):
                            if isinstance(topic, dict) and topic.get("Text"):
                                result += f"{i+1}. {topic['Text'][:200]}...\n"
                                if topic.get("FirstURL"):
                                    result += f"   Source: {topic['FirstURL']}\n"
                        result += "\n"

                    # Add definition if available
                    if data.get("Definition"):
                        result += f"📚 Definition: {data['Definition']}\n"
                        if data.get("DefinitionURL"):
                            result += f"   Source: {data['DefinitionURL']}\n\n"

                    # Add answer if available
                    if data.get("Answer"):
                        result += f"💡 Answer: {data['Answer']}\n"
                        if data.get("AnswerType"):
                            result += f"   Type: {data['AnswerType']}\n\n"

                    # Check if we got meaningful results
                    if len(result) > 100:  # More than just the header
                        return result
                    else:
                        # Fallback: provide helpful search suggestion
                        return f"� Search: {query}\n\nNo instant results available. This query might work better with:\n• More specific terms\n• Different keywords\n• Academic or technical search engines\n\nNote: This tool provides instant answers and definitions. For general web results, consider using a browser."

                else:
                    return f"� Search: {query}\n\n� Search service unavailable (status {response.status_code})"

            except Exception as e:
                return f"� Search: {query}\n\n� Search error: {str(e)}\n\nNote: This tool provides instant answers and definitions from DuckDuckGo's API."

        except Exception as e:
            return f"Web search error: {str(e)}"


#====================================================================================================
# File Toolkit
#====================================================================================================

class FileTool(Toolkit):
    """File operations tool with separate methods for each operation."""

    def __init__(self, **kwargs):
        super().__init__(
            name="file_tool",
            tools=[
                self.list_directory,
                self.read_file,
                self.write_file,
                self.create_file,
                self.delete_file,
                self.search_files,
                self.replace_text,
                self.copy_file,
                self.move_file,
            ],
            **kwargs
        )

    def list_directory(self, path: str = ".", max_depth: int = 1, show_hidden: bool = False) -> str:
        """List directory contents with emoji file types.

        Args:
            path: Directory path to list (default: current directory)
            max_depth: Maximum recursion depth for subdirectories (default: 1)
            show_hidden: Include hidden files (default: False)

        Returns:
            JSON string with directory listing including file types, sizes, and emojis
        """
        try:
            path = safe_path(path)
        except Exception as e:
            return json.dumps({"error": f"Invalid path: {str(e)}"})

        def list_dir_recursive(dir_path, current_depth=0):
            """Recursively list directory contents"""
            items = []
            if current_depth >= max_depth:
                return items

            try:
                for item in sorted(Path(dir_path).iterdir()):
                    # Skip hidden files unless requested
                    if not show_hidden and item.name.startswith('.') and item.name not in {'.env', '.gitignore'}:
                        continue

                    # Skip common ignored directories
                    if item.name in {'.git', '__pycache__', '.vscode', 'node_modules'}:
                        continue

                    rel_path = os.path.relpath(item, path)
                    if item.is_dir():
                        items.append({
                            "name": rel_path + "/",
                            "type": "directory",
                            "emoji": "�",
                            "size": None
                        })
                        # Recursively list subdirectories if depth allows
                        if current_depth + 1 < max_depth:
                            subitems = list_dir_recursive(item, current_depth + 1)
                            items.extend(subitems)
                    else:
                        size = item.stat().st_size
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024*1024:
                            size_str = f"{size//1024}KB"
                        else:
                            size_str = f"{size//(1024*1024)}MB"

                        items.append({
                            "name": rel_path,
                            "type": "file",
                            "emoji": get_file_emoji(item.name),
                            "size": size_str
                        })
            except (OSError, PermissionError) as e:
                return [{"error": f"Cannot access {dir_path}: {str(e)}"}]

            return items

        if not os.path.exists(path):
            return json.dumps({"error": f"Path does not exist: {path}"})

        if not os.path.isdir(path):
            return json.dumps({"error": f"Path is not a directory: {path}"})

        results = list_dir_recursive(path)
        return json.dumps({
            "path": path,
            "items": results,
            "total_items": len(results)
        })

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Read file contents.

        Args:
            path: File path to read
            start_line: Starting line number (default: 1)
            end_line: Ending line number, reads to end if not specified

        Returns:
            File contents as string
        """
        path = safe_path(path)
        with open(path, "r", encoding='utf-8', errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[start_line-1:end_line]) if end_line else "".join(lines[start_line-1:])

    def write_file(self, path: str, content: str) -> str:
        """Write or overwrite a file with content.

        Args:
            path: File path to write
            content: Content to write to the file

        Returns:
            Success message with file path and size
        """
        path = safe_path(path)

        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Write the file
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return json.dumps({"error": f"Failed to write file: {str(e)}"})

        file_exists_msg = "Updated" if os.path.exists(path) else "Created"
        return f"{file_exists_msg} file: {path} ({len(content)} bytes)"

    def create_file(self, path: str, content: str = "") -> str:
        """Create a new file (fails if file already exists).

        Args:
            path: File path to create
            content: Initial content for the file (default: empty string)

        Returns:
            Success message or error if file exists
        """
        path = safe_path(path)

        # Check if file already exists
        if os.path.exists(path):
            return json.dumps({"error": f"File already exists: {path}. Use write_file to overwrite."})

        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Create the file
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return json.dumps({"error": f"Failed to write file: {str(e)}"})

        return f"Created file: {path} ({len(content)} bytes)"

    def delete_file(self, path: str) -> str:
        """Delete a file.

        Args:
            path: File path to delete

        Returns:
            Success message or error
        """
        path = safe_path(path)

        if not os.path.exists(path):
            return json.dumps({"error": f"File does not exist: {path}"})

        if os.path.isdir(path):
            return json.dumps({"error": f"Cannot delete directory: {path}. This operation only deletes files."})

        try:
            os.remove(path)
            return f"Deleted file: {path}"
        except Exception as e:
            return json.dumps({"error": f"Failed to delete file: {str(e)}"})

    def search_files(self, pattern: str = "**/*", content: Optional[str] = None, max_results: int = 50) -> str:
        """Search for files by pattern and/or content.

        Args:
            pattern: Glob pattern for file matching (default: all files)
            content: Text content to search for in files (optional)
            max_results: Maximum number of results to return (default: 50)

        Returns:
            JSON string with search results including file paths, line numbers, and matches
        """
        import glob
        results = []

        # Build a glob rooted at the workspace to avoid expanding outside the project root
        root = get_workspace_root()
        search_pattern = os.path.join(root, pattern)
        for file_path in glob.glob(search_pattern, recursive=True):
            if os.path.isfile(file_path):
                if content:
                    try:
                        with open(file_path, "r", errors="ignore") as f:
                            for i, line in enumerate(f, start=1):
                                if content in line:
                                    results.append({"file": file_path, "line": i, "text": line.strip()})
                                    if len(results) >= max_results:
                                        return json.dumps(results)
                    except Exception as e:
                        results.append({"file": file_path, "error": str(e)})
                else:
                    results.append({"file": file_path, "size": os.path.getsize(file_path)})
                    if len(results) >= max_results:
                        return json.dumps(results)
        return json.dumps(results)

    def replace_text(self, path: str, search_text: str, replace_text: str,
                     use_regex: bool = False, case_sensitive: bool = True) -> str:
        """Replace text in a file.

        Args:
            path: File path to modify
            search_text: Text to search for
            replace_text: Text to replace with
            use_regex: Use regular expression for search (default: False)
            case_sensitive: Case-sensitive search (default: True)

        Returns:
            Success message with number of replacements
        """
        import re
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

        with open(path, "w", encoding='utf-8') as f:
            f.write(new_content)

        return f"Replaced {count} occurrence(s) in {path}"

    def copy_file(self, source_path: str, destination_path: str) -> str:
        """Copy a file to a new location.

        Args:
            source_path: Source file path
            destination_path: Destination file path

        Returns:
            Success message with source and destination paths
        """
        import shutil
        try:
            src = safe_path(source_path)
            dst = safe_path(destination_path)
            shutil.copy2(src, dst)
            return f"Copied {src} to {dst}"
        except Exception as e:
            return json.dumps({"error": f"Failed to copy file: {str(e)}"})

    def move_file(self, source_path: str, destination_path: str) -> str:
        """Move or rename a file.

        Args:
            source_path: Source file path
            destination_path: Destination file path

        Returns:
            Success message with source and destination paths
        """
        import shutil
        try:
            src = safe_path(source_path)
            dst = safe_path(destination_path)
            shutil.move(src, dst)
            return f"Moved {src} to {dst}"
        except Exception as e:
            return json.dumps({"error": f"Failed to move file: {str(e)}"})


#====================================================================================================
# Time Toolkit
#====================================================================================================

class TimeTool(Toolkit):
    """Time operations toolkit."""

    def __init__(self, **kwargs):
        super().__init__(
            name="time_toolkit",
            tools=[
                self.current_time,
            ],
            **kwargs
        )

    def current_time(self, format: str = "iso") -> str:
        """Get current time in various formats.

        Args:
            format: Time format - iso, human, timestamp, date, time, or custom strftime

        Returns:
            Formatted current time
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        if format == "iso":
            return now.isoformat()
        elif format == "human":
            return now.strftime("%B %d, %Y %I:%M %p UTC")
        elif format == "timestamp":
            return str(int(now.timestamp()))
        elif format == "date":
            return now.strftime("%Y-%m-%d")
        elif format == "time":
            return now.strftime("%H:%M:%S")
        else:
            # Custom strftime format
            try:
                return now.strftime(format)
            except:
                return f"Invalid time format: {format}"


#====================================================================================================
# Python Toolkit
#====================================================================================================

class PythonTool(Toolkit):
    """Python code execution toolkit."""

    def __init__(self, **kwargs):
        super().__init__(
            name="python_toolkit",
            tools=[
                self.execute_code,
            ],
            **kwargs
        )

    def execute_code(self, code: str, timeout: int = 30) -> str:
        """Execute Python code safely with timeout.

        Args:
            code: Python code to execute
            timeout: Timeout in seconds (default: 30, max: 300)

        Returns:
            Execution result with stdout/stderr or error message
        """
        import sys
        import io
        import threading

        # Capture output
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Use threading for timeout (cross-platform)
        execution_complete = threading.Event()
        execution_error = None
        stdout_result = ""
        stderr_result = ""

        def execute_with_timeout():
            nonlocal execution_error, stdout_result, stderr_result
            try:
                # Redirect output
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture

                # Execute code
                exec(code)

                # Get results
                stdout_result = stdout_capture.getvalue()
                stderr_result = stderr_capture.getvalue()

            except Exception as e:
                execution_error = e
            finally:
                execution_complete.set()

        try:
            # Start execution in thread
            exec_thread = threading.Thread(target=execute_with_timeout)
            exec_thread.daemon = True
            exec_thread.start()

            # Wait for completion or timeout
            if execution_complete.wait(timeout):
                if execution_error:
                    raise execution_error

                result = "✅ Python code executed successfully\n"
                if stdout_result:
                    result += f"Output:\n{stdout_result}"
                if stderr_result:
                    result += f"Errors:\n{stderr_result}"
                if not stdout_result and not stderr_result:
                    result += "No output"

                return result
            else:
                return f"� Code execution timed out after {timeout} seconds"

        except Exception as e:
            return f"� Python execution error: {str(e)}"
        finally:
            # Restore output
            sys.stdout = old_stdout
            sys.stderr = old_stderr


#====================================================================================================
# Git Toolkit
#====================================================================================================

class GitTool(Toolkit):
    """Git operations toolkit."""

    def __init__(self, **kwargs):
        super().__init__(
            name="git_toolkit",
            tools=[
                self.status,
                self.diff,
                self.log,
                self.branch,
                self.commit,
            ],
            **kwargs
        )

    def status(self) -> str:
        """Show git status.

        Returns:
            Git status output or clean working directory message
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30
            )
        except Exception as e:
            return f"� Git status failed: {str(e)}"
        if result.returncode == 0:
            if result.stdout:
                return f"📋 Git Status:\n{result.stdout}"
            else:
                return "✅ Working directory clean"
        else:
            return f"� Git status failed: {result.stderr}"

    def diff(self, files: Optional[List[str]] = None) -> str:
        """Show git diff.

        Args:
            files: Specific files to diff (optional)

        Returns:
            Git diff output
        """
        cmd = ["git", "diff"]
        if files:
            cmd.extend(files)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as e:
            return f"� Git diff failed: {str(e)}"

        if result.returncode == 0:
            if result.stdout:
                output = result.stdout
                return f"� Git Diff:\n{output[:2000]}" + ("...\n(truncated)" if len(output) > 2000 else "")
            else:
                return "No changes to show"
        else:
            return f"� Git diff failed: {result.stderr}"

    def log(self, limit: int = 10) -> str:
        """Show git log.

        Args:
            limit: Number of log entries to show (default: 10)

        Returns:
            Git log output
        """
        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={limit}", "--oneline"],
                capture_output=True,
                text=True,
                timeout=30
            )
        except Exception as e:
            return f"� Git log failed: {str(e)}"

        if result.returncode == 0:
            return f"📜 Recent Commits:\n{result.stdout}"
        else:
            return f"� Git log failed: {result.stderr}"

    def branch(self, branch_name: str = None) -> str:
        """Show current branch or create new branch.

        Args:
            branch_name: Branch name to create (optional)

        Returns:
            Current branch name or branch creation result
        """
        try:
            if branch_name:
                result = subprocess.run(
                    ["git", "checkout", "-b", branch_name],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    return f"✅ Created and switched to branch: {branch_name}"
                else:
                    return f"� Branch creation failed: {result.stderr}"
            else:
                result = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    return f"🌿 Current branch: {result.stdout.strip()}"
                else:
                    return f"� Branch check failed: {result.stderr}"
        except Exception as e:
            return f"� Branch operation failed: {str(e)}"

    def commit(self, message: str, **kwargs) -> str:
        """Commit changes.

        Args:
            message: Commit message
            **kwargs: Additional arguments (ignored for compatibility)

        Returns:
            Commit result
        """
        try:
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                timeout=30
            )
        except Exception as e:
            return f"� Commit failed: {str(e)}"

        if result.returncode == 0:
            return f"✅ Commit successful: {message}"
        else:
            return f"� Commit failed: {result.stderr}"


#====================================================================================================
# HTTP Toolkit
#====================================================================================================

class HttpTool(Toolkit):
    """HTTP fetch toolkit."""

    def __init__(self, **kwargs):
        super().__init__(
            name="http_toolkit",
            tools=[
                self.fetch,
            ],
            **kwargs
        )

    def fetch(self, url: str, method: str = "GET", timeout: int = 10) -> str:
        """Fetch content from HTTP/HTTPS URLs.

        Args:
            url: URL to fetch
            method: HTTP method - GET or HEAD (default: GET)
            timeout: Request timeout in seconds (default: 10)

        Returns:
            HTTP response with status, headers, and content
        """
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

            result = f"� HTTP {method.upper()} {url}\n"
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
            return f"� HTTP request timed out after {timeout} seconds"
        except httpx.RequestError as e:
            return f"� HTTP request failed: {str(e)}"
        except Exception as e:
            return f"� HTTP fetch error: {str(e)}"
