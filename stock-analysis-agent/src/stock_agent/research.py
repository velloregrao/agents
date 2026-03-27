"""
Multi-agent research orchestrator.

Runs a full agentic loop using Claude Sonnet + all available data tools to
produce a deep buy/hold/sell recommendation for a single ticker.

Extracted from api.py into its own module so it can be imported by both:
  - api.py (legacy /research endpoint)
  - orchestrator/router.py (via the /agent dispatch path)
without creating a circular import dependency.
"""

import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

from stock_agent.tools import (
    get_stock_info,
    get_current_price,
    get_technical_indicators,
    get_fundamentals,
)
from stock_agent.alpaca_tools import get_account_balance, get_positions
from stock_agent.memory import get_open_trades, get_lessons, get_performance_summary

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SONNET = "claude-sonnet-4-6"

# ── Tool definitions ───────────────────────────────────────────────────────────

ORCHESTRATOR_TOOLS = [
    {
        "name": "get_stock_info",
        "description": "Get company overview, sector, market cap.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    },
    {
        "name": "get_current_price",
        "description": "Get live price, volume, intraday change.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    },
    {
        "name": "get_technical_indicators",
        "description": "Get RSI, MACD, Bollinger Bands, SMA20, SMA50.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}, "period": {"type": "string", "default": "6mo"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": "Get P/E, revenue, margins, analyst ratings.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    },
    {
        "name": "get_account_balance",
        "description": "Get Alpaca paper account balance and buying power.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_positions",
        "description": "Get all open positions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_open_trades",
        "description": "Get open trades from memory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_lessons",
        "description": "Get lessons from past trades.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}, "sector": {"type": "string"}},
        },
    },
    {
        "name": "get_performance_summary",
        "description": "Get overall trading performance summary.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

ORCHESTRATOR_SYSTEM = """You are an expert stock trading orchestrator managing a paper trading portfolio.

Your decision-making process for ANY research request:
1. ALWAYS call get_positions AND get_open_trades first — explicitly state whether the user currently holds this stock
2. Check get_lessons for past lessons on this ticker/sector
3. ALWAYS check get_account_balance before any trade recommendation
4. Get technical indicators AND fundamentals before recommending
5. Apply position sizing: max 5% of portfolio per trade

Output format:
- Start with "📦 Current Position: You hold X shares of TICKER" or "📦 Current Position: None"
- Then lead with BUY / HOLD / SELL decision
- Show key data points that drove the decision
- Reference specific past lessons if applicable
- If recommending a trade: show exact quantity and position size as % of portfolio
- Flag risks clearly
- Note: for informational purposes only, not financial advice"""


def _handle_tool(name: str, inputs: dict) -> str:
    """Execute a named tool and return JSON-encoded result."""
    try:
        if name == "get_stock_info":
            return json.dumps(get_stock_info(inputs["ticker"]))
        elif name == "get_current_price":
            return json.dumps(get_current_price(inputs["ticker"]))
        elif name == "get_technical_indicators":
            return json.dumps(get_technical_indicators(inputs["ticker"], inputs.get("period", "6mo")))
        elif name == "get_fundamentals":
            return json.dumps(get_fundamentals(inputs["ticker"]))
        elif name == "get_account_balance":
            return json.dumps(get_account_balance())
        elif name == "get_positions":
            return json.dumps(get_positions())
        elif name == "get_open_trades":
            return json.dumps(get_open_trades())
        elif name == "get_lessons":
            return json.dumps(get_lessons(ticker=inputs.get("ticker"), sector=inputs.get("sector")))
        elif name == "get_performance_summary":
            return json.dumps(get_performance_summary())
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def run_research_orchestrator(ticker: str, user_request: str) -> str:
    """
    Agentic research loop: Claude Sonnet calls tools until it has enough data
    to produce a full buy/hold/sell recommendation.

    Args:
        ticker:       Primary ticker being researched (used for logging).
        user_request: Full user message forwarded as the initial prompt.

    Returns:
        Markdown-formatted recommendation string.
    """
    messages = [{"role": "user", "content": user_request}]
    while True:
        response = _client.messages.create(
            model=SONNET,
            max_tokens=4096,
            system=ORCHESTRATOR_SYSTEM,
            tools=ORCHESTRATOR_TOOLS,
            messages=messages,
        )
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "end_turn":
            return " ".join(b.text for b in response.content if b.type == "text")
        tool_results = []
        for tc in tool_calls:
            result = _handle_tool(tc.name, tc.input)
            tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": result})
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
