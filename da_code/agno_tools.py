import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Union, Literal
import httpx
from pathlib import Path
from agno.agent import Agent
from agno.tools import tool
from pydantic import BaseModel, Field, ConfigDict
from .models import (
    AgentConfig, CodeSession, CommandExecution, CommandStatus,
    LLMCall, LLMCallStatus, ToolCall, ToolCallStatus, UserResponse, da_mongo
)
import subprocess
import os

#====================================================================================================
# Pydantics
#====================================================================================================

# Modern Pydantic v2 models for tool parameters
class TodoOperation(BaseModel):
    """Structured parameters for todo operations."""
    model_config = ConfigDict(extra='forbid')

    operation: Literal["read", "exists", "create", "update", "write"] = "read"
    content: Optional[str] = None

class WebSearchParams(BaseModel):
    """Structured parameters for web search."""
    model_config = ConfigDict(extra='forbid')

    query: str = Field(..., description="Search query")
    num_results: int = Field(5, ge=1, le=20, description="Number of results to return")

class FileSearchParams(BaseModel):
    """Structured parameters for file search."""
    model_config = ConfigDict(extra='forbid')

    pattern: str = Field("*", description="Glob pattern for file matching")
    content: Optional[str] = Field(None, description="Text content to search for")
    max_results: int = Field(20, ge=1, le=100, description="Maximum results to return")

class TimeParams(BaseModel):
    """Structured parameters for time operations."""
    model_config = ConfigDict(extra='forbid')

    format: str = Field("iso", description="Time format: iso, human, timestamp, date, time, or custom strftime")
    timezone: str = Field("UTC", description="Timezone (currently only UTC supported)")

class PythonCodeParams(BaseModel):
    """Structured parameters for Python code execution."""
    model_config = ConfigDict(extra='forbid')

    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(30, ge=1, le=300, description="Timeout in seconds (1-300)")

class GitParams(BaseModel):
    """Structured parameters for git operations."""
    model_config = ConfigDict(extra='forbid')

    operation: Literal["status", "commit", "diff", "branch", "log"] = "status"
    message: Optional[str] = Field(None, description="Commit message (required for commit operation)")
    branch_name: Optional[str] = Field(None, description="Branch name for branch operations")
    files: Optional[List[str]] = Field(None, description="Specific files for diff operation")
    limit: int = Field(10, ge=1, le=50, description="Number of log entries to show")


#====================================================================================================
# Tool input handling
#====================================================================================================


def _handle_simple_string(value: str, model_class: type) -> Union[BaseModel, str]:
    """Handle simple string inputs for different model classes."""
    if model_class == TodoOperation:
        return TodoOperation(operation="create", content=value)
    elif model_class == WebSearchParams:
        return WebSearchParams(query=value)
    elif model_class == FileSearchParams:
        return FileSearchParams(pattern=value)
    elif model_class == TimeParams:
        return TimeParams(format=value)
    elif model_class == PythonCodeParams:
        return PythonCodeParams(code=value)
    elif model_class == GitParams:
        return GitParams(operation="status")
    else:
        return f"Invalid input format for {model_class.__name__}"


# Tool factory functions with modern patterns
def _parse_tool_input(tool_input: Union[str, dict], model_class: type) -> Union[BaseModel, str]:
    """Parse and validate tool input using Pydantic models."""
    try:
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)

                # Handle LangChain's __arg1 format
                if "__arg1" in params:
                    arg1_value = params["__arg1"]
                    if isinstance(arg1_value, str):
                        try:
                            # Try to parse __arg1 as JSON
                            actual_params = json.loads(arg1_value)
                            return model_class(**actual_params)
                        except json.JSONDecodeError:
                            # __arg1 is a simple string, handle by model type
                            return _handle_simple_string(arg1_value, model_class)
                    else:
                        # __arg1 is already a dict
                        return model_class(**arg1_value)
                else:
                    # Normal JSON params
                    return model_class(**params)
            except json.JSONDecodeError:
                # Handle simple string inputs
                return _handle_simple_string(tool_input, model_class)
        else:
            # Handle dict input (already parsed)
            if "__arg1" in tool_input:
                arg1_value = tool_input["__arg1"]
                if isinstance(arg1_value, str):
                    try:
                        actual_params = json.loads(arg1_value)
                        return model_class(**actual_params)
                    except json.JSONDecodeError:
                        return _handle_simple_string(arg1_value, model_class)
                else:
                    return model_class(**arg1_value)
            else:
                return model_class(**tool_input)
    except Exception as e:
        return f"Parameter validation error: {str(e)}"

