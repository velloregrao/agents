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
from fastapi.responses import JSONResponse
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
from stock_agent.watchlist import initialize_db as initialize_watchlist_db
from stock_agent.agent import run_analysis

# Alert manager lives in the orchestrator package (imported after sys.path is set below)
from stock_agent.trading_agent import run_trading_agent, monitor_positions
from stock_agent.reflection import reflect
from stock_agent.research import run_research_orchestrator

# Make orchestrator/ importable from api.py
# (agents root is 3 levels above this file: src/stock_agent/api.py → agents/)
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
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


# ── /agent/approve — human decision on an ESCALATED trade proposal ────────────

class ApproveRequest(BaseModel):
    approval_id: str
    decision:    str   # "approve" or "reject"
    user_id:     str

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


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stock_agent.api:app", host="0.0.0.0", port=8000, reload=True)
