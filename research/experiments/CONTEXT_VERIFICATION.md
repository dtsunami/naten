# Context Verification & Tool Management

This guide explains how to verify actual token usage and manage tools for context optimization.

## Quick Start

### 1. Run Context Verification Demo

```bash
python inspect_context_demo.py
```

This will show:
- Actual token usage breakdown (not estimates!)
- Per-tool token usage
- How to disable/enable tools dynamically
- Message inspection

### 2. Verify Token Usage in CLI

Add this to your CLI session:

```python
# In agno_cli.py, add a new command handler:

elif user_input.lower() == 'inspect':
    # Verify actual token usage
    from da_code.context_inspector import verify_token_usage
    breakdown = verify_token_usage(agent, session_id=str(code_session.id))

    console.print("\n[bold cyan]Context Breakdown:[/bold cyan]")
    console.print(f"  System:       {breakdown.system_message_tokens:>6,} tokens")
    console.print(f"  User:         {breakdown.user_message_tokens:>6,} tokens")
    console.print(f"  History:      {breakdown.chat_history_tokens:>6,} tokens")
    console.print(f"  Tool schemas: {breakdown.tool_schemas_tokens:>6,} tokens")
    console.print(f"  {'─' * 40}")
    console.print(f"  TOTAL:        {breakdown.total_tokens:>6,} tokens")
    console.print(f"\n  Tools: {breakdown.tool_count} toolkits, {breakdown.tool_function_count} functions")

    # Show per-tool breakdown
    console.print("\n[bold]Per-tool token usage:[/bold]")
    for tool_name, tokens in sorted(breakdown.breakdown_by_tool.items(), key=lambda x: -x[1]):
        pct = (tokens / breakdown.total_tokens) * 100
        console.print(f"  • {tool_name:<20} {tokens:>6,} ({pct:.1f}%)")
```

### 3. Enable Real-Time Context Logging

To see exactly what's sent to the LLM on each call, use `pre_hooks`:

```python
# In agno_agent.py AgnoAgent.__init__:

from .context_inspector import ContextInspector

# Create pre-hook for logging
inspector = ContextInspector()
pre_hook = inspector.create_pre_hook()

self.agent = Agent(
    name="da_code",
    model=self.llm,
    # ... other params ...
    pre_hooks=[pre_hook],  # ✨ Log context before each LLM call
)
```

Now every LLM call will log:
```
🔍 PRE-HOOK: Sending 45,234 tokens to LLM
   Breakdown: system=2,456, user=1,234, assistant=12,544, tool=29,000
```

## Tool Management

### Create Tool Configuration

```bash
python -c "from da_code.tool_config import create_default_config; create_default_config()"
```

This creates `.da/tools.json`:

```json
{
  "max_context_tokens": 128000,
  "max_tool_tokens": 40000,
  "max_history_tokens": 20000,
  "num_history_runs": 5,
  "tools": {
    "TodoTool": {
      "name": "TodoTool",
      "enabled": true,
      "priority": 5,
      "description": "Manage TODO lists",
      "estimated_tokens": 8000
    },
    "CommandTool": {
      "name": "CommandTool",
      "enabled": true,
      "priority": 10,
      "description": "Execute shell commands",
      "estimated_tokens": 2000
    },
    "FileTool": {
      "name": "FileTool",
      "enabled": true,
      "priority": 10,
      "description": "File operations",
      "estimated_tokens": 16000
    }
  }
}
```

### Disable Tools to Save Tokens

```python
from da_code.context_inspector import ContextManager

# Disable TodoTool (saves ~8k tokens)
context_mgr = ContextManager(agent)
context_mgr.disable_tools(['TodoTool'])

# Re-enable later
context_mgr.enable_tools(['TodoTool'])
```

### Auto-Optimize for Token Budget

```python
from da_code.tool_config import ToolConfigManager

tool_mgr = ToolConfigManager()

# Find which tools to disable to fit under 30k token budget
to_disable = tool_mgr.optimize_tools_for_budget(max_tokens=30000)
print(f"Disable these tools to meet budget: {to_disable}")

# Apply to agent
for tool_name in to_disable:
    tool_mgr.disable_tool(tool_name)

tool_mgr.apply_to_agent(agent)
```

## Integration with AgnoAgent

### Option 1: Use Pre-Hooks (Recommended)

Pre-hooks run **before each LLM call** and can:
- Log actual context sent to LLM
- Modify messages (compact, summarize, etc.)
- Track token usage per call
- Implement custom context optimization

```python
# In agno_agent.py:

def create_context_pre_hook():
    """Create pre-hook that logs and optimizes context."""
    from .context_inspector import ContextInspector

    inspector = ContextInspector()

    def pre_hook(messages: List[Dict], **kwargs):
        # Log context
        total = sum(len(inspector.encoding.encode(str(m.get('content', ''))))
                   for m in messages)
        logger.info(f"🔍 Sending {total:,} tokens to LLM")

        # Optional: Compact messages if over budget
        if total > 100000:
            # Implement compaction logic here
            logger.warning(f"⚠️  High context usage: {total:,} tokens")

        return messages

    return pre_hook

# Then in Agent init:
self.agent = Agent(
    ...,
    pre_hooks=[create_context_pre_hook()],
)
```