#====================================================================================================
# TODO Tool
#====================================================================================================



class TodoManager:
    """Modern todo.md file manager with async support and structured operations."""

    def __init__(self, working_directory: str = None):
        """Initialize todo manager."""
        self.working_dir = working_directory or os.getcwd()
        self.todo_file = Path(self.working_dir) / "todo.md"

    def read_todo_file(self) -> str:
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

    def file_exists(self) -> str:
        """Check if todo.md file exists."""
        try:
            exists = self.todo_file.exists()
            if exists:
                size = self.todo_file.stat().st_size
                return f"✅ todo.md exists ({size} bytes)"
            else:
                return "❌ todo.md does not exist"

        except Exception as e:
            return f"Error checking file existence: {str(e)}"

    def create_todo_file(self, content: str) -> str:
        """Create or completely replace todo.md file with provided content."""
        try:
            # Ensure content follows proper markdown format
            if not content.strip().startswith('# '):
                content = f"# TODO\n\n{content.strip()}"

            self.todo_file.write_text(content.strip() + '\n', encoding='utf-8')
            return f"✅ Created/updated todo.md file"

        except Exception as e:
            return f"Error creating todo file: {str(e)}"

    def update_todo_file(self, new_content: str) -> str:
        """Update todo.md file by replacing its contents."""
        return self.create_todo_file(new_content)

working_directory = os.getcwd()
todo_manager = TodoManager(working_directory)

@tool(
    name="todo_file_manager",
    description="Manage todo.md file with structured operations and modern validation.",
    instructions="""
SUPPORTED FORMATS:
  - JSON: {"operation": "read"} or {"operation": "create", "content": "..."}

OPERATIONS:
  - read/get/show: Read current todo.md contents
  - exists/check: Check if todo.md file exists
  - create/update/write: Create or replace todo.md with content

EXAMPLE INPUTS:
  - {"operation": "read"}
  - {"operation": "create", "content": "# TODO\n\n- [ ] New task"}
  - "Quick todo item"
 
TODO FORMAT: Use markdown with - [ ] for tasks, - [x] for completed items
    """
)
def handle_todo_operation(tool_input: str) -> str:
    """Handle todo.md file operations with structured validation."""
    params = _parse_tool_input(tool_input, TodoOperation)
    if isinstance(params, str):
        return params

    try:
        if params.operation in ["read", "get", "show"]:
            return todo_manager.read_todo_file()
        elif params.operation in ["exists", "check"]:
            return todo_manager.file_exists()
        elif params.operation in ["create", "update", "write"]:
            if not params.content:
                return "Error: content parameter is required for create/update operations"
            return todo_manager.create_todo_file(params.content)
        else:
            return f"Error: Unsupported operation '{params.operation}'"
    except Exception as e:
        return f"Todo operation error: {str(e)}"



#====================================================================================================
# Command Tool
#====================================================================================================


@tool(
    name="shell_command",
    description="Execute shell/bash commands with user confirmation",
    requires_confirmation=True,
    instructions="""
Input should be a JSON string with:
- command: The command to execute (required)
- explanation: Brief explanation of what the command does (optional)
- reasoning: Why this command is needed (optional)
- working_directory: Directory to run command in (optional)
- related_files: List of files this command affects (optional)

Example: {"command": "ls -la", "explanation": "List directory contents", "reasoning": "User wants to see files"}

The tool will request user confirmation before executing any command.
"""
)
def execute_command(tool_input: str) -> str:
    """Execute shell commands with user confirmation."""
    try:
        # Parse command input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
            except json.JSONDecodeError:
                # Simple string command
                params = {"command": tool_input}
        else:
            params = tool_input

        command = params.get("command")
        if not command:
            return "Error: No command specified"

        working_dir = params.get("working_directory", os.getcwd())

        start_time = time.time()
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=300
        )

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
        return "⏰ Command timed out after 5 minutes"
    except Exception as e:
        return f"❌ Command execution failed: {str(e)}"


#====================================================================================================
# Web Search Tool
#====================================================================================================

