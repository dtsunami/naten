"""Context telemetry and tracking for LLM token usage.

This module provides comprehensive telemetry for tracking and analyzing
token usage across multiple LLM models (main, reasoning, output, parser, etc.).

Key components:
1. ModelStatsTracker - Centralized tracking for multiple models
2. ModelInterceptor - Wraps models to capture actual token usage
3. ContextManager - Manages and optimizes agent context
4. Helper functions - Access stats and manage context

The interceptor provides ACTUAL token counts from real LLM calls (not estimates).
"""

import logging
import json
import tiktoken
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class ModelCallStats:
    """Statistics for a single model call."""
    model_type: str  # 'main', 'reasoning', 'output', 'parser', etc.
    timestamp: datetime
    total_tokens: int
    system_tokens: int
    user_tokens: int
    assistant_tokens: int
    tool_tokens: int
    tool_result_tokens: int
    tool_count: int


@dataclass
class ModelStats:
    """Aggregated statistics for a specific model."""
    model_type: str
    call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    max_context_seen: int = 0
    last_breakdown: Optional[Dict[str, Any]] = None
    call_history: List[ModelCallStats] = field(default_factory=list)


@dataclass
class ContextStats:
    """Context usage statistics from model interceptor."""
    call_count: int
    total_input_tokens: int
    max_context_seen: int
    avg_context: int
    last_breakdown: Optional[Dict[str, Any]] = None


# ============================================================================
# ModelStatsTracker - Centralized tracking for multiple models
# ============================================================================

