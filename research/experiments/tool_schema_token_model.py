"""Build a heuristic model for predicting tool schema token usage.

This experiment creates various tool configurations and measures their actual
token usage when serialized to OpenAI function calling format.
"""

import json
import tiktoken
from typing import List, Dict, Any
from dataclasses import dataclass
import statistics


@dataclass
class ToolConfig:
    """Configuration for a test tool."""
    name: str
    num_functions: int
    docstring_length: int  # chars per function
    num_params: int  # parameters per function
    param_description_length: int  # chars per parameter description


@dataclass
class TokenMeasurement:
    """Results from measuring a tool's token usage."""
    config: ToolConfig
    total_tokens: int
    tokens_per_function: float
    json_size_bytes: int


def create_test_function(func_num: int, config: ToolConfig) -> Dict[str, Any]:
    """Create a test function definition matching Agno's format."""
    # Generate docstring
    docstring = f"Function {func_num}: " + "x" * (config.docstring_length - 20)

    # Generate parameters
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    for i in range(config.num_params):
        param_name = f"param_{i}"
        param_desc = "p" * config.param_description_length
        parameters["properties"][param_name] = {
            "type": "string",
            "description": param_desc
        }
        parameters["required"].append(param_name)

    # Return in OpenAI function calling format
    return {
        "type": "function",
        "function": {
            "name": f"{config.name}_func_{func_num}",
            "description": docstring,
            "parameters": parameters
        }
    }


def create_tool_schema(config: ToolConfig) -> List[Dict[str, Any]]:
    """Create a complete tool schema with multiple functions."""
    return [
        create_test_function(i, config)
        for i in range(config.num_functions)
    ]


def measure_tool_tokens(config: ToolConfig) -> TokenMeasurement:
    """Measure actual token usage for a tool configuration."""
    enc = tiktoken.encoding_for_model('gpt-4')

    # Create tool schema
    schema = create_tool_schema(config)

    # Serialize to JSON (as Agno does)
    json_str = json.dumps(schema)

    # Count tokens
    tokens = len(enc.encode(json_str))

    return TokenMeasurement(
        config=config,
        total_tokens=tokens,
        tokens_per_function=tokens / config.num_functions if config.num_functions > 0 else 0,
        json_size_bytes=len(json_str)
    )


def run_experiments() -> List[TokenMeasurement]:
    """Run comprehensive experiments on tool schema token usage."""
    results = []

    print("=" * 80)
    print("TOOL SCHEMA TOKEN USAGE EXPERIMENTS")
    print("=" * 80)
    print()

    # Experiment 1: Vary number of functions (fixed docstring)
    print("Experiment 1: Varying number of functions")
    print("-" * 80)
    for num_funcs in [1, 2, 4, 8, 10, 15, 20]:
        config = ToolConfig(
            name="test_tool",
            num_functions=num_funcs,
            docstring_length=100,
            num_params=3,
            param_description_length=50
        )
        result = measure_tool_tokens(config)
        results.append(result)
        print(f"  {num_funcs:2d} functions: {result.total_tokens:5,} tokens "
              f"({result.tokens_per_function:6.1f} per func)")
    print()

    # Experiment 2: Vary docstring length (fixed functions)
    print("Experiment 2: Varying docstring length (8 functions)")
    print("-" * 80)
    for doc_len in [20, 50, 100, 200, 500, 1000]:
        config = ToolConfig(
            name="test_tool",
            num_functions=8,
            docstring_length=doc_len,
            num_params=3,
            param_description_length=50
        )
        result = measure_tool_tokens(config)
        results.append(result)
        print(f"  Docstring {doc_len:4d} chars: {result.total_tokens:5,} tokens "
              f"({result.tokens_per_function:6.1f} per func)")
    print()

    # Experiment 3: Vary number of parameters (fixed functions)
    print("Experiment 3: Varying parameter count (8 functions)")
    print("-" * 80)
    for num_params in [0, 1, 2, 3, 5, 10]:
        config = ToolConfig(
            name="test_tool",
            num_functions=8,
            docstring_length=100,
            num_params=num_params,
            param_description_length=50
        )
        result = measure_tool_tokens(config)
        results.append(result)
        print(f"  {num_params:2d} params: {result.total_tokens:5,} tokens "
              f"({result.tokens_per_function:6.1f} per func)")
    print()

    # Experiment 4: Vary parameter description length
    print("Experiment 4: Varying parameter description length (8 functions, 3 params)")
    print("-" * 80)
    for param_desc_len in [10, 25, 50, 100, 200]:
        config = ToolConfig(
            name="test_tool",
            num_functions=8,
            docstring_length=100,
            num_params=3,
            param_description_length=param_desc_len
        )
        result = measure_tool_tokens(config)
        results.append(result)
        print(f"  Param desc {param_desc_len:3d} chars: {result.total_tokens:5,} tokens "
              f"({result.tokens_per_function:6.1f} per func)")
    print()

    # Experiment 5: Realistic configurations (matching actual tools)
    print("Experiment 5: Realistic tool configurations")
    print("-" * 80)
    realistic_configs = [
        ToolConfig("TodoTool", 4, 80, 1, 40),
        ToolConfig("FileTool", 8, 120, 3, 60),
        ToolConfig("CommandTool", 1, 150, 2, 80),
        ToolConfig("HttpTool", 1, 100, 3, 50),
    ]

    for config in realistic_configs:
        result = measure_tool_tokens(config)
        results.append(result)
        print(f"  {config.name:15s} ({config.num_functions} funcs): {result.total_tokens:5,} tokens "
              f"({result.tokens_per_function:6.1f} per func)")
    print()

    return results