@tool(
    name="web_search",
    description="Search the web for current information using DuckDuckGo with user confirmation",
    requires_confirmation=True,
    instructions="""
SUPPORTED FORMATS:
- JSON: {"query": "search terms", "num_results": 5}
- Simple text: "search terms"

EXAMPLE INPUTS:
- {"query": "Python asyncio tutorial", "num_results": 3}
- "latest AI news 2025"
- {"query": "pydantic validation examples"}

Returns: Instant answers, related topics, and source links.
"""
)
def web_search(tool_input: str) -> str:
    """Search the web for current information."""
    try:
        # Parse search input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
                query = params.get("query", "")
                num_results = params.get("num_results", 5)
            except json.JSONDecodeError:
                # Simple string query
                query = tool_input
                num_results = 5
        else:
            query = tool_input.get("query", "")
            num_results = tool_input.get("num_results", 5)

        if not query:
            return "Error: No search query specified"

        # Enhanced web search with multiple fallbacks
        import httpx
        import urllib.parse

        result = f"🔍 Search results for: {query}\n\n"

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
                    return f"🔍 Search: {query}\n\nNo instant results available. This query might work better with:\n• More specific terms\n• Different keywords\n• Academic or technical search engines\n\nNote: This tool provides instant answers and definitions. For general web results, consider using a browser."

            else:
                return f"🔍 Search: {query}\n\n❌ Search service unavailable (status {response.status_code})"

        except Exception as e:
            return f"🔍 Search: {query}\n\n❌ Search error: {str(e)}\n\nNote: This tool provides instant answers and definitions from DuckDuckGo's API."

    except Exception as e:
        return f"Web search error: {str(e)}"


#====================================================================================================
# File Search Tool
#====================================================================================================

@tool(
    name="file_search",
    description="Search for files by pattern and/or content",
    instructions="""
SUPPORTED FORMATS:
- JSON: {"pattern": "*.py", "content": "async def", "max_results": 10}
- Simple text: "*.py" (pattern only)

SEARCH TYPES:
1. Pattern only: Find files matching glob pattern
2. Content only: Find files containing text
3. Combined: Both pattern and content filters

EXAMPLE INPUTS:
- {"pattern": "**/*.py", "max_results": 15}
- {"content": "AsyncAgent", "max_results": 5}
- {"pattern": "*.md", "content": "TODO"}
- "requirements.txt"

Returns: File paths with sizes and line numbers for content matches.
"""
)
def file_search(tool_input: str) -> str:
    """Search for files by pattern and/or content."""
    try:
        # Parse search input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
                pattern = params.get("pattern", "*")
                content = params.get("content")
                max_results = params.get("max_results", 20)
            except json.JSONDecodeError:
                # Simple string pattern
                pattern = tool_input
                content = None
                max_results = 20
        else:
            pattern = tool_input.get("pattern", "*")
            content = tool_input.get("content")
            max_results = tool_input.get("max_results", 20)

        import glob
        from pathlib import Path

        results = []

        # Find files by pattern
        if pattern:
            files = glob.glob(pattern, recursive=True)
            files = [f for f in files if Path(f).is_file()][:max_results]
        else:
            files = []

        # If content search specified, filter by content
        if content and files:
            content_matches = []
            for file_path in files:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                        matching_lines = []
                        for i, line in enumerate(lines, 1):
                            if content.lower() in line.lower():
                                matching_lines.append((i, line.strip()[:100]))

                        if matching_lines:
                            file_size = Path(file_path).stat().st_size
                            content_matches.append({
                                'path': file_path,
                                'size': file_size,
                                'matches': matching_lines[:5]  # Limit matches per file
                            })
                except Exception:
                    continue

            if content_matches:
                result = f"📁 Files containing '{content}':\n\n"
                for match in content_matches[:max_results]:
                    result += f"📄 {match['path']} ({match['size']} bytes)\n"
                    for line_num, line_content in match['matches']:
                        result += f"   Line {line_num}: {line_content}\n"
                    result += "\n"
                return result
            else:
                return f"No files found containing '{content}'"

        elif files:
            # Pattern-only search
            result = f"📁 Files matching '{pattern}':\n\n"
            for file_path in files:
                try:
                    file_size = Path(file_path).stat().st_size
                    result += f"📄 {file_path} ({file_size} bytes)\n"
                except Exception:
                    result += f"📄 {file_path}\n"
            return result
        else:
            return f"No files found matching pattern: {pattern}"

    except Exception as e:
        return f"File search error: {str(e)}"


