"""Pydantic models and session tracking for da_code CLI tool."""
from pathlib import Path
env_file = Path('.env')
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file, override=False)

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Annotated, Dict, List, Optional, Union, Callable

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient


from bson import ObjectId
from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    PlainSerializer,
    AfterValidator,
    WithJsonSchema,
    field_validator
)
logger = logging.getLogger(__name__)


# Removed CommandConfirmationNeeded - using pure generator pattern now


def validate_object_id(v: Any) -> ObjectId:
    if isinstance(v, ObjectId):
        return v
    if ObjectId.is_valid(v):
        return ObjectId(v)
    raise ValueError("Invalid ObjectId")

PyObjectId = Annotated[
    Union[str, ObjectId],
    AfterValidator(validate_object_id),
    PlainSerializer(lambda x: str(x), return_type=str),
    WithJsonSchema({"type": "string"}, mode="serialization"),
]


class CommandStatus(str, Enum):
    """Status of command execution."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class UserResponse(str, Enum):
    """User response to command confirmation."""
    YES = "yes"
    EDIT = "edit"
    REPROMPT = "reprompt"


class LLMCallStatus(str, Enum):
    """Status of LLM call."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ToolCallStatus(str, Enum):
    """Status of tool/MCP call."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class StatusType(str, Enum):
    """Status message types for live interface."""
    INFO = "info"
    WORKING = "working"
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


class CommandExecution(BaseModel):
    """Model for individual command execution tracking."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True,
        populate_by_name=True
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Command details
    command: str = Field(..., description="Shell command to execute")
    tool_name: Optional[str] = Field(None, description="Name of the tool being executed")
    explanation: Optional[str] = Field(None, description="Agent explanation of what command does")
    working_directory: str = Field("/tmp", description="Working directory for command execution")

    # User interaction
    user_prompt: Optional[str] = Field(None, description="Prompt shown to user for confirmation")
    user_response: Optional[UserResponse] = Field(None, description="User's response to confirmation")
    user_modifications: Optional[str] = Field(None, description="User modifications to command")

    # Execution tracking
    status: CommandStatus = Field(CommandStatus.PENDING, description="Current status of command")
    exit_code: Optional[int] = Field(None, description="Command exit code")
    stdout: Optional[str] = Field(None, description="Command standard output")
    stderr: Optional[str] = Field(None, description="Command standard error")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    timeout_seconds: int = Field(300, description="Command timeout in seconds")

    # Agent context
    agent_reasoning: Optional[str] = Field(None, description="Agent's reasoning for this command")
    related_files: List[str] = Field(default_factory=list, description="Files related to this command")
    explanation_requested: bool = Field(False, description="Whether user requested explanation for this command")

    def update_status(self, status: CommandStatus) -> None:
        """Update command status and timestamp."""
        self.status = status
        self.updated_at = datetime.now(timezone.utc)

    def set_result(self, exit_code: int, stdout: str, stderr: str, execution_time: float) -> None:
        """Set command execution result."""
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.execution_time = execution_time
        self.status = CommandStatus.SUCCESS if exit_code == 0 else CommandStatus.FAILED
        self.updated_at = datetime.now(timezone.utc)


class ConfirmationRequest(BaseModel):
    """Request for user confirmation during execution."""

    execution: CommandExecution
    choices: list[str] = Field(default=["yes", "no", "modify", "explain"])
    default_choice: str = "no"


class ConfirmationResponse(BaseModel):
    """User response to confirmation request."""

    choice: str
    modified_command: Optional[str] = None
    reprompt_message: Optional[str] = None