class ModelStatsTracker:
    """
    Centralized tracker for multiple LLM models.

    Supports tracking stats from:
    - main: Primary chat model
    - reasoning: Reasoning model (o1/o3)
    - output: Output/response model
    - parser: Parsing/structured output model
    - Any custom model types
    """

    def __init__(self):
        """Initialize the stats tracker."""
        self.models: Dict[str, ModelStats] = {}
        self._lock = None  # For thread safety if needed

        logger.info("🎯 ModelStatsTracker initialized - Ready to track multiple models")

    def register_model(self, model_type: str) -> None:
        """
        Register a new model type for tracking.

        Args:
            model_type: Type identifier (e.g., 'main', 'reasoning', 'output', 'parser')
        """
        if model_type not in self.models:
            self.models[model_type] = ModelStats(model_type=model_type)
            logger.info(f"📊 Registered model type: '{model_type}'")

    def record_call(
        self,
        model_type: str,
        total_tokens: int,
        breakdown: Dict[str, int],
        output_tokens: int = 0
    ) -> None:
        """
        Record a call from a specific model.

        Args:
            model_type: Model type identifier
            total_tokens: Total input tokens for this call
            breakdown: Token breakdown dict with keys:
                - system_tokens
                - user_tokens
                - assistant_tokens
                - tool_tokens
                - tool_result_tokens
                - tool_count
            output_tokens: Output tokens generated (if available)
        """
        # Auto-register if not registered
        if model_type not in self.models:
            self.register_model(model_type)

        stats = self.models[model_type]

        # Update counters
        stats.call_count += 1
        stats.total_input_tokens += total_tokens
        stats.total_output_tokens += output_tokens
        stats.max_context_seen = max(stats.max_context_seen, total_tokens)

        # Store last breakdown
        stats.last_breakdown = breakdown.copy()

        # Record call in history
        call_stat = ModelCallStats(
            model_type=model_type,
            timestamp=datetime.now(),
            total_tokens=total_tokens,
            system_tokens=breakdown.get('system_tokens', 0),
            user_tokens=breakdown.get('user_tokens', 0),
            assistant_tokens=breakdown.get('assistant_tokens', 0),
            tool_tokens=breakdown.get('tool_tokens', 0),
            tool_result_tokens=breakdown.get('tool_result_tokens', 0),
            tool_count=breakdown.get('tool_count', 0)
        )
        stats.call_history.append(call_stat)

        logger.debug(f"📊 Recorded {model_type} model call #{stats.call_count}: {total_tokens:,} tokens")

    def get_model_stats(self, model_type: str) -> Optional[ModelStats]:
        """
        Get stats for a specific model.

        Args:
            model_type: Model type identifier

        Returns:
            ModelStats or None if model not registered
        """
        return self.models.get(model_type)

    def get_all_stats(self) -> Dict[str, ModelStats]:
        """
        Get stats for all registered models.

        Returns:
            Dictionary mapping model type to ModelStats
        """
        return self.models.copy()

    def get_total_stats(self) -> Dict[str, Any]:
        """
        Get aggregated stats across all models.

        Returns:
            Dictionary with combined statistics
        """
        total_calls = sum(s.call_count for s in self.models.values())
        total_input = sum(s.total_input_tokens for s in self.models.values())
        total_output = sum(s.total_output_tokens for s in self.models.values())
        max_context = max((s.max_context_seen for s in self.models.values()), default=0)

        return {
            'total_calls': total_calls,
            'total_input_tokens': total_input,
            'total_output_tokens': total_output,
            'max_context_seen': max_context,
            'models_active': list(self.models.keys()),
            'breakdown_by_model': {
                model_type: {
                    'calls': stats.call_count,
                    'input_tokens': stats.total_input_tokens,
                    'output_tokens': stats.total_output_tokens,
                    'max_context': stats.max_context_seen,
                    'avg_input': stats.total_input_tokens // stats.call_count if stats.call_count > 0 else 0
                }
                for model_type, stats in self.models.items()
            }
        }

    def get_last_call_breakdown(self, model_type: str = 'main') -> Optional[Dict[str, Any]]:
        """
        Get the last call breakdown for a specific model.

        Args:
            model_type: Model type (default: 'main')

        Returns:
            Last breakdown dict or None
        """
        stats = self.get_model_stats(model_type)
        return stats.last_breakdown if stats else None

    def get_combined_last_breakdown(self) -> Dict[str, Any]:
        """
        Get combined breakdown from the most recent call of each model.

        Returns:
            Combined breakdown showing tokens from all models
        """
        combined = {
            'system_tokens': 0,
            'user_tokens': 0,
            'assistant_tokens': 0,
            'tool_tokens': 0,
            'tool_result_tokens': 0,
            'total_tokens': 0,
            'tool_count': 0,
            'models_used': []
        }

        for model_type, stats in self.models.items():
            if stats.last_breakdown:
                combined['models_used'].append(model_type)
                for key in ['system_tokens', 'user_tokens', 'assistant_tokens',
                           'tool_tokens', 'tool_result_tokens', 'total_tokens']:
                    combined[key] += stats.last_breakdown.get(key, 0)

                # Use max tool count (they're probably the same)
                combined['tool_count'] = max(
                    combined['tool_count'],
                    stats.last_breakdown.get('tool_count', 0)
                )

        return combined

    def reset_stats(self, model_type: Optional[str] = None) -> None:
        """
        Reset stats for a specific model or all models.

        Args:
            model_type: Model type to reset, or None to reset all
        """
        if model_type:
            if model_type in self.models:
                self.models[model_type] = ModelStats(model_type=model_type)
                logger.info(f"🔄 Reset stats for '{model_type}' model")
        else:
            self.models.clear()
            logger.info("🔄 Reset stats for all models")

    def log_summary(self, max_tokens: int = 128000) -> None:
        """
        Log a summary of all model stats.

        Args:
            max_tokens: Maximum context window for percentage calculations
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 MULTI-MODEL STATS SUMMARY")
        logger.info(f"{'='*80}")

        total_stats = self.get_total_stats()

        logger.info(f"\n🎯 Overall Statistics:")
        logger.info(f"   Total LLM calls:     {total_stats['total_calls']}")
        logger.info(f"   Total input tokens:  {total_stats['total_input_tokens']:,}")
        logger.info(f"   Total output tokens: {total_stats['total_output_tokens']:,}")
        logger.info(f"   Max context (call):  {total_stats['max_context_seen']:,} ({total_stats['max_context_seen']/max_tokens*100:.1f}% of {max_tokens:,})")

        logger.info(f"\n📋 Per-Model Breakdown:")
        for model_type, breakdown in total_stats['breakdown_by_model'].items():
            logger.info(f"\n   {model_type.upper()} Model:")
            logger.info(f"      Calls:       {breakdown['calls']}")
            logger.info(f"      Input:       {breakdown['input_tokens']:,} tokens")
            logger.info(f"      Output:      {breakdown['output_tokens']:,} tokens")
            logger.info(f"      Max context: {breakdown['max_context']:,} tokens")
            logger.info(f"      Avg input:   {breakdown['avg_input']:,} tokens/call")

        logger.info(f"\n{'='*80}\n")


# ============================================================================
# ModelInterceptor - Wrap models to capture actual token usage
# ============================================================================

class ModelInterceptor:
    """Wraps an Agno model to intercept and log messages sent to LLM."""

    def __init__(
        self,
        model,
        max_tokens: int = 128000,
        model_type: str = 'main',
        stats_tracker: Optional[ModelStatsTracker] = None
    ):
        """
        Initialize interceptor.

        Args:
            model: The Agno model to wrap
            max_tokens: Maximum context window (default 128k)
            model_type: Type identifier for this model ('main', 'reasoning', 'output', 'parser', etc.)
            stats_tracker: Optional centralized stats tracker (creates local one if not provided)
        """
        self.model = model
        self.max_tokens = max_tokens
        self.model_type = model_type

        # Use provided tracker or create local stats
        self.stats_tracker = stats_tracker
        if stats_tracker:
            stats_tracker.register_model(model_type)

        # Get model info for verification
        model_id = getattr(model, 'id', 'gpt-4')
        model_type_name = type(model).__name__

        # Get tiktoken encoder
        try:
            self.encoding = tiktoken.encoding_for_model(model_id)
            logger.debug(f"\n{'🔥'*40}")
            logger.debug(f"✅ MODEL INTERCEPTOR INITIALIZED")
            logger.debug(f"{'🔥'*40}")
            logger.debug(f"   Model Type:     {model_type_name}")
            logger.debug(f"   Model ID:       {model_id}")
            logger.debug(f"   Max Tokens:     {max_tokens:,}")
            logger.debug(f"   Encoding:       {self.encoding.name}")
            logger.debug(f"   Wrapper Status: ACTIVE - Will intercept all LLM calls")
            logger.debug(f"{'🔥'*40}\n")
        except Exception as e:
            self.encoding = tiktoken.get_encoding("cl100k_base")
            logger.debug(f"\n{'🔥'*40}")
            logger.debug(f"⚠️  MODEL INTERCEPTOR INITIALIZED (fallback encoding)")
            logger.debug(f"{'🔥'*40}")
            logger.debug(f"   Model Type:     {model_type_name}")
            logger.debug(f"   Model ID:       {model_id}")
            logger.debug(f"   Max Tokens:     {max_tokens:,}")
            logger.debug(f"   Encoding:       cl100k_base (fallback)")
            logger.debug(f"   Warning:        Could not get encoding for {model_id}: {e}")
            logger.debug(f"   Wrapper Status: ACTIVE - Will intercept all LLM calls")
            logger.debug(f"{'🔥'*40}\n")

        # Track stats
        self.stats = {
            'call_count': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'max_context_seen': 0,
            'last_breakdown': None,  # Store actual breakdown from last call
        }

    def _log_messages(self, messages: List[Any], tools: Any = None, **kwargs) -> None:
        """Log messages before sending to LLM."""
        try:
            # Quick safety check
            if not messages:
                logger.warning("⚠️  No messages to log")
                return
            self.stats['call_count'] += 1
            call_num = self.stats['call_count']

            logger.info(f"\n{'='*80}")
            logger.info(f"🔍 MODEL INTERCEPTOR [{self.model_type.upper()}]: LLM Call #{call_num}")
            logger.info(f"{'='*80}")

            # Analyze messages
            total_tokens = 0
            breakdown = {
                'system': {'tokens': 0, 'count': 0, 'preview': ''},
                'user': {'tokens': 0, 'count': 0, 'preview': ''},
                'assistant': {'tokens': 0, 'count': 0, 'preview': ''},
                'tool': {'tokens': 0, 'count': 0, 'schemas': []},
                'tool_result': {'tokens': 0, 'count': 0},
            }

            # Convert messages to dicts if they're Message objects
            msg_dicts = []
            for msg in messages:
                if hasattr(msg, 'to_dict'):
                    msg_dict = msg.to_dict()
                elif hasattr(msg, 'model_dump'):
                    msg_dict = msg.model_dump()
                elif isinstance(msg, dict):
                    msg_dict = msg
                else:
                    msg_dict = {
                        'role': getattr(msg, 'role', 'unknown'),
                        'content': str(getattr(msg, 'content', ''))
                    }
                msg_dicts.append(msg_dict)

            # Analyze each message
            for msg in msg_dicts:
                role = msg.get('role', 'unknown')
                content = str(msg.get('content', ''))

                # Count content tokens
                if content:
                    content_tokens = len(self.encoding.encode(content))
                    total_tokens += content_tokens

                    # Track by role
                    if role == 'system':
                        breakdown['system']['tokens'] += content_tokens
                        breakdown['system']['count'] += 1
                        if not breakdown['system']['preview']:
                            breakdown['system']['preview'] = content[:200]

                    elif role == 'user':
                        breakdown['user']['tokens'] += content_tokens
                        breakdown['user']['count'] += 1
                        if not breakdown['user']['preview']:
                            breakdown['user']['preview'] = content[:200]

                    elif role == 'assistant':
                        breakdown['assistant']['tokens'] += content_tokens
                        breakdown['assistant']['count'] += 1
                        if not breakdown['assistant']['preview']:
                            breakdown['assistant']['preview'] = content[:200]

                    elif role == 'tool':
                        breakdown['tool_result']['tokens'] += content_tokens
                        breakdown['tool_result']['count'] += 1

            # Count tool schemas
            if tools:
                try:
                    # Tools can be a list or dict
                    if isinstance(tools, list):
                        tool_str = json.dumps(tools, default=str)
                        tool_tokens = len(self.encoding.encode(tool_str))
                        breakdown['tool']['tokens'] = tool_tokens
                        breakdown['tool']['count'] = len(tools)
                        breakdown['tool']['schemas'] = [
                            t.get('function', {}).get('name', str(t.get('name', 'unknown')))
                            for t in tools[:10]
                        ]
                        total_tokens += tool_tokens
                    else:
                        logger.debug(f"Tools is not a list: {type(tools)}")
                except Exception as e:
                    logger.debug(f"Could not analyze tools: {e}")

            # Update stats
            self.stats['total_input_tokens'] += total_tokens
            self.stats['max_context_seen'] = max(self.stats['max_context_seen'], total_tokens)

            # Store breakdown for context overlay
            self.stats['last_breakdown'] = {
                'system_tokens': breakdown['system']['tokens'],
                'user_tokens': breakdown['user']['tokens'],
                'assistant_tokens': breakdown['assistant']['tokens'],
                'tool_tokens': breakdown['tool']['tokens'],
                'tool_result_tokens': breakdown['tool_result']['tokens'],
                'total_tokens': total_tokens,
                'tool_count': breakdown['tool']['count'],
            }

            # Calculate percentages
            usage_pct = (total_tokens / self.max_tokens) * 100

            # Log breakdown
            logger.info(f"\n📊 Token Breakdown (Call #{call_num}):")
            logger.info(f"   System messages:     {breakdown['system']['tokens']:>7,} tokens ({breakdown['system']['count']} msgs)")
            logger.info(f"   User messages:       {breakdown['user']['tokens']:>7,} tokens ({breakdown['user']['count']} msgs)")
            logger.info(f"   Assistant history:   {breakdown['assistant']['tokens']:>7,} tokens ({breakdown['assistant']['count']} msgs)")
            logger.info(f"   Tool schemas:        {breakdown['tool']['tokens']:>7,} tokens ({breakdown['tool']['count']} tools)")
            logger.info(f"   Tool results:        {breakdown['tool_result']['tokens']:>7,} tokens ({breakdown['tool_result']['count']} msgs)")
            logger.info(f"   {'─'*60}")
            logger.info(f"   TOTAL CONTEXT:       {total_tokens:>7,} tokens ({usage_pct:.1f}% of {self.max_tokens:,})")

            # Show tool schemas if present
            if breakdown['tool']['schemas']:
                logger.info(f"\n🔧 Tools Sent to LLM ({breakdown['tool']['count']} total):")
                for tool_name in breakdown['tool']['schemas']:
                    logger.info(f"   • {tool_name}")
                if breakdown['tool']['count'] > 10:
                    logger.info(f"   ... and {breakdown['tool']['count'] - 10} more")

            # Show message previews
            if breakdown['system']['preview']:
                logger.info(f"\n💬 System Message Preview:")
                logger.info(f"   {breakdown['system']['preview'][:150]}...")

            if breakdown['user']['preview']:
                logger.info(f"\n💬 User Message Preview:")
                logger.info(f"   {breakdown['user']['preview'][:150]}...")

            # Warnings
            logger.info(f"\n⚠️  Context Usage Analysis:")
            if usage_pct > 70:
                logger.warning(f"   ⚠️  HIGH USAGE: {usage_pct:.1f}% of context window!")
                remaining = self.max_tokens - total_tokens
                logger.warning(f"   Only {remaining:,} tokens remaining for response")

            if breakdown['tool']['tokens'] > 40000:
                logger.warning(f"   ⚠️  TOOL SCHEMAS: {breakdown['tool']['tokens']:,} tokens ({breakdown['tool']['tokens']/total_tokens*100:.1f}%)")
                logger.warning(f"   Consider disabling unused tools")

            if breakdown['assistant']['tokens'] > 30000:
                logger.warning(f"   ⚠️  CHAT HISTORY: {breakdown['assistant']['tokens']:,} tokens ({breakdown['assistant']['tokens']/total_tokens*100:.1f}%)")
                logger.warning(f"   Consider reducing num_history_runs")

            if not any([usage_pct > 70, breakdown['tool']['tokens'] > 40000, breakdown['assistant']['tokens'] > 30000]):
                logger.info(f"   ✅ Context usage is reasonable")

            # Cumulative stats
            logger.info(f"\n📈 Cumulative Stats:")
            logger.info(f"   Total LLM calls:     {self.stats['call_count']}")
            logger.info(f"   Total input tokens:  {self.stats['total_input_tokens']:,}")
            logger.info(f"   Max context (call):  {self.stats['max_context_seen']:,}")
            logger.info(f"   Avg context (call):  {self.stats['total_input_tokens'] // self.stats['call_count']:,}")

            logger.info(f"{'='*80}\n")

            # Report to central tracker if available
            if self.stats_tracker:
                self.stats_tracker.record_call(
                    model_type=self.model_type,
                    total_tokens=total_tokens,
                    breakdown=self.stats['last_breakdown'],
                    output_tokens=0  # Will be updated when we track output
                )

        except Exception as e:
            logger.error(f"❌ Model interceptor error: {e}", exc_info=True)

    def response(self, messages: List[Any], **kwargs) -> Any:
        """Intercept synchronous response call."""
        logger.debug(f"\n{'🎯'*40}")
        logger.debug(f"🎯 INTERCEPTED: Synchronous LLM call (response)")
        logger.debug(f"{'🎯'*40}")

        # Log messages (tools is in kwargs)
        self._log_messages(messages, **kwargs)

        # Call original model
        logger.info(f"📤 Sending {len(messages)} messages to actual LLM model...")
        result = self.model.response(messages, **kwargs)
        logger.debug(f"✅ LLM call completed successfully\n")

        return result

    async def aresponse(self, messages: List[Any], **kwargs) -> Any:
        """Intercept async response call."""
        logger.debug(f"\n{'🎯'*40}")
        logger.debug(f"🎯 INTERCEPTED: Async LLM call (aresponse)")
        logger.debug(f"{'🎯'*40}")

        # Log messages (tools is in kwargs)
        self._log_messages(messages, **kwargs)

        # Call original model
        logger.info(f"📤 Sending {len(messages)} messages to actual LLM model (async)...")
        result = await self.model.aresponse(messages, **kwargs)
        logger.debug(f"✅ Async LLM call completed successfully\n")

        return result

    async def aresponse_stream(self, messages: List[Any], **kwargs):
        """Intercept async streaming response call."""
        try:
            logger.debug(f"\n{'🎯'*40}")
            logger.debug(f"🎯 INTERCEPTED: Async STREAMING LLM call (aresponse_stream)")
            logger.debug(f"{'🎯'*40}")

            # Log messages before streaming starts (tools is in kwargs)
            self._log_messages(messages, **kwargs)

            # Call original model and stream results
            logger.info(f"📤 Starting stream: {len(messages)} messages to LLM...")

            # Stream chunks from the underlying model
            async for chunk in self.model.aresponse_stream(messages, **kwargs):
                yield chunk

            logger.debug(f"✅ Streaming LLM call completed\n")

        except Exception as e:
            logger.error(f"❌ Error in streaming interceptor: {e}", exc_info=True)
            # Re-raise to let Agno handle it
            raise

    @property
    def __class__(self):
        """Make isinstance() checks pass through to wrapped model."""
        return self.model.__class__

    @property
    def id(self):
        """Expose model ID for Agno's reasoning model detection."""
        return getattr(self.model, 'id', None)

    @property
    def name(self):
        """Expose model name."""
        return getattr(self.model, 'name', None)

    @property
    def provider(self):
        """Expose model provider."""
        return getattr(self.model, 'provider', None)

    @property
    def metrics(self):
        """Expose model metrics."""
        return getattr(self.model, 'metrics', None)

    @property
    def reasoning_effort(self):
        """Expose reasoning_effort for o1/o3 models."""
        return getattr(self.model, 'reasoning_effort', None)

    def __getattr__(self, name):
        """Forward all other attributes to wrapped model."""
        # Known safe methods/attributes that don't need interception
        known_safe = {
            '_ipython_canary_method_should_not_exist_', '__wrapped__',
            'to_dict', 'get_instructions_for_model', 'get_system_message_for_model',
            '__deepcopy__', '__copy__', '__getstate__', '__setstate__',
            '__repr__', '__str__', '__init__', 'model_dump', 'model_dump_json',
            'id', 'name', 'provider', 'metrics',  # Common model attributes
            'api_key', 'api_version', 'azure_endpoint', 'base_url', 'azure_deployment',  # Config attributes
            'max_tokens', 'timeout', 'max_retries',  # Model config
            'reasoning_effort', 'temperature', 'top_p', 'frequency_penalty', 'presence_penalty',  # LLM parameters
            # Agno framework internal methods (don't need interception)
            'get_function_call_to_run_from_tool_execution', 'arun_function_calls',
            'run_function_calls', 'get_function_call', 'parse_function_call', 'create_function_call_result'
        }

        if name not in known_safe:
            logger.debug(f"🔍 ModelInterceptor: Forwarding attribute access: {name}")

            # If it's a method, warn about bypass
            attr = getattr(self.model, name)
            if callable(attr):
                logger.warning(f"⚠️  UNEXPECTED: Accessing method '{name}' on wrapped model (bypassing interceptor)")
                logger.warning(f"   This method is not intercepted. Expected 'response', 'aresponse', or 'aresponse_stream'")
            return attr

        return getattr(self.model, name)


