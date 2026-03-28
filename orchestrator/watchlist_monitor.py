"""
orchestrator/watchlist_monitor.py

Async parallel fan-out scanner for the watchlist monitor (Phase 5 Step 5.3).

Flow per scan run:
    1. Fetch all active watchlists from SQLite
    2. Deduplicate tickers across all users
    3. Score every unique ticker concurrently via asyncio.gather()
       (score_ticker is sync/blocking → run in ThreadPoolExecutor)
    4. For each user, risk-gate their fired signals (sync)
       - BLOCK    → silent, no alert
       - APPROVED / RESIZE / ESCALATE → include in results
    5. Return {user_id: [MonitorResult]} for alert delivery (Step 5.4)

Public entry points:
    run_full_scan() -> dict[str, list[MonitorResult]]
        Sync — called by APScheduler cron job (Step 5.5).

    scan_user_watchlist(user_id, tickers) -> list[MonitorResult]
        Sync — called by POST /monitor/watchlist/scan for on-demand
        testing outside market hours.

    run_scan_async(watchlists, equity) -> dict[str, list[MonitorResult]]
        Async — awaited directly from async FastAPI route handlers.
"""

import asyncio
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.signal_scorer import score_ticker, SignalScore
from orchestrator.risk_agent import evaluate_proposal, RiskResult, Verdict
from stock_agent.watchlist import get_all_active_watchlists
from stock_agent.alpaca_tools import get_account_balance

# ── Contract ──────────────────────────────────────────────────────────────────

@dataclass
class MonitorResult:
    """
    One alert-worthy signal that cleared both the score threshold and the
    risk gate. Passed to the alert delivery layer (Step 5.4).

    Fields:
        ticker        Stock symbol
        user_id       Canonical user the watchlist belongs to
        signal        Full SignalScore (score, direction, components, summary)
        risk          RiskResult from evaluate_proposal()
                      (APPROVED, RESIZE, or ESCALATE — never BLOCK)
        proposed_qty  Shares computed via 5% position sizing
    """
    ticker:       str
    user_id:      str
    signal:       SignalScore
    risk:         RiskResult
    proposed_qty: int


# ── Internal: async scoring layer ─────────────────────────────────────────────

