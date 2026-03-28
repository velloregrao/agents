"""
orchestrator/scheduler.py

APScheduler-backed watchlist cron (Phase 5 Step 5.5).

Runs run_full_scan() every 15 minutes, but only during US equity market
hours (Mon–Fri 09:30–16:00 ET). Outside that window the job is a no-op so
we never burn API quota or Alpaca rate-limits on closed-market data.

The scheduler runs in a background thread (BackgroundScheduler), which is
compatible with the Uvicorn/FastAPI main thread that already owns the asyncio
event loop. run_full_scan() itself uses asyncio.run() internally, which is
safe to call from a non-async thread.

Public API:
    start()    — called at FastAPI startup
    stop()     — called at FastAPI shutdown
    run_now()  — immediate scan regardless of market hours (POST /monitor/scan/run)
    is_market_hours() -> bool — exported for tests and the /monitor/scan/status endpoint
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

# ── Config ────────────────────────────────────────────────────────────────────

_ET                    = ZoneInfo("America/New_York")
SCAN_INTERVAL_MINUTES  = 15
_MARKET_OPEN_H, _MARKET_OPEN_M   = 9, 30
_MARKET_CLOSE_H, _MARKET_CLOSE_M = 16, 0

# Module-level singleton
_SCHEDULER: BackgroundScheduler | None = None


# ── Market-hours guard ────────────────────────────────────────────────────────

def is_market_hours(now: datetime | None = None) -> bool:
    """
    Return True if *now* (default: current time) falls within US equity
    market hours: Mon–Fri 09:30–16:00 America/New_York.

    Accepts an optional datetime for testing without monkey-patching.
    """
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)

    if now.weekday() >= 5:                         # Saturday=5, Sunday=6
        return False

    market_open  = now.replace(
        hour=_MARKET_OPEN_H,  minute=_MARKET_OPEN_M,  second=0, microsecond=0
    )
    market_close = now.replace(
        hour=_MARKET_CLOSE_H, minute=_MARKET_CLOSE_M, second=0, microsecond=0
    )
    return market_open <= now < market_close


# ── Job function ──────────────────────────────────────────────────────────────

def _scan_job() -> None:
    """
    APScheduler job — fires every SCAN_INTERVAL_MINUTES but is a no-op
    outside market hours so the scheduler can stay running 24/7 without
    needing to be started/stopped around the market session.
    """
    if not is_market_hours():
        return

    now_str = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    print(f"[scheduler] scan started at {now_str}", flush=True)

    try:
        from orchestrator.watchlist_monitor import run_full_scan
        results    = run_full_scan(queue_alerts=True)
        total      = sum(len(v) for v in results.values())
        user_count = len(results)
        print(
            f"[scheduler] scan complete — "
            f"{total} alert(s) queued across {user_count} user(s)",
            flush=True,
        )
    except Exception as exc:
        print(f"[scheduler] scan error: {exc}", file=sys.stderr, flush=True)


# ── Earnings job ──────────────────────────────────────────────────────────────

def _earnings_job() -> None:
    """
    Daily earnings intelligence scan — runs at 08:00 ET Mon–Fri.

    Fires before market open so users have thesis cards waiting in Teams
    before trading begins. No market-hours guard needed — it's a cron, not
    an interval.
    """
    now_str = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    print(f"[scheduler] earnings scan started at {now_str}", flush=True)

    try:
        from orchestrator.earnings_agent import run_full_earnings_scan
        results    = run_full_earnings_scan(queue_alerts=True)
        total      = sum(len(v) for v in results.values())
        user_count = len(results)
        print(
            f"[scheduler] earnings scan complete — "
            f"{total} alert(s) queued across {user_count} user(s)",
            flush=True,
        )
    except Exception as exc:
        print(f"[scheduler] earnings scan error: {exc}", file=sys.stderr, flush=True)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def start() -> None:
    """
    Start the background scheduler.  Safe to call multiple times — subsequent
    calls are no-ops if the scheduler is already running.
    """
    global _SCHEDULER

    if _SCHEDULER is not None and _SCHEDULER.running:
        return

    _SCHEDULER = BackgroundScheduler(timezone=str(_ET))
    _SCHEDULER.add_job(
        _scan_job,
        trigger=IntervalTrigger(minutes=SCAN_INTERVAL_MINUTES, timezone=_ET),
        id="watchlist_scan",
        name="Watchlist Monitor Scan",
        replace_existing=True,
        max_instances=1,        # never overlap — long scans on big watchlists
    )
    _SCHEDULER.add_job(
        _earnings_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=_ET),
        id="earnings_scan",
        name="Earnings Intelligence Scan",
        replace_existing=True,
        max_instances=1,
    )
    _SCHEDULER.start()
    print(
        f"[scheduler] started — scan every {SCAN_INTERVAL_MINUTES} min "
        f"(market hours only: Mon–Fri {_MARKET_OPEN_H:02d}:{_MARKET_OPEN_M:02d}–"
        f"{_MARKET_CLOSE_H:02d}:{_MARKET_CLOSE_M:02d} ET)",
        flush=True,
    )


def stop() -> None:
    """Shut down the scheduler gracefully at FastAPI shutdown."""
    global _SCHEDULER
    if _SCHEDULER is not None:
        _SCHEDULER.shutdown(wait=False)
        _SCHEDULER = None
        print("[scheduler] stopped", flush=True)


def run_now() -> dict[str, list]:
    """
    Trigger an immediate full scan, bypassing the market-hours check.

    Called by POST /monitor/scan/run so engineers can force a scan for
    testing outside market hours without touching the scheduler state.

    Returns the raw results dict {user_id: [MonitorResult]} so the API
    can serialise and return it to the caller.
    """
    from orchestrator.watchlist_monitor import run_full_scan
    print("[scheduler] manual run_now() triggered", flush=True)
    return run_full_scan(queue_alerts=True)
