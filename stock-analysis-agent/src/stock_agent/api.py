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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import anthropic

# ── API key auth ───────────────────────────────────────────────────────────────
# Set AGENT_API_KEY in .env to require X-API-Key header on all requests.
# Leave unset (or empty) for open access during local development.
# Health endpoints are always exempt so liveness probes never need a key.

_API_KEY = os.getenv("AGENT_API_KEY", "").strip() or None
_AUTH_EXEMPT = {
    "/health",
    "/health/deep",
    "/openapi-custom-gpt.json",
}

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
from stock_agent.watchlist import initialize_db as initialize_watchlist_db
from stock_agent.agent import run_analysis

# Alert manager lives in the orchestrator package (imported after sys.path is set below)
from stock_agent.trading_agent import run_trading_agent, monitor_positions
from stock_agent.reflection import reflect
from stock_agent.research import run_research_orchestrator

# Make orchestrator/ importable from api.py.
# Local:     agents/stock-analysis-agent/src/stock_agent/api.py → 4 parents = agents/
# Container: /app/src/stock_agent/api.py                        → 3 parents = /app/
# Walk up until we find orchestrator/ to handle both layouts.
_HERE = Path(__file__).resolve()
_AGENTS_ROOT = next(
    p for p in [_HERE.parent.parent.parent, _HERE.parent.parent.parent.parent]
    if (p / "orchestrator").exists()
)
sys.path.insert(0, str(_AGENTS_ROOT))

from orchestrator.router import route as _route
from orchestrator.contracts import AgentMessage
from orchestrator.approval_manager import get_pending, resolve as resolve_approval
from orchestrator import scheduler as _scheduler
from orchestrator.alert_manager import (
    initialize_db as initialize_alert_db,
    store_conversation_ref,
    get_pending_alerts,
    mark_alert_delivered,
    queue_alert as _queue_alert,
)