async def _score_one(ticker: str, executor: ThreadPoolExecutor) -> SignalScore:
    """
    Run the sync score_ticker() in a thread pool so the event loop stays
    free while yfinance is fetching data over the network.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, score_ticker, ticker)


async def _score_all(
    tickers: list[str],
    executor: ThreadPoolExecutor,
) -> dict[str, SignalScore]:
    """
    Score every ticker concurrently.

    return_exceptions=True means a timeout or parse error on one ticker
    never aborts the whole batch — that ticker gets a neutral zero score.
    """
    results = await asyncio.gather(
        *[_score_one(t, executor) for t in tickers],
        return_exceptions=True,
    )

    scored: dict[str, SignalScore] = {}
    for ticker, result in zip(tickers, results):
        if isinstance(result, SignalScore):
            scored[ticker] = result
        else:
            print(
                f"[monitor] scoring error for {ticker}: {result}",
                file=sys.stderr,
            )
            scored[ticker] = SignalScore(
                ticker=ticker, score=0.0, direction="neutral",
                components={}, fired=False,
                summary=f"⚠️ Scoring error for {ticker}: {result}",
                price=0.0, rsi=50.0,
            )

    return scored


# ── Internal: sync risk gate ──────────────────────────────────────────────────

def _risk_gate(
    ticker: str,
    signal: SignalScore,
    equity: float,
    user_id: str,
) -> MonitorResult | None:
    """
    Run evaluate_proposal() for one fired signal.

    Position sizing: same 5% rule as the router — keeps alerts consistent
    with what the trading agent would actually do.

    Returns None for BLOCK verdicts — circuit breaker or size issues should
    not generate user-facing alerts (no spam when markets are rough).
    """
    price        = signal.price if signal.price > 0 else 1.0
    proposed_qty = max(
        math.floor(equity * 0.05 / price) if equity > 0 else 1,
        1,
    )
    side = "buy" if signal.direction == "bullish" else "sell"
    risk = evaluate_proposal(ticker, proposed_qty, side)

    if risk.verdict == Verdict.BLOCK:
        print(
            f"[monitor] {ticker} signal BLOCKED for {user_id}: {risk.reason}",
            file=sys.stderr,
        )
        return None

    return MonitorResult(
        ticker=ticker,
        user_id=user_id,
        signal=signal,
        risk=risk,
        proposed_qty=proposed_qty,
    )


# ── Core async orchestration ──────────────────────────────────────────────────

async def run_scan_async(
    watchlists: dict[str, list[str]],
    equity: float,
) -> dict[str, list[MonitorResult]]:
    """
    Core scan logic — called by run_full_scan() and async FastAPI routes.

    Steps:
        1. Deduplicate tickers across all users so AAPL is only scored once
           even if 10 users watch it
        2. Score all unique tickers in parallel via asyncio.gather()
        3. Risk-gate each user's fired signals (sync, in a loop)
        4. Return only users who have at least one alertable result
    """
    unique_tickers = list({t for tickers in watchlists.values() for t in tickers})
    if not unique_tickers:
        return {}

    n_workers = min(len(unique_tickers), 10)   # cap thread pool at 10
    executor  = ThreadPoolExecutor(max_workers=n_workers)

    try:
        scores = await _score_all(unique_tickers, executor)
    finally:
        executor.shutdown(wait=False)

    results: dict[str, list[MonitorResult]] = {}

    for user_id, tickers in watchlists.items():
        user_alerts: list[MonitorResult] = []

        for ticker in tickers:
            signal = scores.get(ticker)
            if signal is None or not signal.fired:
                continue

            alert = _risk_gate(ticker, signal, equity, user_id)
            if alert is not None:
                user_alerts.append(alert)

        if user_alerts:
            results[user_id] = user_alerts

    return results


# ── Public sync entry points ──────────────────────────────────────────────────

def run_full_scan() -> dict[str, list[MonitorResult]]:
    """
    Full watchlist scan — called by the APScheduler cron job (Step 5.5).

    Fetches all active watchlists and account equity, then delegates to
    run_scan_async() via asyncio.run().

    Safe to call from a background thread (APScheduler's default executor).
    Do NOT call from within an already-running event loop — use
    run_scan_async() directly instead (e.g. from an async FastAPI route).

    Returns {} if there are no active watchlists or no signals fired.
    """
    watchlists = get_all_active_watchlists()
    if not watchlists:
        return {}

    account = get_account_balance()
    equity  = float(account.get("equity", 0)) if not account.get("error") else 0.0

    return asyncio.run(run_scan_async(watchlists, equity))


def scan_user_watchlist(
    user_id: str,
    tickers: list[str],
    equity:  float = 0.0,
) -> list[MonitorResult]:
    """
    On-demand scan for one user's watchlist.

    Used by POST /monitor/watchlist/scan (Step 5.5) and tests.
    If equity is not provided it is fetched from Alpaca.

    Returns [] if no tickers fired or all fired signals were BLOCKED.
    """
    if not tickers:
        return []

    if equity == 0.0:
        account = get_account_balance()
        equity  = float(account.get("equity", 0)) if not account.get("error") else 0.0

    results = asyncio.run(run_scan_async({user_id: tickers}, equity))
    return results.get(user_id, [])


# ── Standalone smoke test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    USER     = "teams:test-user"
    TICKERS  = (sys.argv[1:] or ["AAPL", "NVDA", "AMD", "MSFT", "TSLA"])

    print(f"Scanning {len(TICKERS)} tickers for {USER}…\n")

    alerts = scan_user_watchlist(USER, TICKERS)

    if not alerts:
        print("No signals fired (all below threshold or blocked by risk gate).")
    else:
        for a in alerts:
            print(f"  {a.ticker}  score={a.signal.score:+.2f}  {a.signal.direction}")
            print(f"    {a.signal.summary}")
            print(f"    risk={a.risk.verdict.value}  qty={a.proposed_qty}")
            if a.risk.narrative:
                print(f"    narrative: {a.risk.narrative[:120]}…")
            print()
