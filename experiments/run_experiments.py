"""Run all token estimation experiments."""

import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    """Run all experiments."""
    print("╔" + "═" * 78 + "╗")
    print("║" + " TOKEN ESTIMATION EXPERIMENTS ".center(78) + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    print("This suite runs experiments to build heuristic models for:")
    print("  1. Tool schema token usage estimation")
    print("  2. User memory token usage patterns")
    print("  3. Chat history token impact")
    print()

    # Run tool schema experiments
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│" + " PART 1: TOOL SCHEMA TOKEN MODEL ".center(78) + "│")
    print("└" + "─" * 78 + "┘\n")

    import tool_schema_token_model
    tool_results = tool_schema_token_model.run_experiments()
    tool_schema_token_model.analyze_results(tool_results)

    # Run memory experiments
    print("\n" + "┌" + "─" * 78 + "┐")
    print("│" + " PART 2: MEMORY TOKEN EXPERIMENTS ".center(78) + "│")
    print("└" + "─" * 78 + "┘\n")

    import memory_token_experiments
    asyncio.run(memory_token_experiments.main())

    print("\n" + "╔" + "═" * 78 + "╗")
    print("║" + " EXPERIMENTS COMPLETE ".center(78) + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    print("Output files created:")
    print("  - tool_schema_measurements.json")
    print("  - memory_token_measurements.json")
    print()
    print("Next steps:")
    print("  1. Review the heuristic formulas in the output")
    print("  2. Integrate the token_estimator.py into context_inspector.py")
    print("  3. Update context overlay to show memory and history estimates")
    print()


if __name__ == "__main__":
    main()