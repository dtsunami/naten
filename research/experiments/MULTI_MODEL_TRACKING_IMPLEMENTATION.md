# Multi-Model Tracking Implementation

## Overview

Implemented a comprehensive multi-model tracking system that can monitor and differentiate between multiple LLM models (main, reasoning, output, parser, etc.) used by the Agno agent.

## Architecture

### 1. Central Stats Tracker (`model_stats_tracker.py`)

**`ModelStatsTracker` class:**
- Centralized tracking for multiple models
- Each model registers with a type identifier ('main', 'reasoning', 'output', 'parser', etc.)
- Aggregates stats across all models
- Provides per-model and combined breakdowns

**Key methods:**
- `register_model(model_type)` - Register a new model type
- `record_call(model_type, total_tokens, breakdown, output_tokens)` - Record a call
- `get_model_stats(model_type)` - Get stats for specific model
- `get_all_stats()` - Get all models' stats
- `get_total_stats()` - Get aggregated stats across all models
- `get_combined_last_breakdown()` - Combined breakdown from all models' last calls

### 2. Updated Model Interceptor (`model_interceptor.py`)

**Enhanced `ModelInterceptor` class:**
- Now accepts `model_type` parameter to identify which model it's wrapping
- Accepts optional `stats_tracker` for central tracking
- Reports to central tracker after each call
- Shows model type in log banners: `🔍 MODEL INTERCEPTOR [MAIN]: LLM Call #1`

**Enhanced `wrap_model_with_interceptor()` function:**
```python
wrap_model_with_interceptor(
    model,
    max_tokens=128000,
    model_type='main',  # NEW: Identify the model
    stats_tracker=None  # NEW: Optional central tracker
)
```

## Integration with AgnoAgent

### Required Changes in `agno_agent.py`:

```python
# In AgnoAgent.__init__:

# 1. Create central tracker
from .model_stats_tracker import ModelStatsTracker
self.model_stats_tracker = ModelStatsTracker()

# 2. Wrap main model with tracker
from .model_interceptor import wrap_model_with_interceptor
base_llm = AzureOpenAI(...)
self.llm = wrap_model_with_interceptor(
    base_llm,
    max_tokens=self.config.max_tokens or 128000,
    model_type='main',  # Identify as main chat model
    stats_tracker=self.model_stats_tracker  # Pass central tracker
)

# 3. Wrap reasoning model with tracker (if enabled)
if self.config.reasoning_deployment is not None:
    base_reasoning = AzureOpenAI(...)
    self.reasoning = wrap_model_with_interceptor(
        base_reasoning,
        max_tokens=self.config.max_tokens or 128000,
        model_type='reasoning',  # Identify as reasoning model
        stats_tracker=self.model_stats_tracker  # Pass same tracker
    )

# 4. Future: Wrap output/parser models similarly
# if self.config.output_deployment:
#     self.output_model = wrap_model_with_interceptor(
#         base_output,
#         model_type='output',
#         stats_tracker=self.model_stats_tracker
#     )
```

## Benefits

### 1. **Extensibility** ✓
- Easy to add new model types (output, parser, custom)
- Just pass `model_type` parameter when wrapping
- All models report to same central tracker

### 2. **Separation** ✓
- Main model vs reasoning model tokens clearly differentiated
- Each model has its own call count and breakdown
- Can analyze usage patterns per model type

### 3. **Aggregation** ✓
- See total tokens across all models
- Understand combined context window usage
- Identify which model is consuming most tokens

### 4. **Backward Compatibility** ✓
- `stats_tracker` is optional
- Models without tracker work with local stats (current behavior)
- Existing code continues to work

## Usage Examples

### Get Stats for Specific Model

```python
# In context overlay or inspector:
main_stats = agent.model_stats_tracker.get_model_stats('main')
reasoning_stats = agent.model_stats_tracker.get_model_stats('reasoning')

print(f"Main model calls: {main_stats.call_count}")
print(f"Reasoning model calls: {reasoning_stats.call_count}")
```

