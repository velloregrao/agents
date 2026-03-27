"""
Full learning trading agent loop.
Combines stock analysis, Alpaca paper trading, memory and reflection.
"""

import os
import json
from anthropic import Anthropic
from dotenv import load_dotenv

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
    get_order_history,
    close_position,
)
from stock_agent.memory import (
    store_trade,
    close_trade,
    get_open_trades,
    get_performance_summary,
    initialize_db,
    log_token_usage,
)
from stock_agent.reflection import get_relevant_lessons, reflect

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Tool definitions for Claude ───────────────────────────────────────────────
TOOLS = [
    {
        "name": "get_stock_info",
        "description": "Get company overview including sector, market cap and business description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_current_price",
        "description": "Get current price, day change, 52-week high/low and volume.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_technical_indicators",
        "description": "Get RSI, MACD, SMA, EMA and Bollinger Bands with signal interpretations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "period": {
                    "type": "string",
                    "enum": ["3mo", "6mo", "1y", "2y"],
                    "description": "History period for calculation"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_fundamentals",
        "description": "Get P/E, P/B, margins, debt/equity and analyst recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_account_balance",
        "description": "Get current paper trading account balance and buying power.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_positions",
        "description": "Get all open positions with unrealized P&L.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "place_order",
        "description": "Place a paper trade market order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "quantity": {"type": "integer", "description": "Number of shares"},
                "side": {"type": "string", "enum": ["BUY", "SELL"], "description": "Order side"}
            },
            "required": ["ticker", "quantity", "side"]
        }
    },
    {
        "name": "close_position",
        "description": "Close an entire position for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker to close"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_open_trades",
        "description": "Get all open trades tracked in memory store.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_performance_summary",
        "description": "Get overall trading performance statistics including win rate and total P&L.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "store_trade",
        "description": "Save a placed trade to memory. Call this immediately after every successful place_order. Pass the order_id from place_order result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id":    {"type": "string",  "description": "Order ID from place_order"},
                "ticker":      {"type": "string",  "description": "Stock ticker symbol"},
                "side":        {"type": "string",  "enum": ["BUY", "SELL"], "description": "Order side"},
                "quantity":    {"type": "number",  "description": "Number of shares"},
                "entry_price": {"type": "number",  "description": "Estimated entry price"},
                "entry_rsi":   {"type": "number",  "description": "RSI at time of entry"},
                "sector":      {"type": "string",  "description": "Stock sector"},
                "reasoning":   {"type": "string",  "description": "Why this trade was placed"}
            },
            "required": ["order_id", "ticker", "side", "quantity", "entry_price"]
        }
    },
    {
        "name": "close_trade",
        "description": "Record a trade as closed in memory. Call this after closing a position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id":      {"type": "string", "description": "Original order ID of the trade to close"},
                "exit_price":    {"type": "number", "description": "Exit price"},
                "outcome_notes": {"type": "string", "description": "Why the position was closed"}
            },
            "required": ["order_id", "exit_price"]
        }
    },
]

# ── Tool executor ─────────────────────────────────────────────────────────────
def execute_tool(name: str, inputs: dict) -> str:
    """Execute a tool by name and return result as string."""
    tool_map = {
        "get_stock_info": get_stock_info,
        "get_current_price": get_current_price,
        "get_technical_indicators": get_technical_indicators,
        "get_fundamentals": get_fundamentals,
        "get_account_balance": get_account_balance,
        "get_positions": get_positions,
        "place_order": place_order,
        "close_position": close_position,
        "get_open_trades": get_open_trades,
        "get_performance_summary": get_performance_summary,
        "store_trade": store_trade,
        "close_trade": close_trade,
    }

    if name not in tool_map:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = tool_map[name](**inputs)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Main agent ────────────────────────────────────────────────────────────────