#====================================================================================================
# Time Tool
#====================================================================================================

@tool(
    name="current_time",
    description="Get current time in various formats",
    instructions="""
SUPPORTED FORMATS:
- JSON: {"format": "iso", "timezone": "UTC"}
- Simple text: "iso" or "human" or "timestamp"

FORMATS:
- iso: ISO 8601 format (2025-01-15T10:30:00Z)
- human: Human readable (January 15, 2025 10:30 AM UTC)
- timestamp: Unix timestamp (1737889800)
- date: Date only (2025-01-15)
- time: Time only (10:30:00)

EXAMPLE INPUTS:
- {"format": "human"}
- "iso"
- {"format": "timestamp"}
"""
)
def current_time(tool_input: str = "iso") -> str:
    """Get current time in various formats."""
    try:
        # Parse time input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
                format_type = params.get("format", "iso")
            except json.JSONDecodeError:
                # Simple string format
                format_type = tool_input
        else:
            format_type = tool_input.get("format", "iso")

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        if format_type == "iso":
            return now.isoformat()
        elif format_type == "human":
            return now.strftime("%B %d, %Y %I:%M %p UTC")
        elif format_type == "timestamp":
            return str(int(now.timestamp()))
        elif format_type == "date":
            return now.strftime("%Y-%m-%d")
        elif format_type == "time":
            return now.strftime("%H:%M:%S")
        else:
            # Custom strftime format
            try:
                return now.strftime(format_type)
            except:
                return f"Invalid time format: {format_type}"

    except Exception as e:
        return f"Time error: {str(e)}"


#====================================================================================================
# Python Code Execution Tool
#====================================================================================================

@tool(
    name="python_executor",
    description="Execute Python code safely with timeout",
    instructions="""
SUPPORTED FORMATS:
- JSON: {"code": "print('hello')", "timeout": 30}
- Simple text: Python code directly

EXAMPLE INPUTS:
- {"code": "import math; print(math.pi)", "timeout": 10}
- "print('Hello World')"
- {"code": "x = [1,2,3]; print(sum(x))"}

SECURITY: Runs in current Python context with 30 second timeout.
"""
)
def python_executor(tool_input: str) -> str:
    """Execute Python code safely with timeout."""
    try:
        # Parse code input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
                code = params.get("code", "")
                timeout = params.get("timeout", 30)
            except json.JSONDecodeError:
                # Simple string code
                code = tool_input
                timeout = 30
        else:
            code = tool_input.get("code", "")
            timeout = tool_input.get("timeout", 30)

        if not code:
            return "Error: No Python code specified"

        import sys
        import io
        import threading
        import time

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
                return f"⏰ Code execution timed out after {timeout} seconds"

        except Exception as e:
            return f"❌ Python execution error: {str(e)}"
        finally:
            # Restore output
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    except Exception as e:
        return f"Python executor error: {str(e)}"


#====================================================================================================
# Git Tool
#====================================================================================================