### Get Combined Stats

```python
total_stats = agent.model_stats_tracker.get_total_stats()
print(f"Total calls across all models: {total_stats['total_calls']}")
print(f"Total input tokens: {total_stats['total_input_tokens']:,}")

# Per-model breakdown
for model_type, breakdown in total_stats['breakdown_by_model'].items():
    print(f"{model_type}: {breakdown['input_tokens']:,} tokens")
```

### Get Combined Last Breakdown

```python
# Get combined breakdown from most recent call of each model
combined = agent.model_stats_tracker.get_combined_last_breakdown()
print(f"Models used: {combined['models_used']}")  # ['main', 'reasoning']
print(f"Total tokens: {combined['total_tokens']:,}")
print(f"System tokens: {combined['system_tokens']:,}")
print(f"Tool tokens: {combined['tool_tokens']:,}")
```

## Context Overlay Integration

### Updated Display Format:

```
================================================================================
📊 CONTEXT WINDOW BREAKDOWN (from actual LLM telemetry)
================================================================================

📈 Multi-Model Statistics:
   Total LLM calls:        3 (2 main + 1 reasoning)
   Total input tokens:     3,455
   Max context (peak):     2,761 tokens (2.2% of 128,000)

📋 Per-Model Breakdown:

   MAIN Model:
      Calls:              2
      Input tokens:       2,618
      Avg per call:       1,309 tokens
      Last breakdown:
        System:           1,395 tokens (53.3%)
        User:                 6 tokens (0.2%)
        Tools:            1,217 tokens (46.5%)

   REASONING Model:
      Calls:              1
      Input tokens:       837
      Avg per call:       837 tokens
      Last breakdown:
        System:           694 tokens (82.9%)
        User:             143 tokens (17.1%)

   COMBINED (last call from each model):
      Total:            3,455 tokens
      System:           2,089 tokens (60.5%)
      User:               149 tokens (4.3%)
      Tools:            1,217 tokens (35.2%)
```

## Files Modified/Created

### Created:
- ✅ `da_code/model_stats_tracker.py` - Central tracking system

### Modified:
- ✅ `da_code/model_interceptor.py` - Added model_type and stats_tracker support

### To Modify (next step):
- ⏭️ `da_code/agno_agent.py` - Create tracker and pass to wrappers
- ⏭️ `da_code/context_inspector.py` - Add methods to access multi-model stats
- ⏭️ `da_code/agno_cli.py` - Update context overlay to show per-model breakdown

## Next Steps

1. Update `agno_agent.py` to create and use the central tracker
2. Update `context_inspector.py` with multi-model accessor methods
3. Update `agno_cli.py` context overlay to show per-model breakdown
4. Test with actual agent calls to verify separation
5. Add to documentation

## Testing Plan

```python
# Test case 1: Main model only
agent = AgnoAgent(session)
agent.arun("Hello")  # Should log: MODEL INTERCEPTOR [MAIN]

# Test case 2: Main + Reasoning
# (with reasoning_deployment configured)
agent.arun("Complex task")  # Should log both [MAIN] and [REASONING]

# Check stats
main_stats = agent.model_stats_tracker.get_model_stats('main')
reasoning_stats = agent.model_stats_tracker.get_model_stats('reasoning')

assert main_stats.call_count >= 1
assert reasoning_stats.call_count >= 1  # If reasoning was used
assert main_stats.total_input_tokens > 0
```

## Extension for Future Models

When Agno adds output_model or parser_model support:

```python
# In agno_agent.py:
if hasattr(self.config, 'output_deployment'):
    base_output = AzureOpenAI(id=self.config.output_deployment, ...)
    self.output_model = wrap_model_with_interceptor(
        base_output,
        max_tokens=self.config.max_tokens or 128000,
        model_type='output',  # NEW model type
        stats_tracker=self.model_stats_tracker  # Same tracker!
    )

# That's it! Everything else just works.
```

The tracker will automatically:
- Register the new model type
- Track its calls separately
- Include it in combined stats
- Show it in context overlay