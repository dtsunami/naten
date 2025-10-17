# Context Overlay - Next Steps

## Current State (COMPLETED ✅)

Successfully implemented **Option 3: Progress Bar Style** context overlay for the `#` key binding in `da_code/agno_cli.py` (lines 605-717).

### What Works:
- Clean progress bar visualization with 50-char width main bar
- Color-coded status: green (<50%), yellow (<70%), red (≥70%)
- Component breakdown with mini bars: System, History, Tools, User
- Azure billing integration showing billed tokens & reasoning tokens
- Tool summary (# toolkits, # functions sent)
- Pre-call estimate panel when no LLM calls made yet

### Example Output:
```
📊 Context Window: 5,198 / 128,000 tokens
██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 4.1%

System   ██████████░░░░░░░░░░░░░░░░░░░░  1,856 (35.7%)
History  █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    257 ( 4.9%)
Tools    ███████░░░░░░░░░░░░░░░░░░░░░░░  1,217 (23.4%)
User     ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░      6 ( 0.1%)

💰 Billing:
   Billed:  2,648 tokens
   Reason:  256 tokens (internal CoT)

🔧 Tools: 5 toolkits, 15 functions sent
```

## TODO #1: Fix Cached Tokens Display 🐛

### Problem:
The "Cached" line is missing from the billing section even though prompt caching IS working:
- **Interceptor shows**: 5,198 tokens sent
- **Azure billed**: 2,648 tokens
- **Implicit caching**: ~2,550 tokens cached (difference between sent and billed)
- **But**: `cache_read_tokens` field returns 0 or None

### Investigation Needed:
1. **Check Azure API response structure** - the field name might be different:
   - Could be `cached_tokens`, `cache_tokens`, `prompt_cache_tokens`, etc.
   - May be nested under a different object

2. **Debug location**: `da_code/agno_cli.py` lines 684-701
   ```python
   azure_cached = getattr(azure_metrics, 'cache_read_tokens', 0) or 0
   ```

3. **Add debug logging** to see what fields ARE available:
   ```python
   logger.warning(f"Azure metrics object: {dir(azure_metrics)}")
   logger.warning(f"Azure metrics dict: {vars(azure_metrics) if hasattr(azure_metrics, '__dict__') else 'N/A'}")
   ```

4. **Check Agno framework** - look at `agno.agent.Agent.get_session_metrics()`:
   - File: Agno library source (likely in site-packages)
   - May need to check how Agno fetches metrics from Azure OpenAI API
   - Azure OpenAI API docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/reference

5. **Alternative approach**: Calculate cached tokens ourselves:
   ```python
   # If we can't get it from Azure, calculate it
   from da_code.context_telemetry import get_multi_model_stats
   multi_model_stats = get_multi_model_stats(agent)
   total_sent = sum(s.total_input_tokens for s in multi_model_stats.values())
   azure_billed = azure_metrics.input_tokens
   calculated_cached = total_sent - azure_billed
   ```

### Expected Fix:
Once we find the correct field, update line 690 in `agno_cli.py`:
```python
azure_cached = getattr(azure_metrics, 'CORRECT_FIELD_NAME', 0) or 0
```

Then the output should show:
```
💰 Billing:
   Billed:  2,648 tokens
   Cached:  2,550 tokens (49% saved)  ← THIS LINE SHOULD APPEAR
   Reason:  256 tokens (internal CoT)
```

---

## TODO #2: Add Drill-Down/Action Capabilities 🎯

### User Request:
> "I do like the drill-down/action capability for context management"

### Proposed Features:

#### Feature A: Per-Toolkit Breakdown
**Trigger**: Press `#` then `t` (or just make `##` show detailed view)

**Display**:
```
🔧 Tool Breakdown:
   TodoTool        ███████░░░░  3 functions,   ~402 tokens  [d to disable]
   CommandTool     ███████░░░░  2 functions,   ~287 tokens  [d to disable]
   FileTool        ████████░░░  4 functions,   ~328 tokens  [d to disable]
   HttpTool        ██░░░░░░░░░  1 function,    ~200 tokens  [d to disable]
   MCPTool         ░░░░░░░░░░░  5 functions,   ~150 tokens  [enabled]
```

#### Feature B: Interactive Context Management
**Trigger**: Press `#` then `m` (manage)

**Actions**:
- Disable/enable individual toolkits
- Clear chat history
- Show per-model breakdown (main vs reasoning)
- Export context snapshot

**Implementation**: Use prompt_toolkit to create interactive menu

#### Feature C: Context History Graph
**Trigger**: Press `#` then `h` (history)

**Display**: ASCII graph showing token usage over last N calls
```
Context Usage History (last 10 calls):
  8k │     ┌─┐
  6k │   ┌─┘ └─┐
  4k │ ┌─┘     └─┐  ← Current
  2k │─┘         └────────
     └─────────────────────
```

### Implementation Plan:

1. **Add key binding handler for `##`** (double-press #):
   ```python
   # In agno_cli.py, after the # binding
   # Track last keypress timestamp to detect double-press
   last_hash_press = [0.0]  # Mutable

   @bindings.add('#')
   def _(event):
       import time
       now = time.time()
       if now - last_hash_press[0] < 0.5:  # Double-press within 500ms
           show_detailed_context_overlay(agent, console)
       else:
           show_context_overlay(agent, console)  # Current implementation
       last_hash_press[0] = now
   ```

2. **Create interactive menu**:
   ```python
   def show_context_management_menu(agent, console):
       from rich.prompt import Prompt
       from rich.table import Table

       # Show options
       table = Table(title="Context Management")
       table.add_column("Key", style="cyan")
       table.add_column("Action")

       table.add_row("t", "Toggle toolkit on/off")
       table.add_row("c", "Clear history")
       table.add_row("e", "Export snapshot")
       table.add_row("q", "Quit")

       console.print(table)

       # Get user choice (this is tricky in async context!)
       # May need to integrate with main input loop
   ```

3. **Toolkit management functions**:
   ```python
   from da_code.context_telemetry import ContextManager

   def toggle_toolkit(agent, toolkit_name):
       mgr = ContextManager(agent)
       # Check if enabled
       if toolkit_name in mgr._disabled_tools:
           mgr.enable_tools([toolkit_name])
           console.print(f"[green]✓ Enabled {toolkit_name}[/green]")
       else:
           mgr.disable_tools([toolkit_name])
           console.print(f"[yellow]⚠ Disabled {toolkit_name}[/yellow]")
   ```

### Technical Considerations:
- **Async context**: The key bindings run in prompt_toolkit's event loop, need to be careful with blocking operations
- **State management**: Need to track which view is active (simple overlay vs detailed)
- **User experience**: Keep it simple and fast - don't make users navigate complex menus

---

## Files Modified:
- ✅ `da_code/agno_cli.py` - lines 605-717 (# key binding)
- ✅ Deleted `context_overlay_new.py` (standalone prototype)

## Related Files:
- `da_code/context_telemetry.py` - Token tracking and model interceptor
- `da_code/token_estimator.py` - Pre-call token estimation
- `da_code/agno_agent.py` - Agent setup with ModelInterceptor wrapping

## Testing:
After changes, test by:
1. Start da_code session
2. Make a request (any request)
3. Press `#` (Shift+3) to see overlay
4. Check that cached tokens appear in billing section
5. Test drill-down features if implemented

---

## User Feedback:
> "well balls, this actually looks awesome af"

✨ The progress bar design is solid - focus on fixing the caching display and adding drill-down features!