### Option 2: Use get_messages_for_session()

Query messages after the fact:

```python
# Get messages that were/will be sent
messages = agent.agent.get_messages_for_session(session_id=session_id)

# Inspect them
inspector = ContextInspector()
for msg in messages:
    content = getattr(msg, 'content', '')
    tokens = len(inspector.encoding.encode(content))
    print(f"{msg.role}: {tokens} tokens")
```

### Option 3: Use Agent Methods

```python
# Dynamically manage tools
agent.agent.add_tool(new_tool)
agent.agent.set_tools(filtered_tools)

# Get session metrics (includes token usage)
metrics = agent.agent.get_session_metrics(session_id=session_id)
print(f"Input tokens: {metrics.input_tokens}")
print(f"Output tokens: {metrics.output_tokens}")

# Get chat history
messages = agent.agent.get_messages_for_session(session_id)
```

## Context Optimization Strategies

### 1. Tool Pruning

Disable low-priority tools based on actual usage:

```python
# After a few interactions, check which tools are used
from da_code.context_inspector import ContextManager

context_mgr = ContextManager(agent)
stats = context_mgr.get_tool_usage_stats()

# Disable unused tools
if stats['TodoTool']['calls'] == 0:
    context_mgr.disable_tools(['TodoTool'])
```

### 2. History Compaction

Reduce `num_history_runs` if context is too large:

```python
# In AgnoAgent.__init__, change:
self.agent = Agent(
    ...,
    num_history_runs=3,  # Reduced from 5 (saves ~8k tokens)
)
```

### 3. Selective MCP Loading

Load MCP tools only when needed:

```python
# In DA.json, comment out unused MCP servers
{
  "mcp_servers": [
    {"name": "essential_tool", "url": "http://localhost:8080"},
    // {"name": "rarely_used", "url": "http://localhost:8081"}  // Disabled
  ]
}
```

### 4. Message Summarization (Advanced)

Use pre-hooks to summarize long histories:

```python
def summarizing_pre_hook(messages: List[Dict], **kwargs):
    """Summarize old messages to save tokens."""

    # Keep recent messages, summarize old ones
    if len(messages) > 10:
        recent = messages[-5:]  # Keep last 5
        old = messages[:-5]     # Summarize the rest

        # Create summary message
        summary = {
            'role': 'system',
            'content': f'[Summary of {len(old)} earlier messages: ...]'
        }

        return [summary] + recent

    return messages
```

## Monitoring & Alerts

### Context Usage Warning

```python
# In CLI, before agent.arun():

breakdown = verify_token_usage(agent, session_id=str(code_session.id))

if breakdown.total_tokens > 100000:
    console.print(f"[yellow]⚠️  High context: {breakdown.total_tokens:,} tokens ({breakdown.total_tokens/128000*100:.0f}%)[/yellow]")
    console.print("[yellow]   Consider disabling some tools or compacting history[/yellow]")
```

### Token Budget Enforcement

```python
# Enforce max tool token budget
MAX_TOOL_TOKENS = 30000

tool_mgr = ToolConfigManager()
current_tokens = tool_mgr.estimate_tool_tokens()

if current_tokens > MAX_TOOL_TOKENS:
    to_disable = tool_mgr.optimize_tools_for_budget(MAX_TOOL_TOKENS)
    console.print(f"[yellow]Tool budget exceeded. Disabling: {', '.join(to_disable)}[/yellow]")

    for tool_name in to_disable:
        tool_mgr.disable_tool(tool_name)

    tool_mgr.apply_to_agent(agent)
```

## Summary

**Three Ways to Verify Token Usage:**

1. **`verify_token_usage(agent)`** - Get actual breakdown (use in CLI `inspect` command)
2. **Pre-hooks** - Real-time logging before each LLM call
3. **`get_messages_for_session()`** - Query messages after the fact

**Three Ways to Manage Tools:**

1. **`ContextManager`** - Programmatically enable/disable tools
2. **`ToolConfigManager`** - File-based configuration (`.da/tools.json`)
3. **`agent.set_tools()`** - Direct Agno Agent API

**Token Saving Strategies:**

- Disable unused tools (~2-8k per tool)
- Reduce `num_history_runs` (~4k per run)
- Use pre-hooks to compact/summarize messages
- Monitor context usage with `inspect` command

## Next Steps

1. ✅ Add `inspect` command to CLI (shows actual token usage)
2. ✅ Create `.da/tools.json` for tool configuration
3. ✅ Add pre-hook for real-time context logging
4. 🔄 Test with actual sessions to verify estimates vs actuals
5. 🔄 Implement message compaction in pre-hook
6. 🔄 Add tool usage tracking to identify unused tools