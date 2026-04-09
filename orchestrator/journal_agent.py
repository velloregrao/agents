"""
orchestrator/journal_agent.py

Trade journal agent (Phase 9).

Pattern: sequential pipeline + coordinator-dispatcher

Responsibilities:
  1. sync_closed_trades()    — diff Alpaca live positions vs open DB trades;
                               close any DB-open trade whose ticker is no longer held
  2. build_weekly_digest()   — run reflect() and format a Teams-ready summary
  3. run_journal_sync()      — cron entry point (sync only, no reflect)
  4. run_weekly_reflection() — cron entry point (sync + reflect + queue alert)

The sync runs every 15 min alongside the watchlist scan.
The weekly reflection runs every Monday at 08:00 ET.

Public API:
    sync_closed_trades() -> dict
    build_weekly_digest() -> dict
    run_journal_sync() -> dict
    run_weekly_reflection() -> dict
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from stock_agent.alpaca_tools import get_positions
from stock_agent.memory import get_open_trades, close_trade, get_performance_summary
from stock_agent.reflection import reflect
from stock_agent.tools import get_current_price
from stock_agent.watchlist import get_all_active_watchlists
from orchestrator.alert_manager import queue_journal_alert


# ── Sync: close resolved positions ───────────────────────────────────────────

def sync_closed_trades() -> dict:
    """
    Diff Alpaca live positions against open DB trades and close any gap.

    A DB trade is considered closed when its ticker is no longer present
    in the current Alpaca positions snapshot. Exit price is taken from the
    current market price (best available estimate at sync time).

    Returns:
        {
            "synced":  int   — number of trades closed this run,
            "skipped": int   — open trades with no price data (left open),
            "errors":  int   — close_trade() failures,
            "details": list  — one entry per closed trade,
        }
    """
    # ── Fetch live Alpaca positions ────────────────────────────────────────
    pos_data  = get_positions()
    if pos_data.get("error"):
        print(f"[journal] get_positions error: {pos_data['error']}", file=sys.stderr)
        return {"synced": 0, "skipped": 0, "errors": 0, "details": []}

    held_tickers = {
        p["ticker"].upper()
        for p in pos_data.get("positions", [])
    }

    # ── Fetch open DB trades ───────────────────────────────────────────────
    open_data   = get_open_trades()
    open_trades = open_data.get("open_trades", [])

    if not open_trades:
        return {"synced": 0, "skipped": 0, "errors": 0, "details": []}

    synced  = 0
    skipped = 0
    errors  = 0
    details = []

    for trade in open_trades:
        ticker   = trade["ticker"].upper()
        order_id = trade["order_id"]

        # Still held — nothing to do
        if ticker in held_tickers:
            continue

        # Ticker gone from Alpaca — position was closed; fetch exit price
        try:
            price_data  = get_current_price(ticker)
            exit_price  = float(price_data.get("current_price") or 0)
        except Exception as exc:
            print(f"[journal] price fetch failed for {ticker}: {exc}", file=sys.stderr)
            exit_price = 0.0

        if exit_price <= 0:
            skipped += 1
            details.append({"ticker": ticker, "order_id": order_id, "status": "skipped_no_price"})
            continue

        result = close_trade(
            order_id=order_id,
            exit_price=exit_price,
            outcome_notes="Auto-closed by journal sync — position no longer held in Alpaca",
        )

        if result.get("error"):
            errors += 1
            details.append({
                "ticker":   ticker,
                "order_id": order_id,
                "status":   "error",
                "error":    result["error"],
            })
        else:
            synced += 1
            details.append({
                "ticker":     ticker,
                "order_id":   order_id,
                "status":     "closed",
                "exit_price": exit_price,
                "pnl":        result.get("pnl"),
                "pnl_pct":    result.get("pnl_pct"),
                "hold_days":  result.get("hold_days"),
            })
            print(
                f"[journal] auto-closed {ticker} @ ${exit_price:.2f} | "
                f"P&L: {result.get('pnl_pct', 0):+.1f}%",
                flush=True,
            )
            # ── Phase 2: embed closed trade into vector store ──────────────
            try:
                from orchestrator.vector_store import embed_closed_trade
                embed_closed_trade({
                    **trade,
                    "exit_price": exit_price,
                    "pnl":        result.get("pnl"),
                    "pnl_pct":    result.get("pnl_pct"),
                    "hold_days":  result.get("hold_days"),
                })
                print(f"[journal] embedded {ticker} trade into vector store", flush=True)
            except Exception as vec_exc:
                # Non-fatal — journal sync succeeds even if vector embed fails
                print(f"[journal] vector embed failed for {ticker}: {vec_exc}", file=sys.stderr)

    return {
        "synced":  synced,
        "skipped": skipped,
        "errors":  errors,
        "details": details,
    }


# ── Weekly digest ─────────────────────────────────────────────────────────────

def build_weekly_digest() -> dict:
    """
    Run reflect() and package the result as a Teams-ready digest payload.

    Returns a dict that can be passed directly to queue_journal_alert().
    Status is 'completed', 'skipped', or 'error' (mirrors reflect() status).
    """
    result = reflect(min_trades=3)

    if result.get("status") != "completed":
        return {
            "status":          result.get("status", "skipped"),
            "reason":          result.get("reason", ""),
            "trades_analyzed": result.get("trades_available", 0),
            "lessons":         [],
            "summary":         "",
            "performance":     get_performance_summary(),
        }

    return {
        "status":          "completed",
        "reason":          "",
        "trades_analyzed": result.get("trades_analyzed", 0),
        "lessons":         result.get("lessons", []),
        "summary":         result.get("summary", ""),
        "performance":     get_performance_summary(),
        "week_of":         datetime.now(timezone.utc).strftime("%b %d, %Y"),
    }


# ── Cron entry points ─────────────────────────────────────────────────────────

def run_journal_sync() -> dict:
    """
    Lightweight cron entry point — sync closed trades only, no reflection.
    Runs every 15 min alongside the watchlist scanner (market hours only).
    """
    result = sync_closed_trades()
    if result["synced"] > 0:
        print(
            f"[journal] sync complete — "
            f"{result['synced']} closed, {result['skipped']} skipped, "
            f"{result['errors']} error(s)",
            flush=True,
        )
    return result


def run_weekly_reflection() -> dict:
    """
    Full weekly cron entry point — sync, reflect, queue Teams digest card.
    Runs every Monday at 08:00 ET.

    Returns the digest dict (useful for POST /journal/digest).
    """
    # Always sync first so reflect() sees the freshest closed-trade data
    sync_result = sync_closed_trades()
    print(
        f"[journal] weekly sync — {sync_result['synced']} trade(s) closed before reflect",
        flush=True,
    )

    digest = build_weekly_digest()

    if digest["status"] == "completed":
        try:
            user_ids = list(get_all_active_watchlists().keys())
            for user_id in user_ids:
                queue_journal_alert(user_id, digest)
            print(
                f"[journal] weekly digest queued for "
                f"{len(user_ids)} user(s) — "
                f"{len(digest['lessons'])} lesson(s)",
                flush=True,
            )
        except Exception as exc:
            print(f"[journal] queue_journal_alert failed: {exc}", file=sys.stderr)

    return digest


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Journal Sync ===")
    sync = sync_closed_trades()
    print(f"synced={sync['synced']}  skipped={sync['skipped']}  errors={sync['errors']}")
    for d in sync["details"]:
        print(f"  {d}")

    print("\n=== Weekly Digest ===")
    digest = build_weekly_digest()
    print(f"status={digest['status']}")
    if digest["status"] == "completed":
        print(f"trades_analyzed={digest['trades_analyzed']}")
        print(f"lessons ({len(digest['lessons'])}):")
        for i, l in enumerate(digest["lessons"], 1):
            print(f"  {i}. {l}")
        print(f"summary: {digest['summary']}")
