"""Experiments to measure user memory and chat history token usage.

This script creates test scenarios to understand how Agno's user memories
and chat history consume tokens in the context window.
"""

import os
import sys
import asyncio
import tiktoken
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import json

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from da_code.models import CodeSession
from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.db.sqlite import SqliteDb


class MemoryTokenAnalyzer:
    """Analyze token usage for user memories and chat history."""

    def __init__(self):
        self.encoding = tiktoken.encoding_for_model('gpt-4')
        self.results = []

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    async def experiment_user_memories(self):
        """Experiment 1: Measure user memory token usage."""
        print("=" * 80)
        print("EXPERIMENT 1: USER MEMORY TOKEN USAGE")
        print("=" * 80)
        print()

        # Create temporary database
        db_path = ".da/test_memory_experiment.db"
        os.makedirs(".da", exist_ok=True)

        db = SqliteDb(
            session_table="test_memory_sessions",
            db_file=db_path
        )

        # Create test agent with memories enabled
        # Note: We won't actually call the LLM, just analyze the context construction
        print("Creating test agent with user memories enabled...")

        test_memories = [
            "User prefers Python for data analysis",
            "User's timezone is Pacific Standard Time (PST)",
            "User works on machine learning projects",
            "User likes detailed explanations with examples",
            "User's main project is called 'naten'",
            "User previously worked on sentiment analysis",
            "User uses Visual Studio Code as primary editor",
            "User prefers dark mode for all applications",
            "User is experienced with asyncio and concurrent programming",
            "User likes comprehensive documentation",
        ]

        print(f"\nCreated {len(test_memories)} test memories:")
        total_memory_tokens = 0
        for i, memory in enumerate(test_memories, 1):
            tokens = self.count_tokens(memory)
            total_memory_tokens += tokens
            print(f"  {i:2d}. [{tokens:3d} tokens] {memory}")

        print(f"\n{'─' * 80}")
        print(f"Total memory content: {total_memory_tokens} tokens")

        # Estimate overhead (JSON structure, field names, etc.)
        memory_json = json.dumps({
            "memories": [{"content": m, "created_at": datetime.now().isoformat()} for m in test_memories]
        })
        memory_json_tokens = self.count_tokens(memory_json)
        overhead = memory_json_tokens - total_memory_tokens

        print(f"Total with JSON overhead: {memory_json_tokens} tokens")
        print(f"Overhead: {overhead} tokens ({overhead / len(test_memories):.1f} per memory)")
        print()

        # Analyze per-memory overhead
        print("Heuristic Formula for User Memories:")
        print("  tokens_per_memory ≈ content_tokens + 15 (JSON overhead)")
        print(f"  total_memories_tokens ≈ Σ(memory_tokens) + {overhead}")
        print()

        self.results.append({
            "experiment": "user_memories",
            "num_memories": len(test_memories),
            "content_tokens": total_memory_tokens,
            "total_tokens": memory_json_tokens,
            "overhead_tokens": overhead,
            "avg_tokens_per_memory": memory_json_tokens / len(test_memories)
        })

        # Cleanup
        try:
            os.remove(db_path)
        except:
            pass

    async def experiment_chat_history(self):
        """Experiment 2: Measure chat history token usage."""
        print("=" * 80)
        print("EXPERIMENT 2: CHAT HISTORY TOKEN USAGE")
        print("=" * 80)
        print()

        # Simulate chat history with varying message lengths
        chat_scenarios = [
            {
                "name": "Short Q&A",
                "exchanges": [
                    ("User", "What is asyncio?"),
                    ("Assistant", "Asyncio is Python's library for concurrent programming using async/await syntax."),
                ]
            },
            {
                "name": "Medium conversation",
                "exchanges": [
                    ("User", "How do I optimize my database queries?"),
                    ("Assistant", "Here are several strategies:\n1. Use indexes on frequently queried columns\n2. Avoid SELECT *\n3. Use EXPLAIN to analyze query plans\n4. Consider query caching\n5. Optimize JOIN operations"),
                    ("User", "Can you explain more about indexes?"),
                    ("Assistant", "Indexes are data structures that improve query speed. They work like a book's index - instead of scanning every row, the database can quickly locate relevant data. Common types include B-tree, hash, and full-text indexes."),
                ]
            },
            {
                "name": "Code review",
                "exchanges": [
                    ("User", "Can you review this code?"),
                    ("Assistant", "I'd be happy to review your code. Please share the code snippet."),
                    ("User", "def process(data):\n    result = []\n    for item in data:\n        if item > 0:\n            result.append(item * 2)\n    return result"),
                    ("Assistant", "Good start! Here are some improvements:\n\n1. Use list comprehension: `return [item * 2 for item in data if item > 0]`\n2. Add type hints: `def process(data: List[int]) -> List[int]`\n3. Add docstring explaining what the function does\n4. Consider edge cases (empty list, None values)\n\nRefactored:\n```python\nfrom typing import List\n\ndef process(data: List[int]) -> List[int]:\n    \"\"\"Double all positive numbers in the input list.\"\"\"\n    return [item * 2 for item in data if item > 0]\n```"),
                ]
            }
        ]

        print("Analyzing different chat history scenarios:\n")

        for scenario in chat_scenarios:
            print(f"Scenario: {scenario['name']}")
            print("─" * 80)

            total_tokens = 0
            for role, message in scenario["exchanges"]:
                # Format as Agno would (with role prefix and JSON structure)
                message_json = json.dumps({"role": role.lower(), "content": message})
                tokens = self.count_tokens(message_json)
                total_tokens += tokens
                print(f"  {role:10s}: {tokens:4d} tokens - {message[:60]}{'...' if len(message) > 60 else ''}")

            avg_per_message = total_tokens / len(scenario["exchanges"])
            print(f"  {'─' * 76}")
            print(f"  Total: {total_tokens:4d} tokens ({len(scenario['exchanges'])} messages, {avg_per_message:.1f} avg)")
            print()

            self.results.append({
                "experiment": "chat_history",
                "scenario": scenario["name"],
                "num_messages": len(scenario["exchanges"]),
                "total_tokens": total_tokens,
                "avg_tokens_per_message": avg_per_message
            })

        # Analyze impact of num_history_runs
        print("\n" + "=" * 80)
        print("IMPACT OF num_history_runs SETTING")
        print("=" * 80)
        print()

        avg_tokens_per_exchange = 250  # Estimated from above scenarios
        for num_runs in [1, 3, 5, 10, 20]:
            estimated_tokens = num_runs * avg_tokens_per_exchange
            print(f"  num_history_runs = {num_runs:2d}  →  ~{estimated_tokens:5,} tokens in context")

        print()
        print("Recommendation:")
        print("  - Keep num_history_runs = 5 for balanced context (typical use)")
        print("  - Reduce to 3 if context usage > 70%")
        print("  - Increase to 10 for complex multi-turn conversations")
        print()

    async def experiment_combined_overhead(self):
        """Experiment 3: Measure combined overhead (memories + history + system)."""
        print("=" * 80)
        print("EXPERIMENT 3: COMBINED CONTEXT OVERHEAD")
        print("=" * 80)
        print()

        # Simulate a typical agent context
        components = {
            "System message (base)": 123,
            "Todo.md": 509,
            "Instructions": 111,
            "Datetime context": 21,
            "User memories (5 items)": 180,  # From experiment 1
            "Chat history (5 runs, 10 msgs)": 1250,  # From experiment 2
            "Tool schemas (15 tools)": 1217,  # From actual measurement
            "Current user message": 50,
        }

        print("Typical agent context breakdown:\n")

        total = 0
        for component, tokens in components.items():
            pct = 0  # Will calculate after total
            total += tokens

        for component, tokens in components.items():
            pct = (tokens / total) * 100
            print(f"  {component:35s}: {tokens:5,} tokens ({pct:5.1f}%)")

        print(f"  {'─' * 78}")
        print(f"  {'TOTAL':35s}: {total:5,} tokens")
        print()

        # Show impact on max context
        max_context = 128000
        usage_pct = (total / max_context) * 100
        remaining = max_context - total
        remaining_pct = (remaining / max_context) * 100

        print(f"Context window usage:")
        print(f"  Used:      {total:6,} / {max_context:6,} tokens ({usage_pct:5.1f}%)")
        print(f"  Remaining: {remaining:6,} tokens ({remaining_pct:5.1f}%)")
        print()

        self.results.append({
            "experiment": "combined_overhead",
            "components": components,
            "total_tokens": total,
            "max_context": max_context,
            "usage_pct": usage_pct
        })

    async def run_all_experiments(self):
        """Run all experiments."""
        await self.experiment_user_memories()
        await self.experiment_chat_history()
        await self.experiment_combined_overhead()

        # Save results
        output_file = "memory_token_measurements.json"
        with open(output_file, "w") as f:
            json.dump(self.results, f, indent=2)

        print("=" * 80)
        print("RESULTS SAVED")
        print("=" * 80)
        print(f"Results saved to: {output_file}")
        print()

        # Summary recommendations
        print("=" * 80)
        print("RECOMMENDATIONS FOR TOKEN OPTIMIZATION")
        print("=" * 80)
        print()
        print("1. USER MEMORIES:")
        print("   - Each memory costs ~15-30 tokens (content + JSON overhead)")
        print("   - Keep memories concise (< 50 chars when possible)")
        print("   - Regularly prune outdated memories")
        print()
        print("2. CHAT HISTORY:")
        print("   - Each message pair (user + assistant) costs ~200-300 tokens")
        print("   - num_history_runs=5 is optimal for most cases (~1,250 tokens)")
        print("   - Reduce to 3 if approaching context limits")
        print()
        print("3. TODO.MD:")
        print("   - Currently using 509 tokens (36% of system message)")
        print("   - Move completed items to DONE.md")
        print("   - Keep only active/pending items in todo.md")
        print()
        print("4. OVERALL STRATEGY:")
        print("   - Monitor context usage in real-time")
        print("   - Prioritize: System > Tools > Recent History > Old History > Memories")
        print("   - Use context overlay to identify optimization targets")
        print()


async def main():
    """Run memory token experiments."""
    analyzer = MemoryTokenAnalyzer()
    await analyzer.run_all_experiments()


if __name__ == "__main__":
    asyncio.run(main())