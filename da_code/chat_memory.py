"""Flexible chat memory management for da_code with PostgreSQL integration and fallbacks."""

import logging
import os
from typing import Optional

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_postgres import PostgresChatMessageHistory
from langchain_community.chat_message_histories import FileChatMessageHistory
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import PostgreSQL chat history (graceful fallback if not available)
POSTGRES_AVAILABLE = False


class ChatMemoryManager:
    """Flexible chat memory manager with PostgreSQL primary, in-memory fallback."""

    def __init__(self, session_id: str):
        """Initialize memory manager with session ID."""
        self.session_id = session_id
        self.chat_history: Optional[BaseChatMessageHistory] = None
        self.memory_type = "unknown"

    def get_chat_history(self) -> BaseChatMessageHistory:
        """Get chat history with automatic fallback strategy."""
        if self.chat_history is None:
            self.chat_history = self._create_chat_history()

        return self.chat_history

    def _create_chat_history(self) -> BaseChatMessageHistory:
        """Create chat history with fallback strategy: PostgreSQL -> Redis -> File -> In-Memory."""

        # Strategy 1: PostgreSQL (preferred for production)
        postgres_history = self._try_postgres()
        if postgres_history:
            return postgres_history

        # Strategy 2: File-based (persistence without database)
        file_history = self._try_file()
        if file_history:
            return file_history

        # Strategy 3: In-memory (fallback)
        logger.info("Using in-memory chat history (no persistence)")
        self.memory_type = "memory"
        return ChatMessageHistory()

    def _try_postgres(self) -> Optional[BaseChatMessageHistory]:
        """Try to create PostgreSQL chat history."""

        # Check for PostgreSQL environment variables
        postgres_url = os.getenv("POSTGRES_CHAT_URL", None)

        if not postgres_url:
            logger.debug("PostgreSQL configuration not found")
            return None

        try:
            # Test the connection and create chat history
            chat_history = PostgresChatMessageHistory(
                connection_string=postgres_url,
                session_id=self.session_id,
                table_name="da_code_chat_history"
            )

            # Try to access the chat history to test connection
            chat_history.messages  # This will trigger connection test

            logger.info(f"Connected to PostgreSQL chat memory: !")
            print(f"Connected to PostgreSQL chat memory: !")
            self.memory_type = "postgres"
            return chat_history

        except Exception as e:
            logger.warning(f"PostgreSQL chat history connection failed: {e}")
            return None

    def _try_file(self) -> Optional[BaseChatMessageHistory]:
        """Try to create file-based chat history."""
        try:
            # Check if file storage is enabled
            enable_file_storage = os.getenv("DA_CODE_FILE_MEMORY", "false").lower() == "true"
            if not enable_file_storage:
                logger.debug("File-based chat history disabled")
                return None



            # Create sessions directory
            sessions_dir = Path(os.getenv("DA_CODE_SESSIONS_DIR", "./da_code_sessions"))
            sessions_dir.mkdir(exist_ok=True, parents=True)

            session_file = sessions_dir / f"{self.session_id}.json"

            chat_history = FileChatMessageHistory(str(session_file))

            logger.info(f"Using file-based chat history: {session_file}")
            self.memory_type = "file"
            return chat_history

        except Exception as e:
            logger.warning(f"File-based chat history failed: {e}")
            return None

    def get_memory_info(self) -> dict:
        """Get information about the current memory configuration."""
        return {
            "memory_type": self.memory_type,
            "session_id": self.session_id,
            "persistent": self.memory_type in ["postgres", "redis", "file"],
            "shared": self.memory_type in ["postgres", "redis"],
            "message_count": len(self.chat_history.messages) if self.chat_history else 0
        }

    def clear_history(self) -> bool:
        """Clear chat history for current session."""
        try:
            if self.chat_history:
                self.chat_history.clear()
                logger.info(f"Cleared chat history for session {self.session_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to clear chat history: {e}")
            return False

    def export_history(self) -> list:
        """Export chat history as a list of message dicts."""
        try:
            if self.chat_history:
                messages = []
                for msg in self.chat_history.messages:
                    messages.append({
                        "type": msg.__class__.__name__,
                        "content": msg.content,
                        "timestamp": getattr(msg, "timestamp", None)
                    })
                return messages
            return []
        except Exception as e:
            logger.error(f"Failed to export chat history: {e}")
            return []


def create_chat_memory_manager(session_id: str) -> ChatMemoryManager:
    """Factory function to create a chat memory manager."""
    return ChatMemoryManager(session_id)

