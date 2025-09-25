"""Simple async UI for da_code - minimal version without complex terminal handling."""

import asyncio
from typing import Any, Callable, Optional


class SimpleAsyncUI:
    """Simple UI for async operations without complex terminal handling."""

    async def chat_with_agent(self, agent_chat_func: Callable[[str], Any],
                             message: str) -> Optional[str]:
        """Execute agent chat with simple status updates."""
        try:
            print("🤖 Assistant: Thinking...")
            result = await agent_chat_func(message)
            return result
        except Exception as e:
            print(f"❌ Error: {e}")
            return None

    async def execute_shell_command(self,
                                   shell_func: Callable[[], Any],
                                   command: str) -> Any:
        """Execute shell command with simple status updates."""
        try:
            print(f"🔧 Executing: {command[:50]}...")
            result = await shell_func()
            return result
        except Exception as e:
            print(f"❌ Error: {e}")
            return None


# Global instance
simple_async_ui = SimpleAsyncUI()