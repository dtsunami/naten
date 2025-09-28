"""Unified execution event system for multi-framework agent streaming."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional, Union, AsyncGenerator
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .models import CommandExecution


class EventType(str, Enum):
    """Types of execution events."""
    EXECUTION_START = "execution_start"
    EXECUTION_END = "execution_end"
    LLM_START = "llm_start"
    LLM_END = "llm_end"
    LLM_STREAM = "llm_stream"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    COMMAND_CONFIRMATION_NEEDED = "command_confirmation_needed"
    COMMAND_EXECUTED = "command_executed"
    AGENT_THOUGHT = "agent_thought"
    ERROR = "error"
    FINAL_RESPONSE = "final_response"


class ExecutionEvent(BaseModel):
    """Unified execution event that any framework can emit."""

    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    framework: str = Field(..., description="Framework that generated this event")

    # Event data - different types use different fields
    content: Optional[str] = None
    execution: Optional[CommandExecution] = None
    tool_name: Optional[str] = None
    tokens_used: Optional[int] = None
    execution_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


class ConfirmationRequest(BaseModel):
    """Request for user confirmation during execution."""

    execution: CommandExecution
    choices: list[str] = Field(default=["yes", "no", "modify", "explain"])
    default_choice: str = "no"


class ConfirmationResponse(BaseModel):
    """User response to confirmation request."""

    choice: str
    modified_command: Optional[str] = None


class StreamingExecutor(ABC):
    """Abstract base for streaming execution across frameworks."""

    @abstractmethod
    async def execute_with_stream(self, task: str) -> AsyncGenerator[ExecutionEvent, ConfirmationResponse]:
        """
        Execute task and yield events. Can receive confirmation responses.

        Usage:
            executor = SomeStreamingExecutor()
            confirmation_response = None

            async for event in executor.execute_with_stream(task):
                if event.event_type == EventType.COMMAND_CONFIRMATION_NEEDED:
                    # Get user input
                    user_choice = await prompt_user(event.execution)
                    confirmation_response = ConfirmationResponse(choice=user_choice)

                    # Send response back to generator
                    try:
                        event = await executor.asend(confirmation_response)
                    except StopAsyncIteration:
                        break

                elif event.event_type == EventType.FINAL_RESPONSE:
                    return event.content
        """
        pass

    @abstractmethod
    def get_framework_name(self) -> str:
        """Get the framework identifier."""
        pass


class EventConverter:
    """Converts framework-specific events to unified ExecutionEvents."""

    @staticmethod
    def from_langchain(event: Dict[str, Any], framework: str = "langchain") -> Optional[ExecutionEvent]:
        """Convert LangChain astream_events to ExecutionEvent."""
        event_type = event.get("event")
        event_name = event.get("name", "")
        data = event.get("data", {})

        if event_type == "on_llm_start":
            return ExecutionEvent(
                event_type=EventType.LLM_START,
                framework=framework,
                content="LLM call started",
                metadata={"name": event_name, "data": data}
            )

        elif event_type == "on_llm_end":
            tokens = 0
            if "output" in data:
                output = data["output"]
                if hasattr(output, "usage_metadata"):
                    tokens = output.usage_metadata.get("total_tokens", 0)

            return ExecutionEvent(
                event_type=EventType.LLM_END,
                framework=framework,
                content="LLM call completed",
                tokens_used=tokens,
                metadata={"name": event_name, "data": data}
            )

        elif event_type == "on_tool_start":
            return ExecutionEvent(
                event_type=EventType.TOOL_START,
                framework=framework,
                tool_name=event_name,
                content=f"Tool started: {event_name}",
                metadata={"data": data}
            )

        elif event_type == "on_tool_end":
            return ExecutionEvent(
                event_type=EventType.TOOL_END,
                framework=framework,
                tool_name=event_name,
                content=f"Tool completed: {event_name}",
                metadata={"data": data}
            )

        elif event_type == "on_chain_end":
            # Check if this is the final response
            if "output" in data:
                output_data = data["output"]
                if isinstance(output_data, dict) and "output" in output_data:
                    return ExecutionEvent(
                        event_type=EventType.FINAL_RESPONSE,
                        framework=framework,
                        content=output_data["output"]
                    )

        return None

    @staticmethod
    def from_agno(event: Dict[str, Any], framework: str = "agno") -> Optional[ExecutionEvent]:
        """Convert Agno events to ExecutionEvent."""
        # TODO: Implement when we add Agno
        # This will convert Agno's streaming events to our unified format
        pass


class UnifiedEventStream:
    """Utility for creating unified event streams from different sources."""

    @staticmethod
    async def from_langchain_stream(
        langchain_stream: AsyncGenerator[Dict[str, Any], None],
        framework: str = "langchain"
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """Convert LangChain astream_events to unified event stream."""
        async for event in langchain_stream:
            unified_event = EventConverter.from_langchain(event, framework)
            if unified_event:
                yield unified_event

    @staticmethod
    async def from_agno_stream(
        agno_stream: AsyncGenerator[Dict[str, Any], None],
        framework: str = "agno"
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """Convert Agno stream to unified event stream."""
        # TODO: Implement when we add Agno
        async for event in agno_stream:
            unified_event = EventConverter.from_agno(event, framework)
            if unified_event:
                yield unified_event