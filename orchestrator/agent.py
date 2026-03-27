import anthropic
import json
import os
import sys

sys.path.insert(0, "/Users/velloregrao/Projects/agents/stock-analysis-agent/src")

from dotenv import load_dotenv

load_dotenv("/Users/velloregrao/Projects/agents/stock-analysis-agent/.env")

# Import all tools from each MCP server
from stock_agent.tools import (
    get_stock_info,
    get_current_price,
    get_technical_indicators,
    get_fundamentals,
)
from stock_agent.alpaca_tools import (
    get_account_balance,
    get_positions,
    place_order,
    close_position,
)
from stock_agent.memory import (
    get_open_trades,
    get_recent_trades,
    get_lessons,
    get_performance_summary,
    initialize_db,
)

initialize_db()

# ── Tool registry ──────────────────────────────────────────────────────────────


def handle_tool(name: str, inputs: dict) -> str:
    try:
        if name == "get_stock_info":
            return json.dumps(get_stock_info(inputs["ticker"]))
        elif name == "get_current_price":
            return json.dumps(get_current_price(inputs["ticker"]))
        elif name == "get_technical_indicators":
            return json.dumps(
                get_technical_indicators(inputs["ticker"], inputs.get("period", "6mo"))
            )
        elif name == "get_fundamentals":
            return json.dumps(get_fundamentals(inputs["ticker"]))
        elif name == "get_account_balance":
            return json.dumps(get_account_balance())
        elif name == "get_positions":
            return json.dumps(get_positions())
        elif name == "place_order":
            return json.dumps(
                place_order(inputs["ticker"], inputs["quantity"], inputs["side"])
            )
        elif name == "close_position":
            return json.dumps(close_position(inputs["ticker"]))
        elif name == "get_open_trades":
            return json.dumps(get_open_trades())
        elif name == "get_recent_trades":
            return json.dumps(get_recent_trades())
        elif name == "get_lessons":
            return json.dumps(
                get_lessons(ticker=inputs.get("ticker"), sector=inputs.get("sector"))
            )
        elif name == "get_performance_summary":
            return json.dumps(get_performance_summary())
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool definitions (what Claude sees) ───────────────────────────────────────

TOOLS = [
    {
        "name": "get_stock_info",
        "description": "Get company overview, sector, market cap for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_current_price",
        "description": "Get live price, volume and intraday change.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": "Get RSI, MACD, Bollinger Bands, SMA20, SMA50.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "period": {"type": "string", "default": "6mo"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": "Get P/E, revenue, margins, analyst ratings.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_account_balance",
        "description": "Get Alpaca paper trading account balance and buying power.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_positions",
        "description": "Get all open positions in the paper trading account.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "place_order",
        "description": "Place a paper trade. Side must be BUY or SELL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quantity": {"type": "integer"},
                "side": {"type": "string", "enum": ["BUY", "SELL"]},
            },
            "required": ["ticker", "quantity", "side"],
        },
    },
    {
        "name": "close_position",
        "description": "Close an entire position for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_open_trades",
        "description": "Get all currently open trades tracked in memory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_trades",
        "description": "Get recent trade history with P&L and reasoning.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_lessons",
        "description": "Get lessons learned from past trades, optionally filtered by ticker or sector.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}, "sector": {"type": "string"}},
        },
    },
    {
        "name": "get_performance_summary",
        "description": "Get overall trading performance: win rate, total P&L, avg return.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ── Orchestrator system prompt ─────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert stock trading orchestrator managing a paper trading portfolio.

You have access to 4 specialized data sources via tools:
- MARKET DATA: get_stock_info, get_current_price, get_technical_indicators, get_fundamentals
- PORTFOLIO: get_account_balance, get_positions, place_order, close_position  
- MEMORY: get_open_trades, get_recent_trades, get_lessons, get_performance_summary

Your decision-making process for ANY research or trade request:
1. ALWAYS start by checking get_lessons (past lessons inform current decisions)
2. ALWAYS check get_account_balance before any trade recommendation
3. Get technical indicators AND fundamentals before recommending
4. Check get_positions to avoid over-concentration in one stock
5. Apply position sizing: max 5% of portfolio per trade

Your output format:
- Lead with a clear BUY / HOLD / SELL decision
- Show the key data points that drove the decision
- Reference specific past lessons if applicable
- If recommending a trade: show exact quantity and position size as % of portfolio
- Flag any risks clearly
"""


# ── Main orchestrator loop ─────────────────────────────────────────────────────


def run_orchestrator(user_request: str) -> str:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_request}]

    print(f"\n{'='*60}")
    print(f"ORCHESTRATOR: {user_request}")
    print(f"{'='*60}")

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Collect tool calls and text
        tool_calls = []
        text_parts = []

        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(block)
                print(f"→ Calling: {block.name}({json.dumps(block.input)})")
            elif block.type == "text" and block.text:
                text_parts.append(block.text)

        # If no tool calls — final answer
        if response.stop_reason == "end_turn":
            final = "\n".join(text_parts)
            print(f"\nFINAL ANSWER:\n{final}")
            return final

        # Execute all tool calls
        tool_results = []
        for tc in tool_calls:
            result = handle_tool(tc.name, tc.input)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tc.id, "content": result}
            )

        # Feed results back to Claude
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    request = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "Research AAPL and give me a recommendation"
    )
    result = run_orchestrator(request)
