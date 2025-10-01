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

working_directory = Path(os.getcwd()) / "todo.md"
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
    description="Execute shell/bash commands with automatic user confirmation",
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
async def execute_command(session: CodeSession, execution: CommandExecution) -> str:
    """Execute an approved command."""
    

    try:
        execution.update_status(CommandStatus.APPROVED)
        start_time = time.time()

        result = subprocess.run(
            execution.command,
            shell=True,
            cwd=execution.working_directory,
            capture_output=True,
            text=True,
            timeout=300
        )

        execution.exit_code = result.returncode
        execution.stdout = result.stdout
        execution.stderr = result.stderr
        execution.execution_time = time.time() - start_time

        if result.returncode == 0:
            execution.update_status(CommandStatus.SUCCESS)
            session.add_execution(execution)

            output = f"✅ Command executed successfully\n"
            if result.stdout:
                stdout = result.stdout.strip()
                output += f"Output:\n{stdout[:2000]}" + ("...\n(truncated)" if len(stdout) > 2000 else "")
            else:
                output += "No output"
            return output
        else:
            execution.update_status(CommandStatus.FAILED)
            session.add_execution(execution)

            output = f"❌ Command failed (exit code: {result.returncode})\n"
            if result.stderr:
                stderr = result.stderr.strip()
                output += f"Error:\n{stderr[:1000]}" + ("...\n(truncated)" if len(stderr) > 1000 else "")
            return output

    except subprocess.TimeoutExpired:
        execution.update_status(CommandStatus.TIMEOUT)
        session.add_execution(execution)
        return "⏰ Command timed out after 5 minutes"
    except Exception as e:
        execution.update_status(CommandStatus.FAILED)
        execution.stderr = str(e)
        session.add_execution(execution)
        return f"❌ Command execution failed: {str(e)}"