class MCPServerInfo(BaseModel):
    """Information about an MCP server."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='allow',
        str_strip_whitespace=True
    )

    name: str = Field(..., description="MCP server name")
    url: str = Field(..., description="MCP server URL")
    description: Optional[str] = Field(None, description="Server description")
    status: str = Field("unknown", description="Server status")
    tools: List[str] = Field(default_factory=list, description="Available tools")


class LLMCall(BaseModel):
    """Model for tracking LLM API calls."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # LLM call details
    model_name: str = Field(..., description="Model name (e.g., gpt-4)")
    provider: str = Field("azure_openai", description="LLM provider")
    prompt: str = Field(..., description="Input prompt sent to LLM")
    response: Optional[str] = Field(None, description="LLM response content")

    # Execution details
    status: LLMCallStatus = Field(LLMCallStatus.PENDING)
    response_time_ms: Optional[float] = Field(None, description="Response time in milliseconds")
    error_message: Optional[str] = Field(None, description="Error message if failed")

    # Usage tracking
    prompt_tokens: Optional[int] = Field(None, description="Input tokens used")
    completion_tokens: Optional[int] = Field(None, description="Output tokens generated")
    total_tokens: Optional[int] = Field(None, description="Total tokens used")
    estimated_cost: Optional[float] = Field(None, description="Estimated cost in USD")


class ToolCall(BaseModel):
    """Model for tracking tool/MCP calls."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Tool call details
    server_name: str = Field(..., description="MCP server name")
    tool_name: str = Field(..., description="Tool name called")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    result: Optional[Dict[str, Any]] = Field(None, description="Tool execution result")

    # Execution details
    status: ToolCallStatus = Field(ToolCallStatus.PENDING)
    response_time_ms: Optional[float] = Field(None, description="Response time in milliseconds")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class ProjectContext(BaseModel):
    """Project context loaded from AGENTS.md."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='allow',
        str_strip_whitespace=True
    )

    project_name: Optional[str] = Field(None, description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    instructions: List[str] = Field(default_factory=list, description="Project instructions as list")
    file_content: str = Field(..., description="Full AGENTS.md content")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



class FileChange(BaseModel):
    """Represents a single file change event."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True
    )

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = Field(..., description="Type of event: created, modified, deleted, moved")
    path: str = Field(..., description="Absolute path to the file")
    relative_path: str = Field(..., description="Path relative to project root")
    size: Optional[int] = Field(None, description="File size in bytes")
    content_snapshot: Optional[str] = Field(None, description="Content snapshot for small files")
    src_path: Optional[str] = Field(None, description="Source path for 'moved' events")
    source: str = Field("unknown", description="Source of change: agent, user, or external")
    pre_change_snapshot: Optional[str] = Field(None, description="Content before agent modification")



class AgentConfig(BaseModel):
    """Configuration for multi-framework agents."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True
    )

    # Azure OpenAI configuration
    azure_endpoint: str = Field(..., description="Azure OpenAI endpoint")
    api_key: str = Field(..., description="Azure OpenAI API key")
    api_version: str = Field("2023-12-01-preview", description="Azure OpenAI API version")
    deployment_name: str = Field("gpt-4", description="Azure OpenAI deployment name")
    reasoning_deployment: str|None = Field(None, description="Azure OpenAi reasoning model for agent")

    # Agent behavior
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Model temperature")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens per response")
    agent_timeout: Optional[int] = Field(60, description="Request timeout in seconds")
    max_retries: int = Field(2, description="Maximum number of retries")

    # Tool configuration
    command_timeout: int = Field(300, description="Default command timeout in seconds")
    require_confirmation: bool = Field(True, description="Require user confirmation for commands")

    # Framework configuration (LangGraph only)
    # Note: da_code now uses LangGraph exclusively for simplicity and reliability
    # CLI configuration
    history_file_path: str = Field(..., description="Path to command history file")



