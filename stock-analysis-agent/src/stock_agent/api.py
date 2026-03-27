"""
FastAPI HTTP wrapper for the stock trading agent.

Public surface:
    POST /agent   — single platform-agnostic endpoint, used by all channel adapters
    GET  /health  — liveness probe

Legacy per-intent endpoints (/analyze, /trade, /research, /portfolio, /reflect,
/monitor) are retained for direct API testing but are no longer called by any
channel adapter.
"""

import os
import re
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=True)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

from stock_agent.tools import (
    get_stock_info,
    get_current_price,
    get_technical_indicators,
    get_fundamentals,
)
from stock_agent.alpaca_tools import get_account_balance, get_positions
from stock_agent.memory import (
    get_open_trades,
    get_performance_summary,
    initialize_db,
)
from stock_agent.agent import run_analysis
from stock_agent.trading_agent import run_trading_agent, monitor_positions
from stock_agent.reflection import reflect
from stock_agent.alpaca_tools import place_order, close_position
from stock_agent.memory import get_recent_trades, get_lessons

# Make orchestrator/ importable from api.py
# (agents root is 3 levels above this file)
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))

app = FastAPI(title="Stock Trading Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


@app.on_event("startup")
def startup():
    initialize_db()


# ── Request models ────────────────────────────────────────────────────────────

class TickerRequest(BaseModel):
    ticker: str

class TradeRequest(BaseModel):
    tickers: list[str]
    request: str = ""

class ResearchRequest(BaseModel):
    ticker: str
    request: str = ""


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "stock-agent-api", "version": "2"}


# ── Analyze a single stock ────────────────────────────────────────────────────

