"""Factory for creating agents with different frameworks."""

import logging
from typing import Optional

from .agent_interface import AgentInterface, AgentFramework
from .async_agent import CustomAsyncAgent
from .models import AgentConfig, CodeSession

logger = logging.getLogger(__name__)


class AgentFactory:
    """Factory for creating agents with framework selection."""

    @staticmethod
    def create_agent(
        config: AgentConfig,
        session: CodeSession,
        framework: Optional[AgentFramework] = None
    ) -> AgentInterface:
        """Create an agent instance with the specified framework."""

        # Determine which framework to use
        selected_framework = framework or config.framework_preference

        logger.debug(f"Creating agent with framework: {selected_framework}")

        try:
            if selected_framework == AgentFramework.LANGCHAIN:
                return CustomAsyncAgent(config, session)
            elif selected_framework == AgentFramework.AGNO:
                # TODO: Implement Agno adapter in future phases
                logger.warning("Agno framework not yet implemented, falling back to Custom Async")
                if config.auto_fallback:
                    return CustomAsyncAgent(config, session)
                else:
                    raise NotImplementedError("Agno framework not yet implemented")
            else:
                raise ValueError(f"Unsupported framework: {selected_framework}")

        except Exception as e:
            # Auto-fallback to Custom Async if enabled
            if config.auto_fallback and selected_framework != AgentFramework.LANGCHAIN:
                logger.warning(f"Failed to create {selected_framework} agent, falling back to Custom Async: {e}")
                return CustomAsyncAgent(config, session)
            else:
                logger.error(f"Failed to create agent with framework {selected_framework}: {e}")
                raise

    @staticmethod
    def get_available_frameworks() -> list[AgentFramework]:
        """Get list of available frameworks."""
        # For now, only LangChain is implemented
        return [AgentFramework.LANGCHAIN]

    @staticmethod
    def is_framework_available(framework: AgentFramework) -> bool:
        """Check if a framework is available."""
        return framework in AgentFactory.get_available_frameworks()

    @staticmethod
    def get_default_framework() -> AgentFramework:
        """Get the default framework."""
        return AgentFramework.LANGCHAIN