def analyze_results(results: List[TokenMeasurement]) -> None:
    """Analyze results and build heuristic model."""
    print("=" * 80)
    print("HEURISTIC MODEL ANALYSIS")
    print("=" * 80)
    print()

    # Calculate base overhead per function
    single_func_results = [r for r in results if r.config.num_functions == 1]
    if single_func_results:
        avg_tokens_per_func = statistics.mean([r.total_tokens for r in single_func_results])
        print(f"Average tokens per function (baseline): {avg_tokens_per_func:.1f}")

    # Analyze overhead
    print("\nOverhead Analysis:")

    # JSON structure overhead
    overhead_samples = []
    for r in results:
        if r.config.num_functions > 0:
            # Estimate content vs overhead
            content_estimate = (
                r.config.num_functions *
                (r.config.docstring_length / 4 +  # ~4 chars per token
                 r.config.num_params * (r.config.param_description_length / 4 + 20))
            )
            overhead = r.total_tokens - content_estimate
            overhead_samples.append(overhead / r.config.num_functions)

    avg_overhead = statistics.mean(overhead_samples)
    print(f"  Average JSON overhead per function: {avg_overhead:.1f} tokens")

    # Build regression model
    print("\nRegression Model Coefficients:")

    # Simple linear model: tokens = base + (coef_doc * doc_len) + (coef_param * num_params * param_len)
    # Using representative samples
    samples = [r for r in results if r.config.num_functions == 8]

    if len(samples) > 5:
        # Estimate coefficients from variance
        doc_variance = [r for r in samples if r.config.num_params == 3 and r.config.param_description_length == 50]
        if doc_variance:
            doc_tokens = [(r.total_tokens / r.config.num_functions, r.config.docstring_length) for r in doc_variance]
            if len(doc_tokens) >= 2:
                # Simple linear regression
                x_vals = [d[1] for d in doc_tokens]
                y_vals = [d[0] for d in doc_tokens]
                n = len(x_vals)
                x_mean = statistics.mean(x_vals)
                y_mean = statistics.mean(y_vals)

                numerator = sum((x_vals[i] - x_mean) * (y_vals[i] - y_mean) for i in range(n))
                denominator = sum((x_vals[i] - x_mean) ** 2 for i in range(n))

                if denominator != 0:
                    coef_doc = numerator / denominator
                    intercept = y_mean - (coef_doc * x_mean)
                    print(f"  Docstring coefficient: {coef_doc:.4f} tokens per char")
                    print(f"  Base overhead: {intercept:.1f} tokens")

    # Proposed formula
    print("\nProposed Heuristic Formula:")
    print("=" * 80)
    print("tokens_per_function = BASE + (DOC_COEF * docstring_chars) + (PARAM_COEF * num_params * param_desc_chars)")
    print()
    print("Estimated coefficients:")
    print("  BASE:       ~60 tokens (JSON structure, function name, etc.)")
    print("  DOC_COEF:   ~0.25 (1 token per 4 chars)")
    print("  PARAM_COEF: ~0.30 (slightly higher due to JSON schema overhead)")
    print()
    print("Example for FileTool (8 functions, 120 char docs, 3 params × 60 chars):")
    estimated = 8 * (60 + (0.25 * 120) + (0.30 * 3 * 60))
    print(f"  Estimated: {estimated:.0f} tokens")

    # Find actual FileTool result
    filetool_result = next((r for r in results if r.config.name == "FileTool"), None)
    if filetool_result:
        print(f"  Actual:    {filetool_result.total_tokens} tokens")
        print(f"  Error:     {abs(estimated - filetool_result.total_tokens):.0f} tokens ({abs(estimated - filetool_result.total_tokens) / filetool_result.total_tokens * 100:.1f}%)")
    print()


if __name__ == "__main__":
    results = run_experiments()
    analyze_results(results)

    print("\n" + "=" * 80)
    print("EXPORT RESULTS")
    print("=" * 80)

    # Save results to JSON
    import json
    output = {
        "measurements": [
            {
                "name": r.config.name,
                "num_functions": r.config.num_functions,
                "docstring_length": r.config.docstring_length,
                "num_params": r.config.num_params,
                "param_description_length": r.config.param_description_length,
                "total_tokens": r.total_tokens,
                "tokens_per_function": r.tokens_per_function,
                "json_size_bytes": r.json_size_bytes
            }
            for r in results
        ]
    }

    with open("tool_schema_measurements.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Results saved to: tool_schema_measurements.json")