def run_trading_agent(watchlist: list[str], user_request: str = None) -> str:
    """
    Run the full trading agent loop.

    Args:
        watchlist:    List of tickers to analyze e.g. ["AAPL", "MSFT", "TSLA"]
        user_request: Optional specific instruction from user
    """
    initialize_db()

    # Get relevant lessons from memory
    lessons = get_relevant_lessons(
        ticker=watchlist[0] if watchlist else "general",
        sector=None,
        rsi=None
    )

    # Get performance summary
    performance = get_performance_summary()

    # Build system prompt with memory context
    lessons_text = "\n".join(f"- {l}" for l in lessons) if lessons else "No lessons yet — this is early learning."
    performance_text = json.dumps(performance, indent=2)

    system_prompt = f"""You are an intelligent paper trading agent that learns from experience.

## Your Responsibilities
1. Analyze stocks from the watchlist using available tools
2. Make data-driven trading decisions based on technical and fundamental analysis
3. Apply lessons learned from past trades
4. Place paper trades via Alpaca when you identify strong opportunities
5. Monitor open positions and close them when exit criteria are met
6. Always explain your reasoning clearly

## Lessons Learned From Past Trades
{lessons_text}

## Current Performance
{performance_text}

## Trading Rules
- Only trade stocks with clear technical AND fundamental support
- Maximum 5% of portfolio per position
- RSI below 30 = potential buy signal (oversold)
- RSI above 70 = potential sell signal (overbought)
- Always check account balance before placing orders
- Always store reasoning when placing trades
- This is paper trading — be bold enough to learn but disciplined enough to improve

## Important
- After EVERY successful place_order, you MUST immediately call store_trade with the order_id, ticker, side, quantity, entry_price, entry_rsi, sector, and your reasoning
- After EVERY successful close_position, you MUST immediately call close_trade with the original order_id, exit_price, and outcome_notes
- Explain every decision clearly so the system can learn from it
- This is for educational purposes only — not financial advice"""

    # Build user message
    if user_request:
        user_message = user_request
    else:
        user_message = f"""Please analyze the following watchlist and make trading decisions:
Watchlist: {', '.join(watchlist)}

For each stock:
1. Gather price, technical indicators and fundamentals
2. Apply lessons from past trades
3. Decide: BUY, SELL existing position, or HOLD
4. If trading, place the order and explain reasoning
5. After reviewing all stocks, summarize your decisions and current portfolio status"""

    messages = [{"role": "user", "content": user_message}]

    print(f"\n{'='*60}")
    print(f"Trading Agent Running")
    print(f"Watchlist: {', '.join(watchlist)}")
    print(f"{'='*60}\n")

    # ── Agentic loop ──────────────────────────────────────────
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        log_token_usage(
            call_type="trade",
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        )

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if response.stop_reason == "end_turn" or not tool_use_blocks:
            # Final response
            final_text = " ".join(
                b.text for b in response.content if b.type == "text"
            )
            print("\n" + "="*60)
            print("AGENT DECISION:")
            print("="*60)
            print(final_text)
            return final_text

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []

        for tool_use in tool_use_blocks:
            print(f"→ Calling: {tool_use.name}({json.dumps(tool_use.input)})")
            result = execute_tool(tool_use.name, tool_use.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})


# ── Monitor open positions ────────────────────────────────────────────────────
def monitor_positions() -> str:
    """Check open positions and close any that hit exit criteria."""
    initialize_db()

    open_trades = get_open_trades().get("open_trades", [])
    if not open_trades:
        print("No open positions to monitor.")
        return "No open positions."

    tickers = [t["ticker"] for t in open_trades]
    request = f"""Please monitor these open positions and decide whether to close any:
Open positions: {', '.join(tickers)}

For each position:
1. Get current price and RSI
2. Compare to entry price and entry RSI stored in memory
3. Apply exit rules: RSI > 70 = consider selling, loss > 5% = stop loss
4. Close position if exit criteria met
5. Summarize what you did and why"""

    return run_trading_agent(tickers, request)


# ── Weekly reflection ─────────────────────────────────────────────────────────
def run_weekly_reflection() -> dict:
    """Run weekly reflection to extract lessons from recent trades."""
    print("\nRunning weekly reflection...")
    result = reflect(min_trades=3)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    # Run the agent on a sample watchlist
    result = run_trading_agent(
        watchlist=["AAPL", "MSFT", "TSLA"],
        user_request=None
    )