@tool(
    name="git_operations",
    description="Perform git operations like status, commit, diff, branch, log",
    instructions="""
SUPPORTED FORMATS:
- JSON: {"operation": "status"} or {"operation": "commit", "message": "fix bug"}
- Simple text: "status" or "commit" or "diff"

OPERATIONS:
- status: Show git status
- commit: Commit changes (requires message)
- diff: Show diff of changes
- branch: Show current branch or create new one
- log: Show recent commits

EXAMPLE INPUTS:
- {"operation": "status"}
- {"operation": "commit", "message": "Add new feature"}
- {"operation": "diff", "files": ["file1.py", "file2.py"]}
- {"operation": "log", "limit": 5}
- "status"
"""
)
def git_operations(tool_input: str) -> str:
    """Perform git operations."""
    try:
        # Parse git input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
                operation = params.get("operation", "status")
                message = params.get("message")
                branch_name = params.get("branch_name")
                files = params.get("files", [])
                limit = params.get("limit", 10)
            except json.JSONDecodeError:
                # Simple string operation
                operation = tool_input
                message = None
                branch_name = None
                files = []
                limit = 10
        else:
            operation = tool_input.get("operation", "status")
            message = tool_input.get("message")
            branch_name = tool_input.get("branch_name")
            files = tool_input.get("files", [])
            limit = tool_input.get("limit", 10)

        import subprocess

        def run_git_cmd(cmd_args):
            result = subprocess.run(
                ["git"] + cmd_args,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result

        if operation == "status":
            result = run_git_cmd(["status", "--porcelain"])
            if result.returncode == 0:
                if result.stdout:
                    return f"📋 Git Status:\n{result.stdout}"
                else:
                    return "✅ Working directory clean"
            else:
                return f"❌ Git status failed: {result.stderr}"

        elif operation == "diff":
            if files:
                cmd = ["diff"] + files
            else:
                cmd = ["diff"]
            result = run_git_cmd(cmd)
            if result.returncode == 0:
                if result.stdout:
                    return f"📝 Git Diff:\n{result.stdout[:2000]}" + ("...\n(truncated)" if len(result.stdout) > 2000 else "")
                else:
                    return "No changes to show"
            else:
                return f"❌ Git diff failed: {result.stderr}"

        elif operation == "log":
            result = run_git_cmd(["log", f"--max-count={limit}", "--oneline"])
            if result.returncode == 0:
                return f"📜 Recent Commits:\n{result.stdout}"
            else:
                return f"❌ Git log failed: {result.stderr}"

        elif operation == "branch":
            if branch_name:
                result = run_git_cmd(["checkout", "-b", branch_name])
                if result.returncode == 0:
                    return f"✅ Created and switched to branch: {branch_name}"
                else:
                    return f"❌ Branch creation failed: {result.stderr}"
            else:
                result = run_git_cmd(["branch", "--show-current"])
                if result.returncode == 0:
                    return f"🌿 Current branch: {result.stdout.strip()}"
                else:
                    return f"❌ Branch check failed: {result.stderr}"

        elif operation == "commit":
            if not message:
                return "Error: Commit message required for commit operation"
            result = run_git_cmd(["commit", "-m", message])
            if result.returncode == 0:
                return f"✅ Commit successful: {message}"
            else:
                return f"❌ Commit failed: {result.stderr}"
        else:
            return f"❌ Unsupported git operation: {operation}"

    except Exception as e:
        return f"Git operations error: {str(e)}"


#====================================================================================================
# HTTP Fetch Tool
#====================================================================================================

@tool(
    name="http_fetch",
    description="Fetch content from HTTP/HTTPS URLs",
    instructions="""
SUPPORTED FORMATS:
- JSON: {"url": "https://example.com", "method": "GET", "timeout": 10}
- Simple text: "https://example.com" (GET request)

METHODS:
- GET: Fetch content from URL (default)
- HEAD: Get headers only

EXAMPLE INPUTS:
- {"url": "https://api.github.com/repos/python/cpython"}
- "https://httpbin.org/json"
- {"url": "https://api.example.com", "method": "HEAD"}

Returns: HTTP status, headers, and content (formatted JSON or text).
"""
)
def http_fetch(tool_input: str) -> str:
    """Fetch content from HTTP/HTTPS URLs."""
    try:
        # Parse fetch input
        if isinstance(tool_input, str):
            try:
                params = json.loads(tool_input)
                url = params.get("url", "")
                method = params.get("method", "GET").upper()
                timeout = params.get("timeout", 10)
            except json.JSONDecodeError:
                # Simple string URL
                url = tool_input
                method = "GET"
                timeout = 10
        else:
            url = tool_input.get("url", "")
            method = tool_input.get("method", "GET").upper()
            timeout = tool_input.get("timeout", 10)

        if not url:
            return "Error: No URL specified"

        # Validate URL
        if not (url.startswith("http://") or url.startswith("https://")):
            return "Error: URL must start with http:// or https://"

        # Set safe headers
        headers = {
            "User-Agent": "da_code/1.0 (AI Assistant)",
            "Accept": "text/html,application/json,text/plain,*/*"
        }

        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if method == "GET":
                response = client.get(url, headers=headers)
            elif method == "HEAD":
                response = client.head(url, headers=headers)
            else:
                return f"Error: Unsupported HTTP method: {method} (only GET, HEAD allowed)"

        result = f"🌐 HTTP {method} {url}\n"
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
        if method == "GET" and response.content:
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
        return f"⏰ HTTP request timed out after {timeout} seconds"
    except httpx.RequestError as e:
        return f"❌ HTTP request failed: {str(e)}"
    except Exception as e:
        return f"❌ HTTP fetch error: {str(e)}"