def wrap_model_with_interceptor(
    model,
    max_tokens: int = 128000,
    model_type: str = 'main',
    stats_tracker: Optional[ModelStatsTracker] = None
):
    """
    Wrap an Agno model with interceptor to log messages.

    Args:
        model: Agno model (AzureOpenAI, etc.)
        max_tokens: Maximum context window
        model_type: Type identifier for this model ('main', 'reasoning', 'output', 'parser', etc.)
        stats_tracker: Optional centralized stats tracker for multi-model tracking

    Returns:
        Wrapped model that logs messages before each LLM call
    """
    return ModelInterceptor(
        model,
        max_tokens=max_tokens,
        model_type=model_type,
        stats_tracker=stats_tracker
    )


# ============================================================================
# Context inspection and management utilities
# ============================================================================

def get_interceptor_stats(agent) -> Optional[ContextStats]:
    """
    Get actual context usage stats from the model interceptor.

    Args:
        agent: AgnoAgent instance with wrapped model

    Returns:
        ContextStats with actual usage from interceptor, or None if not available
    """
    try:
        # Access the wrapped model's interceptor stats
        if not hasattr(agent, 'llm'):
            logger.warning("Agent has no llm attribute")
            return None

        model = agent.llm

        # Check if model is wrapped with interceptor
        if not hasattr(model, 'stats'):
            logger.warning("Model is not wrapped with interceptor (no stats attribute)")
            return None

        stats = model.stats

        return ContextStats(
            call_count=stats.get('call_count', 0),
            total_input_tokens=stats.get('total_input_tokens', 0),
            max_context_seen=stats.get('max_context_seen', 0),
            avg_context=stats.get('total_input_tokens', 0) // max(stats.get('call_count', 1), 1),
            last_breakdown=stats.get('last_breakdown', None)
        )

    except Exception as e:
        logger.error(f"Failed to get interceptor stats: {e}", exc_info=True)
        return None


