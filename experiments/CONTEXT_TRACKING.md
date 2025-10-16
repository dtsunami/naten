# Context Tracking & Verification

This guide explains how to verify actual token usage and manage context in da_code.

## Overview

**Two-Layer System:**

1. **Model Interceptor** (`model_interceptor.py`) - Wraps the LLM model to capture ACTUAL messages and tokens sent to the API
2. **Context Inspector** (`context_inspector.py`) - Provides convenient access to interceptor stats and tool management

## How It Works

### Model Interceptor (Automatic)

The model interceptor is automatically enabled in `agno_agent.py`:

```python
# In agno_agent.py AgnoAgent.__init__:
from .model_interceptor import wrap_model_with_interceptor

base_llm = AzureOpenAI(...)
self.llm = wrap_model_with_interceptor(base_llm, max_tokens=128000)
```

**What it logs (automatically on each LLM call):**

```
🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯
🎯 INTERCEPTED: Async STREAMING LLM call (aresponse_stream)
🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯🎯

================================================================================
🔍 MODEL INTERCEPTOR: LLM Call #1
================================================================================

📊 Token Breakdown (Call #1):
   System messages:     1,234 tokens (1 msgs)
   User messages:       567 tokens (1 msgs)
   Assistant history:   0 tokens (0 msgs)
   Tool schemas:        28,000 tokens (14 tools)
   Tool results:        0 tokens (0 msgs)
   ────────────────────────────────────────────────────────────
   TOTAL CONTEXT:       29,801 tokens (23.3% of 128,000)

🔧 Tools Sent to LLM (14 total):
   • list_directory
   • read_file
   • create_file
   • delete_file
   • search_files
   • replace_text
   • copy_file
   • move_file
   • read_todo
   • check_exists

⚠️  Context Usage Analysis:
   ✅ Context usage is reasonable

📈 Cumulative Stats:
   Total LLM calls:     1
   Total input tokens:  29,801
   Max context (call):  29,801
   Avg context (call):  29,801

================================================================================
```

### Context Inspector (Manual Access)

Access the stats programmatically:

```python
from da_code.context_inspector import (
    get_interceptor_stats,
    log_context_summary,
    verify_interceptor,
    ContextManager
)

# Get current stats
stats = get_interceptor_stats(agent)
print(f"Total calls: {stats.call_count}")
print(f"Total tokens: {stats.total_input_tokens:,}")
print(f"Max context: {stats.max_context_seen:,}")

# Show summary
log_context_summary(agent)

# Verify interceptor is working
verify_interceptor(agent)

# Use context manager for tool management
mgr = ContextManager(agent)
mgr.log_summary()

# List tools
tools = mgr.list_tools()
print(f"Available tools: {tools}")

# Count functions per tool
func_counts = mgr.count_tool_functions()
print(f"Tool functions: {func_counts}")

# Estimate tool token usage
estimated = mgr.estimate_tool_tokens()
print(f"Estimated tool tokens: {estimated:,}")

# Disable tools to save tokens
mgr.disable_tools(['TodoTool', 'HttpTool'])  # Saves ~10k tokens
```

## CLI Integration

### Quick Test

Run the test script:

```bash
python test_context_tracking.py
```

### Add to CLI

You can add a command to show context stats in the CLI. Add to `agno_cli.py`:

```python
elif user_input.lower() == '/context':
    # Show context usage
    from da_code.context_inspector import log_context_summary, verify_interceptor

    console.print("\n[bold cyan]🔍 Verifying Model Interceptor[/bold cyan]")
    verify_interceptor(agent)

    console.print("\n[bold cyan]📊 Context Usage Summary[/bold cyan]")
    log_context_summary(agent)
    continue
```

Then in the CLI:

```
agent! /context
```

Output:

```
🔍 Verifying Model Interceptor
✅ Model interceptor is working - 3 LLM calls recorded
   Total tokens: 89,403
   Max context: 31,245

📊 Context Usage Summary

================================================================================
📊 CONTEXT USAGE SUMMARY (from model interceptor)
================================================================================
   Total LLM calls:     3
   Total input tokens:  89,403
   Max context (call):  31,245 (24.4% of 128,000)
   Avg context (call):  29,801 (23.3%)
   ✅ Context usage is reasonable
================================================================================
```

