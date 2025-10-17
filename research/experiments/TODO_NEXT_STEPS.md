# Next Steps for Multi-Model Tracking

## ✅ Completed

1. **Created `model_stats_tracker.py`** - Central tracking system
   - `ModelStatsTracker` class for multi-model tracking
   - Supports unlimited model types (main, reasoning, output, parser, custom)
   - Aggregates stats across all models
   - Provides per-model and combined breakdowns

2. **Updated `model_interceptor.py`** - Added multi-model support
   - Added `model_type` parameter to identify each model
   - Added `stats_tracker` parameter for central reporting
   - Reports to tracker after each call
   - Shows model type in log banners

3. **Created documentation**
   - `MULTI_MODEL_TRACKING_IMPLEMENTATION.md` - Full implementation guide
   - `EXPERIMENT_RESULTS.md` - Token estimation experiments
   - `TOKEN_BREAKDOWN_ANALYSIS.md` - Discrepancy explanations

## ⏭️ Remaining Tasks

### 1. Update `agno_agent.py` (Lines 178-210)

```python
# Add import at top
from .model_stats_tracker import ModelStatsTracker

# In __init__, before wrapping models:
# Create central tracker for all models
self.model_stats_tracker = ModelStatsTracker()

# Update main model wrapping:
self.llm = wrap_model_with_interceptor(
    base_llm,
    max_tokens=self.config.max_tokens or 128000,
    model_type='main',  # ADD THIS
    stats_tracker=self.model_stats_tracker  # ADD THIS
)

# Update reasoning model wrapping (if exists):
if self.config.reasoning_deployment is not None:
    ...
    self.reasoning = wrap_model_with_interceptor(
        base_reasoning,
        max_tokens=self.config.max_tokens or 128000,
        model_type='reasoning',  # ADD THIS
        stats_tracker=self.model_stats_tracker  # ADD THIS
    )
```

### 2. Update `context_inspector.py`

Add new functions to access multi-model stats:

```python
def get_multi_model_stats(agent):
    """Get stats from all models."""
    if not hasattr(agent, 'model_stats_tracker'):
        return None
    return agent.model_stats_tracker.get_all_stats()

def get_model_breakdown(agent, model_type='main'):
    """Get breakdown for specific model."""
    if not hasattr(agent, 'model_stats_tracker'):
        return None
    return agent.model_stats_tracker.get_last_call_breakdown(model_type)

def get_combined_breakdown(agent):
    """Get combined breakdown from all models."""
    if not hasattr(agent, 'model_stats_tracker'):
        return None
    return agent.model_stats_tracker.get_combined_last_breakdown()
```

### 3. Update `agno_cli.py` Context Overlay

Modify the context overlay to show per-model breakdown:

```python
# Around line 630, add multi-model section:

if hasattr(agent, 'model_stats_tracker'):
    total_stats = agent.model_stats_tracker.get_total_stats()

    console.print(f"\n[bold]📊 Multi-Model Statistics:[/bold]")
    console.print(f"   Total LLM calls:        {total_stats['total_calls']}")
    console.print(f"   Total input tokens:     {total_stats['total_input_tokens']:,}")

    # Show per-model breakdown
    console.print(f"\n[bold]📋 Per-Model Breakdown:[/bold]")
    for model_type, breakdown in total_stats['breakdown_by_model'].items():
        if breakdown['calls'] > 0:
            console.print(f"\n   [cyan]{model_type.upper()}[/cyan] Model:")
            console.print(f"      Calls:              {breakdown['calls']}")
            console.print(f"      Input tokens:       {breakdown['input_tokens']:,}")
            console.print(f"      Avg per call:       {breakdown['avg_input']:,} tokens")

            # Show last breakdown for this model
            last_breakdown = agent.model_stats_tracker.get_last_call_breakdown(model_type)
            if last_breakdown:
                console.print(f"      Last call breakdown:")
                console.print(f"        System:           {last_breakdown['system_tokens']:,} tokens")
                console.print(f"        User:             {last_breakdown['user_tokens']:,} tokens")
                console.print(f"        Assistant:        {last_breakdown['assistant_tokens']:,} tokens")
                console.print(f"        Tools:            {last_breakdown['tool_tokens']:,} tokens")
```

### 4. Update `todo.md`

Mark the multi-model tracking task as complete:

```markdown
- [x] Track reasoning model separately in interceptor and context overlay (show main model vs reasoning model tokens separately) - **DONE: Implemented ModelStatsTracker with extensible multi-model support**
```

## Testing Checklist

- [ ] Test with main model only (no reasoning)
- [ ] Test with main + reasoning model
- [ ] Verify stats show separately for each model
- [ ] Verify combined stats are correct
- [ ] Test context overlay shows per-model breakdown
- [ ] Test with future models (output, parser) when available

## Benefits Summary

✓ **Extensible** - Easy to add new model types
✓ **Separated** - Each model tracked independently
✓ **Aggregated** - Can see combined usage
✓ **Backward Compatible** - Optional tracker parameter
✓ **Future-Proof** - Ready for output_model, parser_model, etc.

## Quick Reference

**Files to modify:**
1. `da_code/agno_agent.py` (lines ~178-210)
2. `da_code/context_inspector.py` (add new functions)
3. `da_code/agno_cli.py` (update context overlay ~line 630)
4. `todo.md` (mark task complete)

**Total estimated time:** 15-20 minutes for all updates + testing