def log_context_summary(agent, max_tokens: int = 128000) -> None:
    """
    Log a summary of context usage from the model interceptor.

    This shows ACTUAL token usage from real LLM calls, not estimates.

    Args:
        agent: AgnoAgent instance
        max_tokens: Maximum context window (default 128k)
    """
    stats = get_interceptor_stats(agent)

    if not stats:
        logger.warning("⚠️  No context stats available - interceptor may not be working")
        return

    if stats.call_count == 0:
        logger.info("📊 Context Stats: No LLM calls made yet")
        return

    logger.info(f"\n{'='*80}")
    logger.info(f"📊 CONTEXT USAGE SUMMARY (from model interceptor)")
    logger.info(f"{'='*80}")
    logger.info(f"   Total LLM calls:     {stats.call_count}")
    logger.info(f"   Total input tokens:  {stats.total_input_tokens:,}")
    logger.info(f"   Max context (call):  {stats.max_context_seen:,} ({stats.max_context_seen/max_tokens*100:.1f}% of {max_tokens:,})")
    logger.info(f"   Avg context (call):  {stats.avg_context:,} ({stats.avg_context/max_tokens*100:.1f}%)")

    # Warnings
    if stats.max_context_seen > max_tokens * 0.7:
        logger.warning(f"   ⚠️  HIGH USAGE: Peak usage is {stats.max_context_seen/max_tokens*100:.1f}%")
        logger.warning(f"   Consider disabling tools or reducing num_history_runs")
    else:
        logger.info(f"   ✅ Context usage is reasonable")

    logger.info(f"{'='*80}\n")