class FileSnapshot(BaseModel):
    """Snapshot of a single file at a point in time."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True
    )

    relative_path: str = Field(..., description="Path relative to project root")
    content: Optional[str] = Field(None, description="File content (None if too large or binary)")
    size: int = Field(..., description="File size in bytes")
    content_hash: str = Field(..., description="SHA256 hash of file content")
    is_binary: bool = Field(False, description="Whether file is binary")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FileSystemHistory(BaseModel):
    """Tracks file changes during a session with replay/restore capability."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='allow',
        str_strip_whitespace=True
    )

    session_id: str = Field(..., description="Associated session ID")
    project_root: str = Field(..., description="Root directory of the project")
    max_snapshot_size: int = Field(50_000, description="Max file size for content snapshots")
    changes: List[FileChange] = Field(default_factory=list, description="All file changes")
    last_reported_time: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    session_start_snapshot: Dict[str, FileSnapshot] = Field(default_factory=dict, description="Snapshot at session start")

    def get_changes_since_last_prompt(self, peek_only: bool = False) -> Optional[str]:
        """Get a summary of changes since last prompt.

        Args:
            peek_only: If True, only peek at changes without updating last_reported_time.
                      Use this when building context before agent starts to avoid losing
                      changes if agent fails to start.
        """
        from collections import defaultdict

        current_time = datetime.now(timezone.utc).timestamp()
        new_changes = [c for c in self.changes if c.timestamp.timestamp() > self.last_reported_time]

        # Only update timestamp if not peeking (commit happens after agent starts)
        if not peek_only:
            self.last_reported_time = current_time

        if not new_changes:
            return None

        # Group by event type (deduplicate file paths per event type)
        by_type = defaultdict(set)
        for change in new_changes:
            by_type[change.event_type].add(change.relative_path)

        # Format summary
        parts = []
        for event_type in ['created', 'modified', 'deleted', 'moved']:
            if by_type[event_type]:
                file_list = sorted(by_type[event_type])  # Sort for consistent ordering
                files = ', '.join(file_list[:5])
                more = f" (+{len(file_list) - 5} more)" if len(file_list) > 5 else ""
                parts.append(f"{event_type.title()}: {files}{more}")

        return "📁 File changes: " + " | ".join(parts)

    def mark_changes_reported(self) -> None:
        """Commit the timestamp update to mark changes as reported.

        Call this after agent successfully starts to prevent losing changes
        if agent fails to start.
        """
        self.last_reported_time = datetime.now(timezone.utc).timestamp()

    def get_file_history(self, file_path: str) -> List[FileChange]:
        """Get history of changes for a specific file."""
        from pathlib import Path
        path_obj = Path(file_path)

        # Try to get relative path
        try:
            if path_obj.is_absolute():
                relative = str(path_obj.relative_to(self.project_root))
            else:
                relative = str(path_obj)
        except ValueError:
            relative = str(path_obj)

        return [c for c in self.changes if c.relative_path == relative]

    def restore_file_content(self, file_path: str, timestamp: Optional[datetime] = None) -> Optional[str]:
        """Restore file content to a specific point in time."""
        history = self.get_file_history(file_path)

        if not history:
            return None

        # Filter to changes before timestamp
        if timestamp:
            history = [c for c in history if c.timestamp <= timestamp]

        if not history:
            return None

        # Find most recent change with content snapshot
        for change in reversed(history):
            if change.content_snapshot:
                return change.content_snapshot

        return None

    def capture_session_start_snapshot(self, daignore=None, timeout_seconds: int = 10, progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Capture complete snapshot of project directory at session start.

        Respects .daignore rules to avoid snapshotting sensitive/ignored files.

        Args:
            daignore: DaIgnore instance for filtering files (optional)
            timeout_seconds: maximum seconds to spend indexing (default 10s)
            progress_callback: optional callable called with current relative path or status message
        """
        import hashlib
        from pathlib import Path as PathLib
        import time

        logger.info(f"Capturing session-start snapshot for {self.project_root}")
        project_path = PathLib(self.project_root)

        # Common directories to always ignore
        always_ignore = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.da', 'dist', 'build'}

        file_count = 0
        start_time = time.time()
        deadline = start_time + timeout_seconds if timeout_seconds and timeout_seconds > 0 else None

        for item in project_path.rglob('*'):
            # Check timeout early to avoid unnecessary work
            if deadline and time.time() > deadline:
                logger.warning("Snapshot timeout reached; stopping further indexing")
                if progress_callback:
                    try:
                        progress_callback("Snapshot timeout reached; stopping")
                    except Exception:
                        pass
                break

            # Skip directories
            if not item.is_file():
                continue

            # Skip if any parent directory is in always_ignore
            if any(ignored_dir in item.parts for ignored_dir in always_ignore):
                continue

            try:
                # Get relative path
                relative_path = str(item.relative_to(project_path))

                # Emit progress for this file
                if progress_callback:
                    try:
                        progress_callback(relative_path)
                    except Exception:
                        pass
                else:
                    logger.debug(f"Indexing file: {relative_path}")

                # Check .daignore if provided
                if daignore and daignore.is_ignored(str(item)):
                    continue

                # Get file stats
                file_size = item.stat().st_size

                # Read content and calculate hash
                try:
                    content = item.read_bytes()
                    content_hash = hashlib.sha256(content).hexdigest()

                    # Check if binary
                    try:
                        text_content = content.decode('utf-8')
                        is_binary = False
                        # Store content if small enough
                        content_to_store = text_content if file_size <= self.max_snapshot_size else None
                    except UnicodeDecodeError:
                        is_binary = True
                        content_to_store = None

                    # Create snapshot
                    snapshot = FileSnapshot(
                        relative_path=relative_path,
                        content=content_to_store,
                        size=file_size,
                        content_hash=content_hash,
                        is_binary=is_binary
                    )

                    self.session_start_snapshot[relative_path] = snapshot
                    file_count += 1

                except Exception as e:
                    logger.warning(f"Could not snapshot {relative_path}: {e}")
                    continue

            except Exception as e:
                logger.warning(f"Error processing {item}: {e}")
                continue

        elapsed = time.time() - start_time
        logger.info(f"Captured snapshot of {file_count} files in {elapsed:.2f}s")

    def get_first_change_per_file(self) -> Dict[str, FileChange]:
        """Get the first change for each file (session start state)."""
        first_changes = {}
        for change in self.changes:
            rel_path = change.relative_path
            if rel_path not in first_changes:
                first_changes[rel_path] = change
        return first_changes

    def revert_all_changes(self) -> Dict[str, Any]:
        """Revert ALL changes (agent, user, external) back to session start.

        Uses session_start_snapshot to determine original file state.

        Returns:
            Dictionary with stats about the revert operation
        """
        from pathlib import Path as PathLib
        import os

        if not self.session_start_snapshot:
            return {"status": "error", "message": "No session-start snapshot available"}

        stats = {
            "deleted": 0,
            "restored": 0,
            "errors": [],
            "files_affected": 0
        }

        # Get all files that were changed during the session
        changed_files = set()
        for change in self.changes:
            changed_files.add(change.relative_path)

        # Restore changed files to session-start state
        for rel_path in changed_files:
            full_path = PathLib(self.project_root) / rel_path

            try:
                if rel_path in self.session_start_snapshot:
                    # File existed at session start - restore it
                    snapshot = self.session_start_snapshot[rel_path]

                    if snapshot.content is not None:
                        # We have the content - restore it
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        # Use open() with newline='' to preserve exact line endings without translation
                        with open(full_path, 'w', encoding='utf-8', newline='') as f:
                            f.write(snapshot.content)
                        stats["restored"] += 1
                        stats["files_affected"] += 1
                        logger.info(f"Restored file to session-start state: {rel_path}")
                    else:
                        # Large file or binary - can't restore
                        stats["errors"].append(f"{rel_path}: File too large or binary, cannot restore")
                else:
                    # File didn't exist at session start - delete it
                    if full_path.exists():
                        os.remove(full_path)
                        stats["deleted"] += 1
                        stats["files_affected"] += 1
                        logger.info(f"Deleted file created during session: {rel_path}")

            except Exception as e:
                stats["errors"].append(f"{rel_path}: {str(e)}")
                logger.error(f"Error reverting {rel_path}: {e}")

        # Check for files that were deleted during session
        for rel_path, snapshot in self.session_start_snapshot.items():
            full_path = PathLib(self.project_root) / rel_path

            if rel_path not in changed_files:
                # File exists unchanged - skip it
                continue

            # If file was deleted (doesn't exist now but should)
            if not full_path.exists():
                try:
                    if snapshot.content is not None:
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        # Use open() with newline='' to preserve exact line endings without translation
                        with open(full_path, 'w', encoding='utf-8', newline='') as f:
                            f.write(snapshot.content)
                        stats["restored"] += 1
                        stats["files_affected"] += 1
                        logger.info(f"Restored deleted file: {rel_path}")
                    else:
                        stats["errors"].append(f"{rel_path}: File was deleted but cannot restore (too large or binary)")
                except Exception as e:
                    stats["errors"].append(f"{rel_path}: {str(e)}")
                    logger.error(f"Error restoring deleted file {rel_path}: {e}")

        return {
            "status": "completed",
            "stats": stats,
            "total_files": len(changed_files)
        }


class CodeSession(BaseModel):
    """Main session model containing all command executions and context."""
    
    # unique id
    id: PyObjectId = Field(default_factory=ObjectId, alias="_id")

    model_config = ConfigDict(
        validate_assignment=True,
        extra='allow',
        populate_by_name=True,
        arbitrary_types_allowed = True,
        json_encoders = {ObjectId: str}
    )

    # Session identification (id is the primary identifier, inherited from BaseModel)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Session context
    working_directory: str = Field(..., description="Base working directory for session")
    project_context: Optional[ProjectContext] = Field(None, description="Loaded project context")
    mcp_servers: List[MCPServerInfo] = Field(default_factory=list, description="Available MCP servers")
    daignore: Any = Field(None, description="DaIgnore instance for filtering files")

    # Execution tracking
    executions: List[CommandExecution] = Field(default_factory=list, description="All command executions")
    llm_calls: List[LLMCall] = Field(default_factory=list, description="All LLM API calls")
    tool_calls: List[ToolCall] = Field(default_factory=list, description="All tool/MCP calls")

    # Filesystem tracking
    filesystem_history: Optional[FileSystemHistory] = Field(None, description="File change history for session")

    # Statistics
    total_commands: int = Field(0, description="Total number of commands executed")
    successful_commands: int = Field(0, description="Number of successful commands")
    failed_commands: int = Field(0, description="Number of failed commands")
    total_llm_calls: int = Field(0, description="Total number of LLM calls")
    total_tool_calls: int = Field(0, description="Total number of tool calls")
    total_tokens: int = Field(0, description="Total tokens used across all LLM calls")
    estimated_cost: float = Field(0.0, description="Total estimated cost in USD")

    # Agent configuration
    agent_model: str = Field("gpt-4", description="Azure OpenAI model being used")
    agent_temperature: float = Field(0.7, description="Agent temperature setting")

    def add_execution(self, execution: CommandExecution) -> None:
        """Add a command execution to the session."""
        self.executions.append(execution)
        self.updated_at = datetime.now(timezone.utc)

        if execution.status == CommandStatus.SUCCESS:
            self.successful_commands += 1
            self.total_commands += 1
        elif execution.status == CommandStatus.FAILED:
            self.failed_commands += 1
            self.total_commands += 1

    def get_recent_executions(self, count: int = 10) -> List[CommandExecution]:
        """Get the most recent command executions."""
        return self.executions[-count:] if self.executions else []

    def add_llm_call(self, llm_call: LLMCall) -> None:
        """Add an LLM call to the session."""
        self.llm_calls.append(llm_call)
        self.updated_at = datetime.now(timezone.utc)
        self.total_llm_calls += 1

        if llm_call.total_tokens:
            self.total_tokens += llm_call.total_tokens
        if llm_call.estimated_cost:
            self.estimated_cost += llm_call.estimated_cost

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the session."""
        self.tool_calls.append(tool_call)
        self.updated_at = datetime.now(timezone.utc)
        self.total_tool_calls += 1

    def init_filesystem_history(self) -> None:
        """Initialize filesystem history for this session."""
        if not self.filesystem_history:
            self.filesystem_history = FileSystemHistory(
                session_id=str(self.id),
                project_root=self.working_directory
            )

    def get_file_changes_summary(self, peek_only: bool = False) -> Optional[str]:
        """Get summary of recent file changes.

        Args:
            peek_only: If True, only peek at changes without marking them as reported.
                      Use this when building context before agent starts.
        """
        if not self.filesystem_history:
            return None
        return self.filesystem_history.get_changes_since_last_prompt(peek_only=peek_only)

    def mark_file_changes_reported(self) -> None:
        """Mark file changes as reported after agent successfully starts."""
        if self.filesystem_history:
            self.filesystem_history.mark_changes_reported()

    def get_session_summary(self) -> Dict[str, Any]:
        """Get a comprehensive summary of the session."""
        duration = (self.updated_at - self.created_at).total_seconds()

        return {
            "session_id": str(self.id),
            "duration_seconds": duration,
            "total_commands": self.total_commands,
            "successful_commands": self.successful_commands,
            "failed_commands": self.failed_commands,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "total_tokens": self.total_tokens,
            "estimated_cost": self.estimated_cost,
            "working_directory": self.working_directory,
            "agent_model": self.agent_model,
            "mcp_servers_count": len(self.mcp_servers),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }



class DaMongoTracker:
    """Async MongoDB tracker using Motor."""

    def __init__(self):
        self.mongo_enabled = False
        self.client: Optional[AsyncIOMotorClient] = None
        self.database = "da_code"
        self._init_mongo_client()

    def _init_mongo_client(self) -> None:
        """Initialize MongoDB client."""
        self.mongo_enabled = False
        try:
            mongo_uri = os.getenv('MONGO_URI', None)
            self.client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=3000)
            self.mongo_enabled = True
            logger.info(f"MongoDB client initialized: {mongo_uri}")
        except Exception as e:
            logger.info(f"MongoDB not available: {e}")
            

    async def _save_to_mongo(self, collection: str, document: Dict[str, Any]) -> bool:
        """Save document directly to MongoDB."""
        if not self.mongo_enabled or not self.client:
            return False

        try:
            db = self.client[self.database]
            coll = db[collection]
            await coll.insert_one(document)
            return True
        except Exception:
            self.mongo_enabled = False
            return False

    def _save_to_file(self, filename: str, data: Dict[str, Any]) -> None:
        """Fallback: save to local file."""
        try:
            Path(".da").mkdir(exist_ok=True)
            with open(f".da/{filename}", 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception:
            pass

    async def save_session(self, session: CodeSession) -> None:
        """Save session to MongoDB or file."""
        session_dict = session.dict()

        success = await self._save_to_mongo("sessions", session_dict)
        if not success:
            self._save_to_file(f"{str(session.id)}.json", session_dict)

    async def load_session(self, session_id: str) -> Optional[CodeSession]:
        """Load session from MongoDB or file by ObjectId string.

        Args:
            session_id: String representation of ObjectId
        """
        # Try MongoDB first
        if self.mongo_enabled and self.client:
            try:
                db = self.client[self.database]
                coll = db["sessions"]
                # Query by _id field (the ObjectId)
                if ObjectId.is_valid(session_id):
                    session_dict = await coll.find_one({"_id": ObjectId(session_id)})
                    if session_dict:
                        return CodeSession(**session_dict)
            except Exception as e:
                logger.warning(f"Failed to load from MongoDB: {e}")

        # Fallback to file
        try:
            session_file = Path(f".da/{session_id}.json")
            if session_file.exists():
                with open(session_file, 'r') as f:
                    session_dict = json.load(f)
                    return CodeSession(**session_dict)
        except Exception as e:
            logger.warning(f"Failed to load from file: {e}")

        return None

    async def save_llm_call(self, session_id: str, llm_call: LLMCall) -> None:
        """Save LLM call to MongoDB or file."""
        call_dict = llm_call.dict()
        call_dict["session_id"] = session_id

        success = await self._save_to_mongo("llm_calls", call_dict)
        if not success:
            self._save_to_file(f"llm_{llm_call.id}.json", call_dict)

    async def save_tool_call(self, session_id: str, tool_call: ToolCall) -> None:
        """Save tool call to MongoDB or file."""
        call_dict = tool_call.dict()
        call_dict["session_id"] = session_id

        success = await self._save_to_mongo("tool_calls", call_dict)
        if not success:
            self._save_to_file(f"tool_{tool_call.id}.json", call_dict)

    async def save_file_change(self, session_id: str, file_change: FileChange) -> None:
        """Save file change to MongoDB or file."""
        change_dict = file_change.dict()
        change_dict["session_id"] = session_id

        success = await self._save_to_mongo("file_changes", change_dict)
        if not success:
            # Fallback: append to session history file
            try:
                Path(".da").mkdir(exist_ok=True)
                history_file = Path(f".da/session_{session_id}_files.jsonl")
                with open(history_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(change_dict, default=str) + '\n')
            except Exception:
                pass

    async def close(self) -> None:
        """Close MongoDB connection."""
        if self.client:
            self.client.close()


class StatusMessage(BaseModel):
    """Status message for live interface display."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid',
        str_strip_whitespace=True
    )

    message: str = Field(..., description="Status message text")
    status_type: StatusType = Field(StatusType.INFO, description="Type of status message")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Optional[str] = Field(None, description="Additional details")
    session_id: Optional[str] = Field(None, description="Associated session ID")


class InterfaceState(BaseModel):
    """State tracking for live interface."""
    model_config = ConfigDict(
        validate_assignment=True,
        extra='forbid'
    )

    is_executing: bool = Field(False, description="Whether agent is currently executing")
    execution_start_time: Optional[float] = Field(None, description="Execution start timestamp")
    current_status: str = Field("Ready", description="Current status description")
    timeout_seconds: int = Field(300, description="Execution timeout in seconds")

    # Events for async coordination
    interrupt_requested: bool = Field(False, description="Whether interrupt was requested")
    confirmation_pending: bool = Field(False, description="Whether confirmation is pending")
    confirmation_result: Optional[bool] = Field(None, description="Result of confirmation")

    def start_execution(self, description: str) -> None:
        """Start execution tracking."""
        self.is_executing = True
        self.execution_start_time = datetime.now(timezone.utc).timestamp()
        self.current_status = description
        self.interrupt_requested = False

    def stop_execution(self) -> None:
        """Stop execution tracking."""
        self.is_executing = False
        self.execution_start_time = None
        self.current_status = "Ready"

    def get_elapsed_time(self) -> float:
        """Get elapsed execution time in seconds."""
        if not self.execution_start_time:
            return 0.0
        return datetime.now(timezone.utc).timestamp() - self.execution_start_time

    def get_remaining_time(self) -> float:
        """Get remaining time before timeout."""
        elapsed = self.get_elapsed_time()
        return max(0.0, self.timeout_seconds - elapsed)


# Global session tracker
da_mongo = DaMongoTracker()


def get_mongo_status() -> bool:
    """Get current MongoDB connection status."""
    try:
        return da_mongo.mongo_enabled and da_mongo.client is not None
    except:
        return False