@app.post("/analyze")
def analyze(req: TickerRequest):
    ticker = req.ticker.upper()
    try:
        info  = get_stock_info(ticker)
        price = get_current_price(ticker)
        tech  = get_technical_indicators(ticker, "6mo")
        fund  = get_fundamentals(ticker)

        raw = json.dumps({
            "info": info, "price": price,
            "technicals": tech, "fundamentals": fund,
        }, default=str)

        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a stock analyst. Analyze this data for {ticker} "
                    "and provide a clear, structured analysis with a "
                    "bullish/neutral/bearish verdict.\n\n"
                    f"Data: {raw}\n\n"
                    "Note: For informational purposes only — not financial advice."
                ),
            }],
        )
        text = " ".join(b.text for b in response.content if b.type == "text")
        return {"result": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Run trading agent ─────────────────────────────────────────────────────────

@app.post("/trade")
def trade(req: TradeRequest):
    try:
        result = run_trading_agent(req.tickers, req.request or None)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Get portfolio ─────────────────────────────────────────────────────────────

@app.get("/portfolio")
def portfolio():
    try:
        return {
            "balance":     get_account_balance(),
            "positions":   get_positions(),
            "open_trades": get_open_trades(),
            "performance": get_performance_summary(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Run reflection ────────────────────────────────────────────────────────────

@app.post("/reflect")
def do_reflect():
    try:
        return reflect(min_trades=1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Monitor positions ─────────────────────────────────────────────────────────

@app.post("/monitor")
def do_monitor():
    try:
        result = monitor_positions()
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Research endpoint (multi-agent orchestrator) ──────────────────────────────

ORCHESTRATOR_TOOLS = [
    {"name": "get_stock_info", "description": "Get company overview, sector, market cap.", "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "get_current_price", "description": "Get live price, volume, intraday change.", "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "get_technical_indicators", "description": "Get RSI, MACD, Bollinger Bands, SMA20, SMA50.", "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}, "period": {"type": "string", "default": "6mo"}}, "required": ["ticker"]}},
    {"name": "get_fundamentals", "description": "Get P/E, revenue, margins, analyst ratings.", "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
    {"name": "get_account_balance", "description": "Get Alpaca paper account balance and buying power.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_positions", "description": "Get all open positions.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_open_trades", "description": "Get open trades from memory.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_lessons", "description": "Get lessons from past trades.", "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}, "sector": {"type": "string"}}}},
    {"name": "get_performance_summary", "description": "Get overall trading performance summary.", "input_schema": {"type": "object", "properties": {}}},
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

def _handle_orchestrator_tool(name: str, inputs: dict) -> str:
    try:
        if name == "get_stock_info":         return json.dumps(get_stock_info(inputs["ticker"]))
        elif name == "get_current_price":    return json.dumps(get_current_price(inputs["ticker"]))
        elif name == "get_technical_indicators": return json.dumps(get_technical_indicators(inputs["ticker"], inputs.get("period", "6mo")))
        elif name == "get_fundamentals":     return json.dumps(get_fundamentals(inputs["ticker"]))
        elif name == "get_account_balance":  return json.dumps(get_account_balance())
        elif name == "get_positions":        return json.dumps(get_positions())
        elif name == "get_open_trades":      return json.dumps(get_open_trades())
        elif name == "get_lessons":          return json.dumps(get_lessons(ticker=inputs.get("ticker"), sector=inputs.get("sector")))
        elif name == "get_performance_summary": return json.dumps(get_performance_summary())
        else: return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})

def run_research_orchestrator(ticker: str, user_request: str) -> str:
    """
    Agentic research loop: Claude calls tools until it has enough data
    to produce a full buy/hold/sell recommendation.
    Extracted from the /research endpoint so it can be reused by
    orchestrator/router.py in Phase 2.
    """
    messages = [{"role": "user", "content": user_request}]
    while True:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
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
            result = _handle_orchestrator_tool(tc.name, tc.input)
            tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": result})
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


@app.post("/research")
def research(req: ResearchRequest):
    ticker = req.ticker.upper()
    user_request = req.request or f"Research {ticker} and give me a detailed buy/hold/sell recommendation"
    try:
        return {"result": run_research_orchestrator(ticker, user_request)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Intent routing (ported from teamsBot.ts parseIntent) ─────────────────────
# Phase 2 will replace this regex approach with Claude Haiku classification.

_SKIP_WORDS = {
    "ANALYZE", "ANALYSIS", "STOCK", "SHARE", "PRICE", "GET", "SHOW",
    "TELL", "WHAT", "HOW", "IS", "THE", "FOR", "ME", "TRADE", "TRADES",
    "BUY", "SELL", "PORTFOLIO", "PERFORMANCE", "REFLECT", "REFLECTION",
    "MONITOR", "POSITIONS", "HELP", "HI", "HELLO", "AND", "ON", "A",
    "RUN", "CHECK", "MY",
}

def _parse_intent(text: str) -> tuple[str, list[str]]:
    """Classify intent and extract ticker symbols from raw user text."""
    upper = text.upper()
    words = re.sub(r"[^A-Z\s]", "", upper).split()
    tickers = [w for w in words if 1 <= len(w) <= 5 and w not in _SKIP_WORDS]

    if re.match(r"^(hi|hello|hey|help)$", text.strip(), re.IGNORECASE):
        return "help", []
    if re.search(r"monitor|check\s+positions|review\s+positions", text, re.IGNORECASE):
        return "monitor", []
    if re.search(r"portfolio|positions|holdings", text, re.IGNORECASE):
        return "portfolio", tickers
    if re.search(r"performance|stats|statistics|pnl|profit", text, re.IGNORECASE):
        return "portfolio", tickers
    if re.search(r"reflect|reflection|lessons|learn", text, re.IGNORECASE):
        return "reflect", []
    if re.search(r"research|deep.?dive|full.?analysis|recommend", text, re.IGNORECASE) and tickers:
        return "research", tickers
    if re.search(r"trade|buy|sell|invest|run\s+agent", text, re.IGNORECASE) and tickers:
        return "trade", tickers
    if tickers:
        return "analyze", tickers
    return "unknown", []


# ── Portfolio formatter (ported from teamsBot.ts getPortfolio) ────────────────

def _format_portfolio() -> str:
    """Fetch portfolio data and return markdown-formatted summary."""
    balance  = get_account_balance()
    pos_data = get_positions()
    perf     = get_performance_summary()

    if balance.get("error"):
        return f"❌ Alpaca API error: {balance['error']}"

    def fmt(n) -> str:
        try:
            return f"{float(n):,.2f}"
        except (TypeError, ValueError):
            return "N/A"

    positions = pos_data.get("positions", [])

    lines = [
        "## 📊 Portfolio Status\n",
        f"**Cash:** ${fmt(balance.get('cash'))}  "
        f"**Portfolio Value:** ${fmt(balance.get('portfolio_value'))}  "
        f"**Buying Power:** ${fmt(balance.get('buying_power'))}\n",
    ]

    if positions:
        lines.append("### Open Positions")
        for p in positions:
            pnl     = float(p.get("unrealized_pnl") or 0)
            pnl_pct = float(p.get("unrealized_pnl_pct") or 0)
            emoji   = "📈" if pnl >= 0 else "📉"
            sign    = "+" if pnl >= 0 else ""
            lines.append(
                f"- **{p['ticker']}**: {p['quantity']} shares "
                f"@ ${fmt(p.get('entry_price'))} | "
                f"Current: ${fmt(p.get('current_price'))} | "
                f"{emoji} {sign}${pnl:.2f} ({pnl_pct:.1f}%)"
            )
    else:
        lines.append("### No open positions")

    if perf.get("total_trades", 0) > 0:
        lines += [
            "\n### Performance",
            f"- **Total Trades:** {perf['total_trades']}",
            f"- **Win Rate:** {perf.get('win_rate')}%",
            f"- **Total P&L:** ${perf.get('total_pnl')}",
            f"- **Avg Return:** {perf.get('avg_return_pct')}%",
        ]

    return "\n".join(lines)


# ── Intent dispatcher ─────────────────────────────────────────────────────────

def _dispatch(intent: str, tickers: list[str], raw_text: str) -> str:
    """Route a classified intent to the correct agent pipeline."""
    if intent == "help":
        return (
            "## 🤖 Stock Trading Agent\n\n"
            "**Commands:**\n"
            "- **Analyze AAPL** — Quick stock analysis\n"
            "- **Research NVDA** — Deep multi-agent research (news + technicals + memory)\n"
            "- **Trade AAPL MSFT TSLA** — Run trading agent on watchlist\n"
            "- **Portfolio** — Show positions and balance\n"
            "- **Reflect** — Extract lessons from trade history\n"
            "- **Monitor** — Review open positions for exits\n\n"
            "*Powered by Claude + Alpaca paper trading*"
        )

    if intent == "analyze" and tickers:
        return run_analysis(tickers[0])

    if intent == "research" and tickers:
        user_request = raw_text or f"Research {tickers[0]} and give me a detailed buy/hold/sell recommendation"
        return run_research_orchestrator(tickers[0], user_request)

    if intent == "trade" and tickers:
        return run_trading_agent(tickers, raw_text or None)

    if intent == "portfolio":
        return _format_portfolio()

    if intent == "reflect":
        result = reflect(min_trades=1)
        if result.get("status") == "skipped":
            return f"⚠️ {result['reason']}"
        lines = [
            "## 🧠 Reflection Complete\n",
            f"**Trades Analyzed:** {result.get('trades_analyzed')}",
            f"**Lessons Extracted:** {result.get('lessons_extracted')}\n",
            "### New Lessons",
        ]
        for i, lesson in enumerate(result.get("lessons", []), 1):
            lines.append(f"{i}. {lesson}")
        lines.append(f"\n### Summary\n{result.get('summary', '')}")
        return "\n".join(lines)

    if intent == "monitor":
        return monitor_positions()

    return (
        "I didn't understand that. Try:\n"
        "- **Analyze AAPL**\n"
        "- **Trade AAPL MSFT**\n"
        "- **Portfolio**\n"
        "- **Reflect**\n"
        "- **Monitor**"
    )


# ── /agent — single platform-agnostic endpoint ────────────────────────────────

class AgentRequest(BaseModel):
    user_id:   str
    platform:  str = "teams"
    text:      str
    thread_id: str = ""
    timestamp: str = ""

class AgentResponseModel(BaseModel):
    intent:            str
    text:              str
    requires_approval: bool       = False
    approval_context:  dict | None = None

@app.post("/agent", response_model=AgentResponseModel)
def agent_endpoint(req: AgentRequest):
    """
    Single entry point for all channel adapters.
    Receives a normalised AgentMessage, returns a normalised AgentResponse.
    Phase 2 will replace _parse_intent() with Claude Haiku classification
    inside orchestrator/router.py.
    """
    try:
        intent, tickers = _parse_intent(req.text)
        text = _dispatch(intent, tickers, req.text)
        return AgentResponseModel(intent=intent, text=text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stock_agent.api:app", host="0.0.0.0", port=8000, reload=True)