app = FastAPI(title="Stock Trading Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """
    Enforce X-API-Key header when AGENT_API_KEY is configured.

    Exempt paths (/health, /health/deep) bypass auth so container liveness
    probes and load-balancer checks never need a key.

    When AGENT_API_KEY is not set the middleware is a transparent no-op,
    keeping local development zero-friction.
    """
    if _API_KEY and request.method != "OPTIONS" and request.url.path not in _AUTH_EXEMPT:
        provided = (
            request.headers.get("X-API-Key")
            or request.query_params.get("api_key")
        )
        if provided != _API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Pass X-API-Key header."},
            )
    return await call_next(request)


_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


@app.on_event("startup")
def startup():
    initialize_db()
    initialize_watchlist_db()
    initialize_alert_db()
    _scheduler.start()


@app.on_event("shutdown")
def shutdown():
    _scheduler.stop()


# ── Request models ────────────────────────────────────────────────────────────

class TickerRequest(BaseModel):
    ticker: str

class TradeRequest(BaseModel):
    tickers: list[str]
    request: str = ""

class ResearchRequest(BaseModel):
    ticker: str
    request: str = ""


# ── Health checks ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "stock-agent-api", "version": "2"}


@app.get("/health/deep")
def health_deep():
    """
    Deep liveness probe — verifies every critical external dependency.

    Makes a real 1-token Haiku call to confirm the Anthropic API key is valid,
    and a real Alpaca call to confirm broker connectivity.

    Returns 200 {"status": "ok", "checks": {...}} if all pass.
    Returns 503 {"status": "degraded", "checks": {...}} if any fail.

    Used as a post-deploy gate in the GitHub Actions workflow so a bad key
    rotation or missing secret fails the pipeline before users are affected.
    """
    checks: dict[str, str] = {}

    # ── Anthropic ─────────────────────────────────────────────────────────────
    try:
        _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        checks["anthropic"] = "ok"
    except anthropic.AuthenticationError:
        checks["anthropic"] = "error: invalid API key"
    except Exception as e:
        checks["anthropic"] = f"error: {e}"

    # ── Alpaca ────────────────────────────────────────────────────────────────
    try:
        result = get_account_balance()
        if result.get("error"):
            checks["alpaca"] = f"error: {result['error']}"
        else:
            checks["alpaca"] = "ok"
    except Exception as e:
        checks["alpaca"] = f"error: {e}"

    overall = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if overall else 503,
        content={"status": "ok" if overall else "degraded", "checks": checks},
    )


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


# ── Live signals feed ─────────────────────────────────────────────────────────

@app.get("/signals")
def signals_feed(user_id: str = "default"):
    """
    Return live technical signals for the user's watchlist tickers.
    Falls back to a hardcoded default set if the watchlist is empty.

    Computes RSI-14, EMA-12/26, MACD, and SMA-50 via yfinance concurrently
    (one ThreadPoolExecutor per ticker).  No Claude calls — pure math.

    Signal labels:
      BUY SIGNAL  — RSI<35 (oversold), or MACD>0 + price>SMA50
      SELL SIGNAL — RSI>65 (overbought), or MACD<0 + price<SMA50
      WATCH       — everything else

    Returns a list sorted by confidence descending so strongest signals appear first.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime, timezone
    import yfinance as yf
    from stock_agent.watchlist import get_watchlist

    DEFAULT_TICKERS = ["TSLA", "META", "NVDA", "AMZN", "COIN", "SQ"]
    watchlist = get_watchlist(user_id)
    tickers   = watchlist if watchlist else DEFAULT_TICKERS
    source    = "watchlist" if watchlist else "default"

    def _fetch_signal(ticker: str) -> dict:
        try:
            stock = yf.Ticker(ticker)
            info  = stock.info
            hist  = stock.history(period="6mo")

            if hist.empty or len(hist) < 15:
                return {"ticker": ticker, "error": "insufficient history"}

            name       = info.get("shortName") or info.get("longName") or ticker
            price_raw  = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            price      = float(price_raw or hist["Close"].iloc[-1])
            prev       = float(prev_close or hist["Close"].iloc[-2])
            change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0

            close = hist["Close"].dropna()

            # RSI-14
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss
            rsi   = round(float(100 - (100 / (1 + rs.iloc[-1]))), 1)

            # EMA-12, EMA-26, MACD
            ema_12    = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
            ema_26    = float(close.ewm(span=26, adjust=False).mean().iloc[-1])
            macd_line = ema_12 - ema_26

            # SMA-50
            sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else price

            # EMA trend label (±0.5% tolerance)
            if   price > ema_26 * 1.005: ema_signal = "BULLISH"
            elif price < ema_26 * 0.995: ema_signal = "BEARISH"
            else:                         ema_signal = "NEUTRAL"

            # Signal label (RSI extremes take priority)
            if rsi < 35:
                signal = "BUY SIGNAL"
            elif rsi > 65:
                signal = "SELL SIGNAL"
            elif macd_line > 0 and price > sma_50:
                signal = "BUY SIGNAL"
            elif macd_line < 0 and price < sma_50:
                signal = "SELL SIGNAL"
            else:
                signal = "WATCH"

            # Momentum score (0–10)
            score = 5.0
            if   rsi < 35: score += 2.5
            elif rsi < 45: score += 1.0
            elif rsi > 65: score -= 2.5
            elif rsi > 55: score -= 1.0
            score += 1.5 if macd_line > 0 else -1.5
            score += 1.0 if price > sma_50 else -1.0
            score = max(0.0, min(10.0, round(score, 1)))

            # Confidence: fraction of 4 indicators agreeing on direction
            bull, bear = 0, 0
            if   rsi < 45: bull += 1
            elif rsi > 55: bear += 1
            if macd_line > 0: bull += 1
            else:             bear += 1
            if price > sma_50: bull += 1
            else:              bear += 1
            if   ema_signal == "BULLISH": bull += 1
            elif ema_signal == "BEARISH": bear += 1
            total      = bull + bear
            confidence = round((max(bull, bear) / total) * 100) if total else 50

            return {
                "ticker":         ticker,
                "name":           name,
                "price":          round(price, 2),
                "change_pct":     change_pct,
                "signal":         signal,
                "rsi":            rsi,
                "ema_signal":     ema_signal,
                "momentum_score": score,
                "confidence":     confidence,
                "as_of":          datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }
        except Exception as exc:
            return {"ticker": ticker, "error": str(exc)}

    signals: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as pool:
        futures = {pool.submit(_fetch_signal, t): t for t in tickers}
        for fut in as_completed(futures):
            res = fut.result()
            if res and "error" not in res:
                signals.append(res)

    signals.sort(key=lambda s: s.get("confidence", 0), reverse=True)

    return {
        "signals":           signals,
        "source":            source,
        "tickers_requested": tickers,
        "as_of":             datetime.now(timezone.utc).isoformat(),
    }


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
# Model definitions shared by /agent and /agent/approve

class AgentRequest(BaseModel):
    user_id:   str = "openai:gpt"
    platform:  str = "openai"
    text:      str
    thread_id: str = ""
    timestamp: str = ""

class AgentResponseModel(BaseModel):
    intent:            str
    text:              str
    requires_approval: bool        = False
    approval_context:  dict | None = None


# ── /agent/approve — human decision on an ESCALATED trade proposal ────────────

class ApproveRequest(BaseModel):
    approval_id: str
    decision:    str   # "approve" or "reject"
    user_id:     str = "openai:gpt"


def _custom_gpt_openapi(server_url: str) -> dict:
    """
    Return a minimal OpenAPI schema tailored for Custom GPT Actions.

    FastAPI's generated schema exposes the entire internal app surface. This
    smaller schema is easier to paste into the GPT builder and keeps the model
    focused on the two public interaction endpoints it actually needs.
    """
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Stock Trading Agent API",
            "version": "1.0.0",
            "description": (
                "Minimal schema for an OpenAI Custom GPT action. "
                "Use POST /agent for natural-language requests and "
                "POST /agent/approve to resolve escalated trades."
            ),
        },
        "servers": [{"url": server_url}],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                }
            },
            "schemas": {
                "HealthResponse": {
                    "type": "object",
                    "required": ["status", "service", "version"],
                    "properties": {
                        "status": {"type": "string"},
                        "service": {"type": "string"},
                        "version": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "AgentRequest": {
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "default": "openai:gpt",
                            "description": "Optional caller identifier for per-user state.",
                        },
                        "platform": {
                            "type": "string",
                            "default": "openai",
                            "description": "Calling channel name.",
                        },
                        "text": {
                            "type": "string",
                            "description": "The user's natural-language request.",
                        },
                        "thread_id": {
                            "type": "string",
                            "default": "",
                            "description": "Optional conversation or thread identifier.",
                        },
                        "timestamp": {
                            "type": "string",
                            "default": "",
                            "description": "Optional ISO-8601 timestamp.",
                        },
                    },
                },
                "AgentResponseModel": {
                    "type": "object",
                    "required": ["intent", "text"],
                    "properties": {
                        "intent": {"type": "string"},
                        "text": {"type": "string"},
                        "requires_approval": {
                            "type": "boolean",
                            "default": False,
                        },
                        "approval_context": {
                            "type": "object",
                            "nullable": True,
                            "additionalProperties": True,
                        },
                    },
                },
                "ApproveRequest": {
                    "type": "object",
                    "required": ["approval_id", "decision"],
                    "properties": {
                        "approval_id": {
                            "type": "string",
                            "description": "Opaque approval ID returned in approval_context.",
                        },
                        "decision": {
                            "type": "string",
                            "enum": ["approve", "reject"],
                        },
                        "user_id": {
                            "type": "string",
                            "default": "openai:gpt",
                        },
                    },
                },
            },
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "operationId": "getHealth",
                    "responses": {
                        "200": {
                            "description": "Service health status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/HealthResponse"
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/agent": {
                "post": {
                    "summary": "Send a message to the trading agent",
                    "operationId": "sendAgentMessage",
                    "security": [{"ApiKeyAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/AgentRequest"
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Agent response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/AgentResponseModel"
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/agent/approve": {
                "post": {
                    "summary": "Approve or reject an escalated trade",
                    "operationId": "resolveTradeApproval",
                    "security": [{"ApiKeyAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ApproveRequest"
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Approval resolution result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/AgentResponseModel"
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


@app.get("/openapi-custom-gpt.json")
def openapi_custom_gpt(request: Request):
    configured_base_url = os.getenv("PUBLIC_API_BASE_URL", "").strip()
    request_base_url = str(request.base_url).rstrip("/")
    server_url = configured_base_url or request_base_url
    if server_url.startswith("http://") and request.url.scheme == "https":
        server_url = "https://" + server_url[len("http://"):]
    return JSONResponse(_custom_gpt_openapi(server_url))

@app.post("/agent/approve", response_model=AgentResponseModel)
def approve_endpoint(req: ApproveRequest):
    """
    Receive a human Approve/Reject decision for an ESCALATED trade proposal.

    Called by channel adapters when the user clicks an approval button
    (Teams Adaptive Card, Slack Block Kit button, etc.).

    Flow:
        1. Fetch the pending proposal by approval_id
        2. If rejected: mark resolved, return confirmation
        3. If approved: mark resolved, execute trade via run_trading_agent
    """
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    try:
        pending = get_pending(req.approval_id)
        if not pending:
            return AgentResponseModel(
                intent="approve",
                text="❌ Approval request not found or has expired.",
            )

        if req.decision == "reject":
            resolve_approval(req.approval_id, "rejected")
            return AgentResponseModel(
                intent="approve",
                text=(
                    f"❌ Trade rejected: "
                    f"{pending['side'].upper()} {pending['qty']} shares of "
                    f"{pending['ticker']}."
                ),
            )

        # Approved — execute the trade
        resolve_approval(req.approval_id, "approved")
        trade_request = (
            f"buy {pending['qty']} shares of {pending['ticker']} — "
            f"human-approved after risk escalation ({pending['reason']})"
        )
        result = run_trading_agent([pending["ticker"]], trade_request)
        return AgentResponseModel(
            intent="approve",
            text=f"✅ Trade approved and executed.\n\n{result}",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── /agent — single platform-agnostic endpoint ────────────────────────────────
# All routing and classification now lives in orchestrator/router.py.
# This endpoint is a thin HTTP adapter: deserialise → AgentMessage → route() → serialise.

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


# ── Watchlist scan endpoints (Phase 5.5) ─────────────────────────────────────

class WatchlistScanRequest(BaseModel):
    user_id:  str
    tickers:  list[str]
    equity:   float = 0.0


def _serialise_monitor_results(results) -> list[dict]:
    """Convert MonitorResult objects to JSON-serialisable dicts."""
    return [
        {
            "ticker":       r.ticker,
            "proposed_qty": r.proposed_qty,
            "signal": {
                "score":     r.signal.score,
                "direction": r.signal.direction,
                "summary":   r.signal.summary,
                "price":     r.signal.price,
                "rsi":       r.signal.rsi,
                "fired":     r.signal.fired,
            },
            "risk": {
                "verdict":      r.risk.verdict.value,
                "adjusted_qty": r.risk.adjusted_qty,
                "reason":       r.risk.reason,
                "narrative":    r.risk.narrative,
            },
        }
        for r in results
    ]


@app.post("/monitor/watchlist/scan")
def watchlist_scan(req: WatchlistScanRequest):
    """
    On-demand scan for one user's watchlist — bypasses market-hours check.

    Useful for:
      - Testing outside market hours (e.g. evenings, weekends)
      - Debugging signal scoring for a specific ticker list
      - CI/CD smoke tests against the live API

    Calls scan_user_watchlist() directly; alerts are NOT queued (use
    POST /monitor/scan/run for a full scan with queuing).
    """
    try:
        from orchestrator.watchlist_monitor import scan_user_watchlist
        alerts = scan_user_watchlist(req.user_id, req.tickers, req.equity)
        return {
            "user_id":      req.user_id,
            "alerts_count": len(alerts),
            "alerts":       _serialise_monitor_results(alerts),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/monitor/scan/run")
def scan_run_now():
    """
    Trigger a full watchlist scan across all users immediately.

    Bypasses the market-hours check so engineers can force a scan at any time.
    Alerts ARE queued to alert_queue (Teams bot will push them on next poll).

    Returns a summary: how many alerts were queued per user.
    """
    try:
        results  = _scheduler.run_now()
        summary  = {uid: len(alerts) for uid, alerts in results.items()}
        total    = sum(summary.values())
        return {
            "status":        "ok",
            "users_with_alerts": len(summary),
            "total_alerts":  total,
            "per_user":      summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/monitor/scan/status")
def scan_status():
    """
    Return scheduler state and next scheduled run time.
    Useful for confirming the cron is alive after a deployment.
    """
    from orchestrator.scheduler import _SCHEDULER, is_market_hours, SCAN_INTERVAL_MINUTES
    from datetime import datetime
    from zoneinfo import ZoneInfo

    running   = _SCHEDULER is not None and _SCHEDULER.running
    next_run  = None
    if running:
        job = _SCHEDULER.get_job("watchlist_scan")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "scheduler_running":    running,
        "market_hours_now":     is_market_hours(),
        "scan_interval_minutes": SCAN_INTERVAL_MINUTES,
        "next_run_time":        next_run,
        "current_time_et":      datetime.now(ZoneInfo("America/New_York")).isoformat(),
    }


# ── Alert endpoints (Phase 5.4 — proactive Teams push) ───────────────────────

class ConversationRefRequest(BaseModel):
    user_id:          str
    conversation_ref: dict   # full Teams ConversationReference JSON


class AlertDeliveredRequest(BaseModel):
    pass  # body unused — alert_id comes from the path


class QueueAlertRequest(BaseModel):
    """Internal endpoint for manual alert injection during testing."""
    user_id:      str
    ticker:       str
    score:        float
    direction:    str
    summary:      str
    price:        float
    rsi:          float
    verdict:      str
    adjusted_qty: int
    reason:       str
    narrative:    str
    proposed_qty: int


@app.post("/alerts/store-ref", status_code=204)
def store_ref(req: ConversationRefRequest):
    """
    Upsert a Teams ConversationReference for a user.

    Called by the bot on every incoming activity so we always have a fresh
    reference needed for proactive push via CloudAdapter.continueConversation().
    """
    try:
        store_conversation_ref(req.user_id, req.conversation_ref)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/alerts/pending")
def pending_alerts(user_id: str | None = None):
    """
    Return all undelivered alerts, optionally filtered to one user.

    Each alert includes the user's stored ConversationReference
    (null if the user has never messaged the bot — bot skips delivery).

    Polled by the Teams bot on a 30-second interval.
    """
    try:
        return {"alerts": get_pending_alerts(user_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/alerts/delivered/{alert_id}", status_code=204)
def alert_delivered(alert_id: int):
    """
    Mark an alert as delivered after the bot successfully pushes it to Teams.
    Prevents duplicate delivery on the next poll cycle.
    """
    try:
        mark_alert_delivered(alert_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/alerts/queue")
def queue_alert_endpoint(req: QueueAlertRequest):
    """
    Manually inject an alert into the queue.

    Used for testing proactive push without running the full watchlist scanner.
    In production, alerts are queued automatically by the cron job.
    """
    try:
        # Build lightweight stand-in objects that match MonitorResult field access
        class _Signal:
            ticker    = req.ticker
            score     = req.score
            direction = req.direction
            summary   = req.summary
            price     = req.price
            rsi       = req.rsi
            fired     = True

        class _Verdict:
            value = req.verdict

        class _Risk:
            verdict      = _Verdict()
            adjusted_qty = req.adjusted_qty
            reason       = req.reason
            narrative    = req.narrative

        class _Result:
            ticker       = req.ticker
            user_id      = req.user_id
            signal       = _Signal()
            risk         = _Risk()
            proposed_qty = req.proposed_qty

        alert_id = _queue_alert(req.user_id, _Result())
        return {"alert_id": alert_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Earnings endpoints (Phase 6) ──────────────────────────────────────────────

class EarningsScanRequest(BaseModel):
    user_id:    str
    tickers:    list[str]
    days_ahead: int = 7


def _serialise_earnings_alerts(alerts) -> list[dict]:
    """Convert EarningsAlert objects to JSON-serialisable dicts."""
    return [
        {
            "ticker":           a.ticker,
            "earnings_date":    a.earnings_date,
            "days_until":       a.days_until,
            "eps_estimate":     a.eps_estimate,
            "eps_low":          a.eps_low,
            "eps_high":         a.eps_high,
            "revenue_estimate": a.revenue_estimate,
            "analyst_rating":   a.analyst_rating,
            "analyst_target":   a.analyst_target,
            "thesis":           a.thesis,
            "summary":          a.summary,
            "sentiment":        a.sentiment,
        }
        for a in alerts
    ]


@app.get("/earnings/upcoming")
def earnings_upcoming(user_id: str, days_ahead: int = 7):
    """
    Return upcoming earnings events for a user's active watchlist tickers.

    Useful for a dashboard view — doesn't queue alerts, just returns data.
    """
    try:
        from stock_agent.watchlist import get_watchlist
        from orchestrator.earnings_agent import scan_user_earnings
        tickers = get_watchlist(user_id)
        if not tickers:
            return {"user_id": user_id, "alerts": []}
        alerts = scan_user_earnings(user_id, tickers, days_ahead)
        return {"user_id": user_id, "alerts_count": len(alerts), "alerts": _serialise_earnings_alerts(alerts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/earnings/scan")
def earnings_scan(req: EarningsScanRequest):
    """
    On-demand earnings scan for a specific user + ticker list.

    Does NOT queue alerts — returns results directly.
    Use POST /earnings/scan/run for a full queued scan.
    """
    try:
        from orchestrator.earnings_agent import scan_user_earnings
        alerts = scan_user_earnings(req.user_id, req.tickers, req.days_ahead)
        return {
            "user_id":      req.user_id,
            "alerts_count": len(alerts),
            "alerts":       _serialise_earnings_alerts(alerts),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/earnings/scan/run")
def earnings_scan_run_now():
    """
    Trigger a full earnings scan across all watchlist users immediately.
    Alerts ARE queued to alert_queue (Teams bot pushes on next poll cycle).
    """
    try:
        from orchestrator.earnings_agent import run_full_earnings_scan
        results = run_full_earnings_scan(queue_alerts=True)
        summary = {uid: len(alerts) for uid, alerts in results.items()}
        return {
            "status":              "ok",
            "users_with_alerts":   len(summary),
            "total_alerts":        sum(summary.values()),
            "per_user":            summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Portfolio Optimizer endpoints (Phase 8) ───────────────────────────────────

class OptimizeRequest(BaseModel):
    user_id: str


class RebalanceExecuteRequest(BaseModel):
    user_id: str


def _serialise_trade_proposals(trades) -> list[dict]:
    """Convert TradeProposal objects to JSON-serialisable dicts."""
    return [
        {
            "ticker":        t.ticker,
            "side":          t.side,
            "proposed_qty":  t.proposed_qty,
            "adjusted_qty":  t.adjusted_qty,
            "current_price": t.current_price,
            "trade_value":   t.trade_value,
            "current_pct":   t.current_pct,
            "target_pct":    t.target_pct,
            "drift_pct":     t.drift_pct,
            "risk_verdict":  t.risk_verdict,
            "risk_note":     t.risk_note,
        }
        for t in trades
    ]


@app.post("/portfolio/optimize")
def portfolio_optimize(req: OptimizeRequest):
    """
    Build a portfolio rebalancing plan against the target allocation config.

    Generator → critic → refinement → Sonnet rationale → stored in DB
    and queued as a rebalance alert for Teams approval.

    Returns the plan summary including plan_id (needed to approve/reject).
    Never executes trades — execution requires explicit approval.
    """
    try:
        from orchestrator.portfolio_optimizer import build_rebalance_plan, format_plan_markdown
        plan = build_rebalance_plan(req.user_id)
        return {
            "plan_id":          plan.plan_id,
            "user_id":          plan.user_id,
            "equity":           plan.equity,
            "cash":             plan.cash,
            "total_sell_value": plan.total_sell_value,
            "total_buy_value":  plan.total_buy_value,
            "net_cash_change":  plan.net_cash_change,
            "rationale":        plan.rationale,
            "trades":           _serialise_trade_proposals(plan.trades),
            "blocked":          _serialise_trade_proposals(plan.blocked),
            "markdown":         format_plan_markdown(plan),
            "created_at":       plan.created_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolio/rebalance/{plan_id}/execute")
def portfolio_rebalance_execute(plan_id: str, req: RebalanceExecuteRequest):
    """
    Execute an approved rebalancing plan.

    Fetches the plan from DB, places sells first (to free cash), then buys.
    Only callable after the user has approved the plan via the Teams card.

    Returns a summary of executed and failed trades.
    """
    try:
        from orchestrator.portfolio_optimizer import execute_rebalance_plan
        result = execute_rebalance_plan(plan_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolio/rebalance/{plan_id}/reject", status_code=204)
def portfolio_rebalance_reject(plan_id: str):
    """
    Reject (cancel) a pending rebalancing plan.

    Marks the plan as executed (with no trades) so it cannot be executed later.
    Called by the Teams bot when the user clicks the Reject button on the card.
    """
    try:
        from orchestrator.alert_manager import mark_rebalance_executed
        mark_rebalance_executed(plan_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/portfolio/allocation")
def portfolio_allocation():
    """
    Return the current target allocation config from config/target_allocation.yaml.

    Useful for displaying the allocation in Teams before running Optimize.
    """
    try:
        from orchestrator.portfolio_optimizer import load_target_allocation
        cfg = load_target_allocation()
        allocs = cfg.get("allocations", {})
        total  = sum(allocs.values())
        return {
            "allocations": {
                k: {"target_pct": v, "target_pct_display": f"{v*100:.0f}%"}
                for k, v in allocs.items()
            },
            "total_allocated":    round(total, 4),
            "cash_remainder":     round(1.0 - total, 4),
            "settings":           cfg.get("settings", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Trade Journal endpoints (Phase 9) ────────────────────────────────────────

@app.post("/journal/sync")
def journal_sync():
    """
    Trigger an immediate sync of closed Alpaca positions to the trade journal.

    Useful for:
      - Testing outside the cron schedule
      - Manually closing out stale open trades after paper account resets
      - CI smoke tests to confirm Alpaca connectivity and DB writes

    Returns a summary of how many trades were closed this run.
    """
    try:
        from orchestrator.journal_agent import run_journal_sync
        result = run_journal_sync()
        return {
            "status":  "ok",
            "synced":  result["synced"],
            "skipped": result["skipped"],
            "errors":  result["errors"],
            "details": result["details"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/journal/digest")
def journal_digest():
    """
    Build and return the weekly reflection digest on demand.

    Does NOT queue a Teams alert — returns the digest directly.
    Use POST /journal/reflect/run for a full run that also queues the card.

    Useful for dashboards or testing the reflect → digest pipeline.
    """
    try:
        from orchestrator.journal_agent import build_weekly_digest
        digest = build_weekly_digest()
        return digest
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/journal/reflect/run")
def journal_reflect_run():
    """
    Trigger a full weekly reflection: sync closed trades + reflect + queue Teams card.

    Mirrors what the Monday 08:00 cron does. Useful for forcing a reflection
    outside the weekly schedule (e.g. after a batch of test trades).
    """
    try:
        from orchestrator.journal_agent import run_weekly_reflection
        digest = run_weekly_reflection()
        return {
            "status":          digest.get("status"),
            "week_of":         digest.get("week_of", ""),
            "trades_analyzed": digest.get("trades_analyzed", 0),
            "lessons_count":   len(digest.get("lessons", [])),
            "summary":         digest.get("summary", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── IPO Watch endpoints ───────────────────────────────────────────────────────

@app.post("/ipo-watch/run")
def ipo_watch_run(user_id: str = "ipo-watch"):
    """
    Trigger an immediate IPO Watch scan for all active profiles.

    Mirrors what the every-4-hours cron does. Useful for testing outside
    the scheduled window or forcing a refresh after adding a new profile.

    Returns per-profile signal results and alert dispatch summaries.
    """
    _ipo_root = str(_AGENTS_ROOT / "ipo-watch")
    if _ipo_root not in sys.path:
        sys.path.insert(0, _ipo_root)

    try:
        from scheduler_integration import run_ipo_watch_scan  # type: ignore
        result = run_ipo_watch_scan(user_id=user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ipo-watch/status")
def ipo_watch_status():
    """
    Return the latest persisted signal state for all active IPO Watch profiles.

    No API calls — reads from ipo_watch_state SQLite table only.
    Safe to call frequently from a dashboard.
    """
    _ipo_root = str(_AGENTS_ROOT / "ipo-watch")
    if _ipo_root not in sys.path:
        sys.path.insert(0, _ipo_root)

    try:
        from scheduler_integration import get_current_status  # type: ignore
        rows = get_current_status()
        return {"profiles": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ipo-watch/profiles")
def ipo_watch_profiles():
    """
    List all IPO Watch profiles (active and inactive) with summary metadata.
    """
    _ipo_root = str(_AGENTS_ROOT / "ipo-watch")
    if _ipo_root not in sys.path:
        sys.path.insert(0, _ipo_root)

    try:
        from profiles import list_profiles  # type: ignore
        return {"profiles": list_profiles()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stock_agent.api:app", host="0.0.0.0", port=8000, reload=True)
