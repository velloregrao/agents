"""
FastAPI HTTP wrapper for the stock trading agent.

Public surface:
    POST /agent   — single platform-agnostic endpoint, used by all channel adapters
    GET  /health  — liveness probe

Legacy per-intent endpoints (/analyze, /trade, /research, /portfolio, /reflect,
/monitor) are retained for direct API testing but are no longer called by any
channel adapter.

Routing architecture (Phase 2+):
    /agent delegates all classification and dispatch to orchestrator/router.py,
    which uses Claude Haiku for intent detection (fast, cheap) with a regex
    fallback, then fans out to the correct agent pipeline.
"""

import os
import json
import sys
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
from stock_agent.research import run_research_orchestrator

# Make orchestrator/ importable from api.py
# (agents root is 3 levels above this file: src/stock_agent/api.py → agents/)
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))

from orchestrator.router import route as _route
from orchestrator.contracts import AgentMessage

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
# Implementation lives in stock_agent/research.py — imported at top of file.

@app.post("/research")
def research(req: ResearchRequest):
    ticker = req.ticker.upper()
    user_request = req.request or f"Research {ticker} and give me a detailed buy/hold/sell recommendation"
    try:
        return {"result": run_research_orchestrator(ticker, user_request)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── /agent — single platform-agnostic endpoint ────────────────────────────────
# All routing and classification now lives in orchestrator/router.py.
# This endpoint is a thin HTTP adapter: deserialise → AgentMessage → route() → serialise.

class AgentRequest(BaseModel):
    user_id:   str
    platform:  str = "teams"
    text:      str
    thread_id: str = ""
    timestamp: str = ""

class AgentResponseModel(BaseModel):
    intent:            str
    text:              str
    requires_approval: bool        = False
    approval_context:  dict | None = None

@app.post("/agent", response_model=AgentResponseModel)
def agent_endpoint(req: AgentRequest):
    """
    Single entry point for all channel adapters.

    Constructs a normalised AgentMessage and delegates entirely to
    orchestrator/router.route(), which handles Haiku classification,
    regex fallback, and pipeline dispatch.
    """
    try:
        msg = AgentMessage(
            user_id=req.user_id,
            platform=req.platform,
            text=req.text,
            thread_id=req.thread_id,
            timestamp=req.timestamp,
        )
        resp = _route(msg)
        return AgentResponseModel(
            intent=resp.intent,
            text=resp.text,
            requires_approval=resp.requires_approval,
            approval_context=resp.approval_context,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stock_agent.api:app", host="0.0.0.0", port=8000, reload=True)
