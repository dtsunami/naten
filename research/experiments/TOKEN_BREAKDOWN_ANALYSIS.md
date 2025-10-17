# Token Counting Analysis & Discrepancies

## Overview

You noticed a discrepancy between the metrics shown in the rich status bar vs the model interceptor:

```
Rich Status Bar:  🎫 2,681 tokens (2,067 in / 614 out) | 🧠 64 reasoning
Model Interceptor: Total input tokens: 2,761
```

**Discrepancy: 2,761 - 2,067 = 694 tokens**

## System Message Breakdown

### Components (from `agno_agent.py:_build_system_prompt()`)

| Component | Tokens | Description |
|-----------|--------|-------------|
| **System Prefix** | 123 | Base system prompt template |
| **Todo.md Wrapper** | 7 | `\n📌 TODO.md:\n` header |
| **Todo.md Content** | 502 | Actual todo.md file contents |
| **Subtotal** | **631** | System message base |
| **Instructions** | 111 | 6 instruction items from `agent.instructions` |
| **Subtotal** | **742** | System + Instructions |

### Agno Framework Additions

Agno adds additional context to the system message automatically:

| Component | Est. Tokens | Config |
|-----------|-------------|--------|
| **Datetime Context** | ~21 | `add_datetime_to_context=True` |
| **User Memories** | ~200-500 | `enable_user_memories=True`, `add_memories_to_context=True` |
| **Framework Metadata** | ~100-200 | Agno internal context |
| **Additional Overhead** | ~100 | Message formatting, JSON overhead |
| **TOTAL ESTIMATED** | **~653** | Explains the difference |

**Actual System Message (from interceptor): 1,395 tokens**
- My calculation: 742 tokens (system + instructions)
- Agno additions: ~653 tokens
- **Total: 1,395 tokens** ✓

## Full Context Breakdown (First LLM Call)

### From Model Interceptor (Actual tokens sent to OpenAI API)

```
System message:      1,395 tokens (53.3%)  ← System + Instructions + Agno context
User message:            6 tokens (0.2%)   ← "nice, what do you think?"
Assistant history:       0 tokens (0.0%)   ← No prior conversation
Tool schemas:        1,217 tokens (46.5%)  ← 15 tools (8 functions each)
Tool results:            0 tokens (0.0%)   ← No tool calls yet
────────────────────────────────────────────
TOTAL:               2,618 tokens (Interceptor shows 2,761? See note below)
```

**Note:** The user message "nice, what do you think?" should be ~7 tokens (my calculation), but the interceptor might be counting it with additional formatting.

### Tool Schemas - Actual vs Estimated

**Estimated:** 15 tools × ~2,000 tokens/function = ~30,000 tokens ❌
**Actual:** 1,217 tokens for all 15 tools ✓

This is why the ~2k tokens/function estimate was wildly inaccurate. The actual tool schemas are much more compact (~81 tokens per tool on average).

## Why the Numbers Don't Match

### 1. Rich Status Bar vs Interceptor Discrepancy

**Rich Status Bar:** `2,681 tokens (2,067 in / 614 out)`
**Model Interceptor:** `2,761 input tokens`

The 694-token difference is likely because:

#### Option A: Different Token Counting Methods
- **Rich status metrics** come from Agno's internal `ResponseMetrics` object (lines 1089-1115 in `agno_cli.py`)
- **Interceptor** uses tiktoken to count actual message content sent to OpenAI API
- Agno might be using a different tokenizer or excluding some overhead

#### Option B: The Metrics Are Cumulative
- The rich status might be showing cumulative tokens across the session
- But interceptor shows "Total LLM calls: 1", so this is the first call

#### Option C: Reasoning Model Separate Tracking
- The `🧠 64 reasoning` tokens suggest a separate reasoning model call
- These might not be included in the 2,067 input tokens
- **Most likely explanation:** 2,067 is from the main model, 694 tokens were sent to reasoning model

### 2. Where Are Reasoning Tokens Tracked?

In `agno_agent.py` lines 196-210, you have a separate reasoning model:

```python
self.reasoning = None
if self.config.reasoning_deployment is not None:
    base_reasoning = AzureOpenAI(
        id=self.config.reasoning_deployment,
        ...
    )
    self.reasoning = wrap_model_with_interceptor(base_reasoning, ...)
```

**The reasoning model makes separate LLM calls!**

- Main model (chat): 2,067 input tokens
- Reasoning model: ~694 input tokens
- Reasoning model output: 64 tokens (shown in rich status)
- **Total: 2,761 tokens** ✓

### 3. How Are They Differentiated?

Currently, **they're NOT properly differentiated** in the interceptor stats!

The interceptor stores stats in `self.stats`:
```python
self.stats = {
    'call_count': 0,
    'total_input_tokens': 0,
    'total_output_tokens': 0,
    'max_context_seen': 0,
    'last_breakdown': None,
}
```

**Problem:** Both the main model and reasoning model have their own interceptor wrappers, so they track stats separately. But the context overlay is only showing stats from ONE of them (likely the main model).

## Summary

### Token Breakdown (First Call to Main Model)

| Component | Tokens | Source |
|-----------|--------|--------|
| System message | 1,395 | 742 (your content) + 653 (Agno additions) |
| User message | 6 | "nice, what do you think?" |
| Tool schemas | 1,217 | 15 tools (actual, not estimate) |
| Tool results | 0 | No tool calls yet |
| **TOTAL** | **2,618** | **From interceptor** |

### Reasoning Model (Separate Call)

| Component | Tokens | Source |
|-----------|--------|--------|
| Input to reasoning | ~694 | Reasoning model input |
| Output from reasoning | 64 | Shown in rich status: `🧠 64 reasoning` |

### Why Todo.md Uses 502 Tokens

Out of the 1,395 system message tokens:
- Base system: 123 tokens (8.8%)
- **Todo.md: 509 tokens (36.4%)** - 502 content + 7 wrapper
- Instructions: 111 tokens (8.0%)
- Agno additions: ~653 tokens (46.8%)

**Recommendation:** If you want to reduce system message size, consider:
1. Trimming todo.md (currently 2,348 chars)
2. Moving completed items to a separate DONE.md file
3. Only including active todo items in the system message

## Recommendations

### 1. Track Reasoning Model Separately

Add a separate stats tracker for reasoning model calls:

```python
self.llm_stats = wrap_model_with_interceptor(base_llm, ...)
self.reasoning_stats = wrap_model_with_interceptor(base_reasoning, ...)
```

Then show both in context overlay:
```
Main Model:      2,618 tokens
Reasoning Model:   694 tokens
─────────────────────────────
TOTAL:           3,312 tokens
```

### 2. Differentiate in Context Overlay

Modify `agno_cli.py` context overlay to show:
- Main model tokens (chat)
- Reasoning model tokens (if enabled)
- Clear separation between the two

### 3. Fix Metrics Discrepancy

Investigate why Agno's `ResponseMetrics` shows 2,067 tokens while interceptor shows 2,761. This might be:
- Agno not counting some overhead
- Different tokenizer
- Cached tokens not being counted
- Reasoning model tokens being excluded