def get_multi_model_stats(agent) -> Optional[Dict[str, Any]]:
    """
    Get stats from all models via the central ModelStatsTracker.

    Args:
        agent: AgnoAgent instance with model_stats_tracker

    Returns:
        Dictionary with stats for all models, or None if tracker not available
    """
    try:
        if not hasattr(agent, 'model_stats_tracker'):
            logger.debug("Agent has no model_stats_tracker (single-model mode)")
            return None

        return agent.model_stats_tracker.get_all_stats()

    except Exception as e:
        logger.error(f"Failed to get multi-model stats: {e}", exc_info=True)
        return None


def get_model_breakdown(agent, model_type: str = 'main') -> Optional[Dict[str, Any]]:
    """
    Get breakdown for a specific model type.

    Args:
        agent: AgnoAgent instance with model_stats_tracker
        model_type: Type of model ('main', 'reasoning', 'output', 'parser', etc.)

    Returns:
        Breakdown dictionary for the specified model, or None if not available
    """
    try:
        if not hasattr(agent, 'model_stats_tracker'):
            logger.debug("Agent has no model_stats_tracker")
            return None

        return agent.model_stats_tracker.get_last_call_breakdown(model_type)

    except Exception as e:
        logger.error(f"Failed to get model breakdown for {model_type}: {e}", exc_info=True)
        return None


