"""Flexible chat memory management for da_code with PostgreSQL integration and fallbacks."""

import logging
import os
from typing import Optional

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory

logger = logging.getLogger(__name__)

# Try to import PostgreSQL chat history (graceful fallback if not available)
try:
    from langchain_community.chat_message_histories import PostgresChatMessageHistory
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logger.warning("PostgreSQL chat message history not available - install with: pip install psycopg2-binary")

# Try to import Redis chat history (optional)
try:
    from langchain_community.chat_message_histories import RedisChatMessageHistory
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


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

        # Strategy 2: Redis (good for distributed systems)
        redis_history = self._try_redis()
        if redis_history:
            return redis_history

        # Strategy 3: File-based (persistence without database)
        file_history = self._try_file()
        if file_history:
            return file_history

        # Strategy 4: In-memory (fallback)
        logger.info("Using in-memory chat history (no persistence)")
        self.memory_type = "memory"
        return ChatMessageHistory()

    def _try_postgres(self) -> Optional[BaseChatMessageHistory]:
        """Try to create PostgreSQL chat history."""
        if not POSTGRES_AVAILABLE:
            logger.debug("PostgreSQL chat history not available")
            return None

        # Check for PostgreSQL environment variables
        postgres_url = os.getenv("CHAT_POSTGRES_URL") or os.getenv("POSTGRES_CHAT_URL")

        # Alternative: construct from individual components
        if not postgres_url:
            host = os.getenv("CHAT_POSTGRES_HOST", "localhost")
            port = os.getenv("CHAT_POSTGRES_PORT", "5434")  # Your chat DB port
            user = os.getenv("CHAT_POSTGRES_USER", "lostboy")
            password = os.getenv("CHAT_POSTGRES_PASSWORD")
            database = os.getenv("CHAT_POSTGRES_DB", "orenco_chatmemory")

            if password:
                postgres_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

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

            logger.info(f"Connected to PostgreSQL chat memory: {database}")
            self.memory_type = "postgres"
            return chat_history

        except Exception as e:
            logger.warning(f"PostgreSQL chat history connection failed: {e}")
            return None

    def _try_redis(self) -> Optional[BaseChatMessageHistory]:
        """Try to create Redis chat history."""
        if not REDIS_AVAILABLE:
            logger.debug("Redis chat history not available")
            return None

        redis_url = os.getenv("REDIS_CHAT_URL") or os.getenv("REDIS_URL")
        if not redis_url:
            # Try to construct from components
            host = os.getenv("REDIS_HOST", "localhost")
            port = os.getenv("REDIS_PORT", "6379")
            password = os.getenv("REDIS_PASSWORD")

            if password:
                redis_url = f"redis://:{password}@{host}:{port}"
            else:
                redis_url = f"redis://{host}:{port}"

        if not redis_url:
            logger.debug("Redis configuration not found")
            return None

        try:
            chat_history = RedisChatMessageHistory(
                session_id=self.session_id,
                url=redis_url
            )

            # Test connection
            chat_history.messages

            logger.info("Connected to Redis chat memory")
            self.memory_type = "redis"
            return chat_history

        except Exception as e:
            logger.warning(f"Redis chat history connection failed: {e}")
            return None

    def _try_file(self) -> Optional[BaseChatMessageHistory]:
        """Try to create file-based chat history."""
        try:
            # Check if file storage is enabled
            enable_file_storage = os.getenv("DA_CODE_FILE_MEMORY", "false").lower() == "true"
            if not enable_file_storage:
                logger.debug("File-based chat history disabled")
                return None

            from langchain_community.chat_message_histories import FileChatMessageHistory
            import os
            from pathlib import Path

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


def test_memory_connections() -> dict:
    """Test all available memory connections and return status."""
    status = {
        "postgres": {"available": POSTGRES_AVAILABLE, "connected": False},
        "redis": {"available": REDIS_AVAILABLE, "connected": False},
        "file": {"available": True, "connected": False},
        "memory": {"available": True, "connected": True}
    }

    # Test PostgreSQL
    if POSTGRES_AVAILABLE:
        manager = ChatMemoryManager("test_session")
        postgres_history = manager._try_postgres()
        status["postgres"]["connected"] = postgres_history is not None

    # Test Redis
    if REDIS_AVAILABLE:
        manager = ChatMemoryManager("test_session")
        redis_history = manager._try_redis()
        status["redis"]["connected"] = redis_history is not None

    # Test File
    manager = ChatMemoryManager("test_session")
    file_history = manager._try_file()
    status["file"]["connected"] = file_history is not None

    return status


if __name__ == "__main__":
    # Demo/test the memory manager
    import json

    print("Testing da_code Chat Memory Manager")
    print("=" * 40)

    # Test connections
    status = test_memory_connections()
    print("\nConnection Status:")
    print(json.dumps(status, indent=2))

    # Test memory manager
    print("\nTesting Chat Memory Manager:")
    manager = create_chat_memory_manager("demo_session")
    history = manager.get_chat_history()

    print(f"Memory Type: {manager.memory_type}")
    print(f"Memory Info: {json.dumps(manager.get_memory_info(), indent=2)}")

    # Add test message
    from langchain_core.messages import HumanMessage
    history.add_message(HumanMessage(content="Test message"))

    print(f"Messages after adding test: {len(history.messages)}")
    print(f"Export: {manager.export_history()}")