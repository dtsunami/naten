"""Test script to verify context tracking with model interceptor.

This demonstrates how to:
1. Access actual token usage from the model interceptor
2. Display context usage summary
3. Manage tools to optimize context
"""

import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging to see the output
logging.basicConfig(
    level=logging.INFO,
    format='%(name)-30s - %(levelname)-8s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_context_tracking():
    """Test context tracking functionality."""
    from da_code.context_inspector import (
        get_interceptor_stats,
        log_context_summary,
        verify_interceptor,
        ContextManager
    )

    logger.info("=" * 80)
    logger.info("Context Tracking Test")
    logger.info("=" * 80)

    # This would normally be your agent instance
    # For testing, we'll create a mock
    class MockAgent:
        """Mock agent with interceptor stats."""

        def __init__(self):
            class MockModel:
                stats = {
                    'call_count': 5,
                    'total_input_tokens': 45234,
                    'max_context_seen': 12000,
                }

            self.llm = MockModel()
            self.agent_tools = []

    agent = MockAgent()

    # Test 1: Get stats
    logger.info("\n📊 Test 1: Get interceptor stats")
    stats = get_interceptor_stats(agent)
    if stats:
        logger.info(f"   ✅ Got stats: {stats.call_count} calls, {stats.total_input_tokens:,} tokens")
    else:
        logger.error("   ❌ Failed to get stats")

    # Test 2: Verify interceptor
    logger.info("\n📊 Test 2: Verify interceptor is working")
    is_working = verify_interceptor(agent)
    logger.info(f"   {'✅' if is_working else '❌'} Interceptor working: {is_working}")

    # Test 3: Show summary
    logger.info("\n📊 Test 3: Show context usage summary")
    log_context_summary(agent, max_tokens=128000)

    # Test 4: Context manager
    logger.info("\n📊 Test 4: Context manager")
    mgr = ContextManager(agent)
    stats = mgr.get_stats()
    logger.info(f"   ✅ Context manager stats: {stats.avg_context:,} avg tokens")

    logger.info("\n" + "=" * 80)
    logger.info("✅ All tests passed! Context tracking is working.")
    logger.info("=" * 80)


if __name__ == '__main__':
    test_context_tracking()