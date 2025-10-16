"""Token estimation utilities based on experimental heuristics.

This module provides functions to estimate token usage for various
components without requiring actual LLM calls or full serialization.

Based on experiments in experiments/tool_schema_token_model.py and
experiments/memory_token_experiments.py.
"""

from typing import List, Dict, Any
import tiktoken


class TokenEstimator:
    """Estimate token usage for various agent components."""

    def __init__(self, model: str = "gpt-4"):
        """Initialize estimator with tiktoken encoding."""
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count actual tokens in text."""
        return len(self.encoding.encode(text))

    def estimate_tool_schema_tokens(
        self,
        num_functions: int,
        avg_docstring_length: int = 100,
        avg_params: int = 3,
        avg_param_desc_length: int = 50
    ) -> int:
        """
        Estimate tokens for a tool schema using heuristic model.

        Formula (from experiments):
            tokens = num_functions * (
                BASE_OVERHEAD +
                (DOC_COEF * docstring_chars) +
                (PARAM_COEF * num_params * param_desc_chars)
            )

        Coefficients from experiments/tool_schema_token_model.py:
            BASE_OVERHEAD = 183 tokens (from regression analysis)
            DOC_COEF = 0.125 (measured from experiments)
            PARAM_COEF = 0.27 (measured average for JSON schema overhead)

        Args:
            num_functions: Number of functions in the tool
            avg_docstring_length: Average docstring length in chars
            avg_params: Average number of parameters per function
            avg_param_desc_length: Average parameter description length in chars

        Returns:
            Estimated token count
        """
        BASE_OVERHEAD = 183
        DOC_COEF = 0.125
        PARAM_COEF = 0.27

        tokens_per_function = (
            BASE_OVERHEAD +
            (DOC_COEF * avg_docstring_length) +
            (PARAM_COEF * avg_params * avg_param_desc_length)
        )

        return int(num_functions * tokens_per_function)

    def estimate_tool_from_toolkit(self, toolkit) -> int:
        """
        Estimate tokens for a Toolkit by analyzing its functions.

        This inspects the toolkit's actual functions and measures their
        docstrings and parameters to provide a more accurate estimate.

        Args:
            toolkit: Agno Toolkit instance

        Returns:
            Estimated token count for this toolkit's schema
        """
        if not hasattr(toolkit, 'functions'):
            return 100  # Minimal estimate for unknown tools

        num_functions = len(toolkit.functions)
        if num_functions == 0:
            return 0

        total_doc_length = 0
        total_params = 0

        for func in toolkit.functions:
            # Get docstring length
            if hasattr(func, '__doc__') and func.__doc__:
                total_doc_length += len(func.__doc__.strip())

            # Estimate parameters (rough heuristic)
            if hasattr(func, '__code__'):
                # Subtract 1 for 'self' parameter
                total_params += max(0, func.__code__.co_argcount - 1)

        avg_doc_length = total_doc_length // num_functions if num_functions > 0 else 100
        avg_params = total_params // num_functions if num_functions > 0 else 3

        return self.estimate_tool_schema_tokens(
            num_functions=num_functions,
            avg_docstring_length=avg_doc_length,
            avg_params=avg_params,
            avg_param_desc_length=50  # Reasonable default
        )

    def estimate_user_memory_tokens(self, num_memories: int, avg_memory_length: int = 50) -> int:
        """
        Estimate tokens for user memories.

        Formula (from experiments):
            tokens_per_memory ≈ (memory_chars / 4) + 15 (JSON overhead)
            total_tokens = num_memories * tokens_per_memory

        Args:
            num_memories: Number of stored memories
            avg_memory_length: Average memory content length in chars

        Returns:
            Estimated token count
        """
        OVERHEAD_PER_MEMORY = 26  # JSON structure overhead (from experiments)

        tokens_per_memory = (avg_memory_length / 4) + OVERHEAD_PER_MEMORY
        return int(num_memories * tokens_per_memory)

    def estimate_chat_history_tokens(
        self,
        num_history_runs: int,
        avg_messages_per_run: int = 2,  # User + assistant
        avg_message_length: int = 200
    ) -> int:
        """
        Estimate tokens for chat history.

        Formula (from experiments):
            tokens_per_message ≈ (message_chars / 4) + 20 (JSON overhead)
            total_tokens = num_history_runs * avg_messages_per_run * tokens_per_message

        Typical values (from experiments):
            - Short Q&A: ~41 tokens per exchange (2 messages)
            - Medium conversation: ~146 tokens per exchange (4 messages)
            - Code review: ~245 tokens per exchange (4 messages)
            - Average: ~250 tokens per run

        Args:
            num_history_runs: Number of previous runs to include (from agent config)
            avg_messages_per_run: Average messages per run (default: 2 = user + assistant)
            avg_message_length: Average message length in chars

        Returns:
            Estimated token count
        """
        OVERHEAD_PER_MESSAGE = 20  # JSON structure overhead

        tokens_per_message = (avg_message_length / 4) + OVERHEAD_PER_MESSAGE
        total_messages = num_history_runs * avg_messages_per_run

        return int(total_messages * tokens_per_message)

    def estimate_context_breakdown(
        self,
        system_message: str,
        instructions: List[str],
        num_tools: int = 0,
        avg_tool_functions: int = 5,
        num_memories: int = 0,
        num_history_runs: int = 5,
        current_user_message: str = ""
    ) -> Dict[str, Any]:
        """
        Estimate full context window breakdown.

        Args:
            system_message: System prompt text
            instructions: List of instruction strings
            num_tools: Number of tools available
            avg_tool_functions: Average functions per tool
            num_memories: Number of user memories
            num_history_runs: Chat history depth (from agent config)
            current_user_message: Current user input

        Returns:
            Dictionary with token breakdown and percentages
        """
        # Count actual tokens for text components
        system_tokens = self.count_tokens(system_message)
        instructions_tokens = sum(self.count_tokens(instr) for instr in instructions)
        user_tokens = self.count_tokens(current_user_message) if current_user_message else 0

        # Estimate datetime context (always ~21 tokens)
        datetime_tokens = 21

        # Estimate framework overhead (Agno internal context)
        framework_overhead = 200  # Conservative estimate

        # Estimate tool schemas
        tool_tokens = self.estimate_tool_schema_tokens(
            num_functions=avg_tool_functions,
            avg_docstring_length=100,
            avg_params=3,
            avg_param_desc_length=50
        ) * num_tools if num_tools > 0 else 0

        # Estimate memories
        memory_tokens = self.estimate_user_memory_tokens(num_memories) if num_memories > 0 else 0

        # Estimate chat history
        history_tokens = self.estimate_chat_history_tokens(num_history_runs) if num_history_runs > 0 else 0

        # Calculate total
        total_tokens = (
            system_tokens +
            instructions_tokens +
            datetime_tokens +
            framework_overhead +
            tool_tokens +
            memory_tokens +
            history_tokens +
            user_tokens
        )

        # Build breakdown
        return {
            "system_message": system_tokens,
            "instructions": instructions_tokens,
            "datetime_context": datetime_tokens,
            "framework_overhead": framework_overhead,
            "tool_schemas": tool_tokens,
            "user_memories": memory_tokens,
            "chat_history": history_tokens,
            "current_user_message": user_tokens,
            "total_estimated": total_tokens,
            "components_pct": {
                "system": (system_tokens / total_tokens * 100) if total_tokens > 0 else 0,
                "tools": (tool_tokens / total_tokens * 100) if total_tokens > 0 else 0,
                "history": (history_tokens / total_tokens * 100) if total_tokens > 0 else 0,
                "memories": (memory_tokens / total_tokens * 100) if total_tokens > 0 else 0,
                "other": ((datetime_tokens + framework_overhead + instructions_tokens + user_tokens) / total_tokens * 100) if total_tokens > 0 else 0,
            }
        }


# Convenience functions

def estimate_tool_tokens(toolkit) -> int:
    """Quick estimate of tool schema tokens for a toolkit."""
    estimator = TokenEstimator()
    return estimator.estimate_tool_from_toolkit(toolkit)


def estimate_all_tools_tokens(toolkits: List[Any]) -> int:
    """Estimate total tokens for a list of toolkits."""
    estimator = TokenEstimator()
    return sum(estimator.estimate_tool_from_toolkit(t) for t in toolkits)


def estimate_memory_impact(num_memories: int) -> Dict[str, int]:
    """Get estimated token impact of user memories."""
    estimator = TokenEstimator()
    tokens = estimator.estimate_user_memory_tokens(num_memories)

    return {
        "tokens": tokens,
        "per_memory": tokens // num_memories if num_memories > 0 else 0,
        "recommendation": "optimal" if tokens < 500 else "high" if tokens < 1000 else "very_high"
    }


def estimate_history_impact(num_runs: int) -> Dict[str, Any]:
    """Get estimated token impact of chat history."""
    estimator = TokenEstimator()
    tokens = estimator.estimate_chat_history_tokens(num_runs)

    return {
        "tokens": tokens,
        "per_run": tokens // num_runs if num_runs > 0 else 0,
        "recommendation": "optimal" if num_runs <= 5 else "reduce" if num_runs <= 10 else "high",
        "suggested_value": 5 if num_runs > 5 else num_runs
    }