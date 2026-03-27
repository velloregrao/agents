"""Stock analysis agent using Claude with tool use."""

import json

import anthropic

from .tools import TOOL_DEFINITIONS, execute_tool
from .memory import log_token_usage

SYSTEM_PROMPT = """You are a professional stock analyst. When given a ticker symbol,
you systematically gather data using the available tools and produce a clear,
structured analysis covering:

1. Company overview
2. Current price and recent performance
3. Technical analysis (trend, momentum, support/resistance)
4. Fundamental valuation (is it cheap, fair, or expensive vs peers?)
5. Key risks and opportunities
6. Summary verdict (bullish / neutral / bearish) with reasoning

Always call multiple tools to gather comprehensive data before writing your analysis.
Present numbers clearly. Be direct and opinionated — traders want a clear view,
not a disclaimer-heavy hedge. Include a disclaimer that this is for informational
purposes only and not financial advice."""


def run_analysis(ticker: str, verbose: bool = False) -> str:
    """
    Run a full stock analysis for the given ticker.
    Returns the final analysis text.
    """
    client = anthropic.Anthropic()

    messages = [
        {
            "role": "user",
            "content": f"Please provide a comprehensive stock analysis for {ticker.upper()}.",
        }
    ]

    print(f"\nAnalyzing {ticker.upper()}...\n")

    # Agentic loop: Claude calls tools until it has enough data
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Log token usage
        log_token_usage(
            call_type="analyze",
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        )

        # Collect tool use blocks
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if verbose:
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [tool] {block.name}({json.dumps(block.input)})")
                elif block.type == "thinking":
                    print(f"  [thinking] {block.thinking[:200]}...")

        # Done when no more tool calls
        if response.stop_reason == "end_turn" or not tool_use_blocks:
            final_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            return final_text

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # Execute all tool calls and collect results
        tool_results = []
        for tool_use in tool_use_blocks:
            if verbose:
                print(f"  [fetching] {tool_use.name}...")
            result = execute_tool(tool_use.name, tool_use.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                }
            )

        messages.append({"role": "user", "content": tool_results})
