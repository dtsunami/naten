"""Demo script showing how to verify token usage and manage tools."""

import asyncio
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from da_code.models import CodeSession
from da_code.agno_agent import AgnoAgent
from da_code.context_inspector import (
    ContextInspector,
    ContextManager,
    verify_token_usage
)
from da_code.context import ContextLoader


async def demo_context_verification():
    """Demonstrate context verification and tool management."""

    print("\n" + "="*80)
    print("CONTEXT VERIFICATION DEMO")
    print("="*80 + "\n")

    # Create a minimal session
    code_session = CodeSession(
        working_directory=str(Path.cwd()),
        project_context=None,
        mcp_servers=[],
    )

    # Initialize agent
    print("🔧 Initializing agent...")
    agent = AgnoAgent(code_session, cwd_context="Demo directory context")

    # 1. VERIFY TOKEN USAGE
    print("\n" + "-"*80)
    print("1. VERIFYING ACTUAL TOKEN USAGE")
    print("-"*80)

    breakdown = verify_token_usage(agent, session_id=str(code_session.id))

    print(f"\n📊 Actual Context Breakdown:")
    print(f"   System message:     {breakdown.system_message_tokens:>6,} tokens")
    print(f"   User messages:      {breakdown.user_message_tokens:>6,} tokens")
    print(f"   Chat history:       {breakdown.chat_history_tokens:>6,} tokens")
    print(f"   Tool schemas:       {breakdown.tool_schemas_tokens:>6,} tokens")
    print(f"   {'─' * 40}")
    print(f"   TOTAL:              {breakdown.total_tokens:>6,} tokens")
    print(f"\n   Tools: {breakdown.tool_count} toolkits, {breakdown.tool_function_count} functions")

    print(f"\n   Per-tool breakdown:")
    for tool_name, tokens in breakdown.breakdown_by_tool.items():
        print(f"     • {tool_name:<20} {tokens:>6,} tokens")

    # 2. TOOL MANAGEMENT
    print("\n" + "-"*80)
    print("2. TOOL MANAGEMENT")
    print("-"*80)

    context_mgr = ContextManager(agent)

    print("\n🔧 Current tools:")
    for t in agent.agent_tools:
        tool_name = getattr(t, 'name', t.__class__.__name__)
        func_count = len(t.functions) if hasattr(t, 'functions') else 1
        print(f"   • {tool_name} ({func_count} functions)")

    # Example: Disable TodoTool to save tokens
    print("\n🔧 Disabling TodoTool to reduce context usage...")
    context_mgr.disable_tools(['TodoTool'])

    # Verify reduction
    breakdown_after = verify_token_usage(agent, session_id=str(code_session.id))
    tokens_saved = breakdown.tool_schemas_tokens - breakdown_after.tool_schemas_tokens

    print(f"\n   Tokens saved: {tokens_saved:,} ({tokens_saved / breakdown.tool_schemas_tokens * 100:.1f}% reduction in tool schemas)")

    # Re-enable
    print("\n🔧 Re-enabling all tools...")
    context_mgr.enable_tools(['TodoTool', 'CommandTool', 'FileTool', 'HttpTool'])

    # 3. MESSAGE INSPECTION
    print("\n" + "-"*80)
    print("3. MESSAGE INSPECTION")
    print("-"*80)

    print("\n📨 Messages that would be sent to LLM:")
    if breakdown.raw_messages:
        for i, msg in enumerate(breakdown.raw_messages[:5], 1):  # Show first 5
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            content_preview = content[:100] + "..." if len(content) > 100 else content
            print(f"\n   Message {i} ({role}):")
            print(f"   {content_preview}")

        if len(breakdown.raw_messages) > 5:
            print(f"\n   ... and {len(breakdown.raw_messages) - 5} more messages")

    # 4. PRE-HOOK DEMONSTRATION
    print("\n" + "-"*80)
    print("4. PRE-HOOK FOR REAL-TIME VERIFICATION")
    print("-"*80)

    inspector = ContextInspector()
    pre_hook = inspector.create_pre_hook()

    print("\n💡 To enable real-time context logging, add pre_hook to Agent:")
    print("   ```python")
    print("   self.agent = Agent(")
    print("       ...,")
    print("       pre_hooks=[pre_hook],  # Log context before each LLM call")
    print("   )")
    print("   ```")

    print("\n💡 Pre-hooks can also be used to:")
    print("   • Compact messages before sending to LLM")
    print("   • Remove redundant tool schemas")
    print("   • Summarize long chat history")
    print("   • Track exact token usage per call")

    # 5. RECOMMENDATIONS
    print("\n" + "="*80)
    print("RECOMMENDATIONS FOR CONTEXT OPTIMIZATION")
    print("="*80)

    print("\n📋 Based on this analysis:")

    if breakdown.tool_schemas_tokens > 30000:
        print(f"   ⚠️  Tool schemas use {breakdown.tool_schemas_tokens:,} tokens ({breakdown.tool_schemas_tokens / 128000 * 100:.1f}% of 128k context)")
        print(f"      Consider disabling unused tools or using MCP selectively")

    if breakdown.chat_history_tokens > 20000:
        print(f"   ⚠️  Chat history uses {breakdown.chat_history_tokens:,} tokens")
        print(f"      Consider reducing num_history_runs (currently 5)")

    if breakdown.total_tokens > 100000:
        print(f"   ⚠️  Total context: {breakdown.total_tokens:,} tokens ({breakdown.total_tokens / 128000 * 100:.1f}% of 128k)")
        print(f"      Context is high - agent may have limited space for responses")

    print("\n✅ Context verification complete!")
    print("\n" + "="*80 + "\n")


if __name__ == '__main__':
    asyncio.run(demo_context_verification())