def get_combined_breakdown(agent) -> Optional[Dict[str, Any]]:
    """
    Get combined breakdown from all models' last calls.

    Args:
        agent: AgnoAgent instance with model_stats_tracker

    Returns:
        Combined breakdown across all models, or None if not available
    """
    try:
        if not hasattr(agent, 'model_stats_tracker'):
            logger.debug("Agent has no model_stats_tracker")
            return None

        return agent.model_stats_tracker.get_combined_last_breakdown()

    except Exception as e:
        logger.error(f"Failed to get combined breakdown: {e}", exc_info=True)
        return None


class ContextManager:
    """Manage and optimize agent context."""

    def __init__(self, agent):
        """
        Initialize context manager.

        Args:
            agent: AgnoAgent instance
        """
        self.agent = agent

    def get_stats(self) -> Optional[ContextStats]:
        """Get current context usage statistics."""
        return get_interceptor_stats(self.agent)

    def log_summary(self, max_tokens: int = 128000) -> None:
        """Log context usage summary."""
        log_context_summary(self.agent, max_tokens=max_tokens)

    def enable_tools(self, tool_names: List[str]) -> None:
        """
        Enable only specified tools by name.

        Args:
            tool_names: List of tool names to enable
        """
        if not hasattr(self.agent, 'agent_tools'):
            logger.warning("Agent has no agent_tools attribute")
            return

        # Filter to only enabled tools
        enabled_tools = [
            t for t in self.agent.agent_tools
            if getattr(t, 'name', t.__class__.__name__) in tool_names
        ]

        # Update agent's tools
        self.agent.agent.set_tools(enabled_tools)
        logger.info(f"🔧 Enabled {len(enabled_tools)} tools: {', '.join(tool_names)}")

    def disable_tools(self, tool_names: List[str]) -> None:
        """
        Disable specified tools by name.

        Args:
            tool_names: List of tool names to disable
        """
        if not hasattr(self.agent, 'agent_tools'):
            logger.warning("Agent has no agent_tools attribute")
            return

        # Filter out disabled tools
        enabled_tools = [
            t for t in self.agent.agent_tools
            if getattr(t, 'name', t.__class__.__name__) not in tool_names
        ]

        # Update agent's tools
        self.agent.agent.set_tools(enabled_tools)
        logger.info(f"🔧 Disabled {len(tool_names)} tools, {len(enabled_tools)} remain")

    def list_tools(self) -> List[str]:
        """
        List all available tool names.

        Returns:
            List of tool names
        """
        if not hasattr(self.agent, 'agent_tools'):
            return []

        return [
            getattr(t, 'name', t.__class__.__name__)
            for t in self.agent.agent_tools
        ]

    def count_tool_functions(self) -> Dict[str, int]:
        """
        Count functions per tool (each function adds ~2k tokens).

        Returns:
            Dict mapping tool name to function count
        """
        if not hasattr(self.agent, 'agent_tools'):
            return {}

        tool_functions = {}
        for tool in self.agent.agent_tools:
            tool_name = getattr(tool, 'name', tool.__class__.__name__)

            if hasattr(tool, 'functions'):
                tool_functions[tool_name] = len(tool.functions)
            else:
                tool_functions[tool_name] = 1

        return tool_functions

    def estimate_tool_tokens(self) -> int:
        """
        Estimate total tokens used by tool schemas (~2k per function).

        Returns:
            Estimated token count for all tool schemas
        """
        func_counts = self.count_tool_functions()
        return sum(func_counts.values()) * 2000

    def get_toolkit_breakdown(self) -> List[Dict[str, Any]]:
        """
        Get detailed breakdown of tokens per toolkit.

        Returns:
            List of dicts with toolkit stats, sorted by token usage (descending)
        """
        from .token_estimator import TokenEstimator

        if not hasattr(self.agent, 'agent_tools'):
            return []

        estimator = TokenEstimator()
        toolkits = []

        for tool in self.agent.agent_tools:
            tool_name = getattr(tool, 'name', tool.__class__.__name__)

            # Get function count
            if hasattr(tool, 'functions'):
                func_count = len(tool.functions)
            else:
                func_count = 1

            # Estimate tokens for this toolkit
            estimated_tokens = estimator.estimate_tool_from_toolkit(tool)

            toolkits.append({
                'name': tool_name,
                'functions': func_count,
                'estimated_tokens': estimated_tokens,
                'toolkit': tool  # Store reference for enable/disable
            })

        # Sort by token usage (descending)
        toolkits.sort(key=lambda x: x['estimated_tokens'], reverse=True)

        return toolkits

    def get_full_context_breakdown(self) -> Dict[str, Any]:
        """
        Get complete breakdown of ALL context components (not just tools).

        This provides a Pareto-style view of what's consuming context tokens,
        suitable for interactive management and optimization.

        Returns:
            Dict with:
                - components: List of dicts with name, tokens, percentage, type, actions
                - total_tokens: Total actual tokens from last call
                - max_tokens: Maximum context window
        """
        from .token_estimator import TokenEstimator

        estimator = TokenEstimator()
        components = []
        max_tokens = 128000

        # Get actual stats if available
        stats = get_interceptor_stats(self.agent)
        breakdown = stats.last_breakdown if stats and stats.last_breakdown else None

        # If no actual data, return empty
        if not breakdown:
            return {
                'components': [],
                'total_tokens': 0,
                'max_tokens': max_tokens,
                'usage_pct': 0
            }

        # Use ACTUAL tokens from last call, not estimates
        # 1. System Prompt
        if breakdown.get('system_tokens', 0) > 0:
            components.append({
                'name': 'System Prompt',
                'tokens': breakdown['system_tokens'],
                'type': 'system',
                'description': 'System message',
                'actions': ['view', 'edit']
            })

        # 2. Chat History
        if breakdown.get('assistant_tokens', 0) > 0:
            num_runs = getattr(self.agent, 'num_history_runs', '?')
            components.append({
                'name': 'Chat History',
                'tokens': breakdown['assistant_tokens'],
                'type': 'history',
                'description': f'{num_runs} previous turn(s)',
                'actions': ['clear', 'reduce']
            })

        # 3. Tool Schemas (combined - we can't break down per toolkit from actual data)
        if breakdown.get('tool_tokens', 0) > 0:
            tool_count = breakdown.get('tool_count', 0)
            components.append({
                'name': 'Tool Schemas',
                'tokens': breakdown['tool_tokens'],
                'type': 'tools',
                'description': f'{tool_count} function(s) sent',
                'actions': ['view', 'disable']
            })

        # 4. Current User Message
        if breakdown.get('user_tokens', 0) > 0:
            components.append({
                'name': 'Current Input',
                'tokens': breakdown['user_tokens'],
                'type': 'user',
                'description': 'User message',
                'actions': []
            })

        # 5. Tool Results (if any)
        if breakdown.get('tool_result_tokens', 0) > 0:
            components.append({
                'name': 'Tool Results',
                'tokens': breakdown['tool_result_tokens'],
                'type': 'tool_results',
                'description': 'Previous tool outputs',
                'actions': []
            })

        # Use actual total from breakdown
        total_tokens = breakdown['total_tokens']

        # Add percentages
        for component in components:
            component['percentage'] = (component['tokens'] / total_tokens * 100) if total_tokens > 0 else 0

        # Sort by token count (descending) - Pareto principle
        components.sort(key=lambda x: x['tokens'], reverse=True)

        return {
            'components': components,
            'total_tokens': total_tokens,
            'max_tokens': max_tokens,
            'usage_pct': (total_tokens / max_tokens * 100) if max_tokens > 0 else 0
        }


