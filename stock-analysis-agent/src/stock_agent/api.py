"""
FastAPI HTTP wrapper for the stock trading agent.
Replaces Python subprocess calls from the Teams bot with proper HTTP endpoints.
"""

import os
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
from stock_agent.trading_agent import run_trading_agent, monitor_positions
from stock_agent.reflection import reflect
from stock_agent.alpaca_tools import place_order, close_position
from stock_agent.memory import get_recent_trades, get_lessons

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


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stock_agent.api:app", host="0.0.0.0", port=8000, reload=True)