## Tool Management

### Count Tool Functions

Each tool function adds ~2k tokens to every LLM call.

```python
from da_code.context_inspector import ContextManager

mgr = ContextManager(agent)

# Count functions per tool
func_counts = mgr.count_tool_functions()
# Output: {
#   'TodoTool': 4,      # 4 functions × 2k = ~8k tokens
#   'CommandTool': 1,   # 1 function × 2k = ~2k tokens
#   'FileTool': 8,      # 8 functions × 2k = ~16k tokens
#   'HttpTool': 1,      # 1 function × 2k = ~2k tokens
# }
# Total: 14 functions = ~28k tokens per call

# Estimate total
estimated = mgr.estimate_tool_tokens()
print(f"Tool schemas use ~{estimated:,} tokens")  # ~28,000 tokens
```

### Disable Unused Tools

Save tokens by disabling tools you're not using:

```python
# Disable TodoTool and HttpTool (saves ~10k tokens per call)
mgr.disable_tools(['TodoTool', 'HttpTool'])

# Now only FileTool and CommandTool remain (~18k tokens)
```

### Enable Specific Tools

```python
# Only enable essential tools
mgr.enable_tools(['FileTool', 'CommandTool'])
```

## Verification

### Check Interceptor Status

```python
from da_code.context_inspector import verify_interceptor

# Returns True if working, False if not
is_working = verify_interceptor(agent)
```

Output:

```
✅ Model interceptor is working - 5 LLM calls recorded
   Total tokens: 149,005
   Max context: 31,245
```

### Check Actual vs Estimated

Compare the interceptor's ACTUAL token counts vs estimates:

```python
from da_code.context_inspector import get_interceptor_stats, ContextManager

stats = get_interceptor_stats(agent)
mgr = ContextManager(agent)

print(f"ACTUAL tool tokens (from last call): ???")  # Would need to store breakdown
print(f"ESTIMATED tool tokens: {mgr.estimate_tool_tokens():,}")

print(f"ACTUAL total context (max): {stats.max_context_seen:,}")
```

The model interceptor logs show the ACTUAL breakdown per call.

## Optimization Strategies

### 1. High Tool Schema Usage (>40k tokens)

If tool schemas use >40k tokens:

```python
mgr = ContextManager(agent)

# Disable unused tools
mgr.disable_tools(['TodoTool', 'HttpTool', 'TimeTool'])

# Or enable only what you need
mgr.enable_tools(['FileTool', 'CommandTool'])
```

### 2. High Chat History (>30k tokens)

If chat history uses >30k tokens:

- Reduce `num_history_runs` in `agno_agent.py` (currently 5)
- Clear old sessions from database

### 3. Monitor Context Usage

Check context usage after several interactions:

```python
from da_code.context_inspector import log_context_summary

log_context_summary(agent)

# If max usage > 70%:
#   - Disable tools
#   - Reduce num_history_runs
#   - Clear old sessions
```

## Summary

**What's Working:**

- ✅ Model interceptor captures ACTUAL messages sent to LLM
- ✅ Detailed token breakdown by message type
- ✅ Tool schema tracking (shows which tools are sent)
- ✅ Cumulative stats across session
- ✅ Warnings for high usage (>70%, >40k tools, >30k history)
- ✅ Context inspector provides programmatic access to stats
- ✅ Context manager for tool management

**How to Use:**

1. **Automatic logging** - Just run the CLI, interceptor logs every LLM call
2. **Manual access** - Use `get_interceptor_stats(agent)` to access stats
3. **Tool management** - Use `ContextManager(agent)` to enable/disable tools
4. **Verification** - Use `verify_interceptor(agent)` to check it's working

**Next Steps:**

- Add `/context` command to CLI for quick stats
- Integrate stats into context overlay UI
- Add tool usage tracking (which tools are actually invoked vs just sent)
- Implement history compaction when context gets too large