# Convenience functions for CLI integration

def show_context_usage(agent) -> None:
    """
    Show current context usage (for CLI commands).

    Args:
        agent: AgnoAgent instance
    """
    log_context_summary(agent)


def verify_interceptor(agent) -> bool:
    """
    Verify that model interceptor is working.

    Args:
        agent: AgnoAgent instance

    Returns:
        True if interceptor is active and has recorded calls
    """
    stats = get_interceptor_stats(agent)

    if not stats:
        logger.error("❌ Model interceptor is NOT working - no stats available")
        logger.error("   Check that model is wrapped in agno_agent.py")
        return False

    if stats.call_count == 0:
        logger.warning("⚠️  Model interceptor is active but no LLM calls recorded yet")
        logger.warning("   Make a request to test it")
        return True

    logger.info(f"✅ Model interceptor is working - {stats.call_count} LLM calls recorded")
    logger.info(f"   Total tokens: {stats.total_input_tokens:,}")
    logger.info(f"   Max context: {stats.max_context_seen:,}")
    return True


# Global tracker instance (for convenience)
_global_tracker: Optional[ModelStatsTracker] = None


def get_global_tracker() -> ModelStatsTracker:
    """
    Get or create the global model stats tracker.

    Returns:
        Global ModelStatsTracker instance
    """
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = ModelStatsTracker()
    return _global_tracker


def reset_global_tracker() -> None:
    """Reset the global tracker (useful for testing)."""
    global _global_tracker
    _global_tracker = None