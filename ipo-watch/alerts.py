"""
IPO Watch — alerts engine.

Dispatches notifications when a tracked IPO candidate crosses a signal
threshold for the first time (WATCH / PREPARE / ACT / RISK).

Channels supported:
  - Teams   — queues an Adaptive Card into the existing alert_queue table;
               the Teams bot polls /alerts/pending and pushes via
               continueConversation().
  - Web     — queues into the same alert_queue table; the web UI's
               Dashboard alert feed picks it up automatically.
  - Log     — always active; writes to stdout so the scheduler's logs capture
               every trigger even if DB is unavailable.

Dedup: uses already_alerted() / record_alert() from stock_agent.memory so
each (ticker, signal, channel) is sent exactly once, even across restarts.

No SMS/Twilio — deferred for a future phase.
"""

import json
import os
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Ensure stock_agent.memory is importable regardless of working directory
_agents_root = Path(__file__).resolve().parent.parent
_src_path = str(_agents_root / "stock-analysis-agent" / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

try:
    from stock_agent.memory import already_alerted, record_alert
    _memory_available = True
except ImportError:
    _memory_available = False

    def already_alerted(ticker, signal, channel):
        return False

    def record_alert(ticker, signal, channel):
        pass


# ---------------------------------------------------------------------------
# Signal copy
# ---------------------------------------------------------------------------

_SIGNAL_EMOJI = {
    "ACT":     "🚀",
    "PREPARE": "📋",
    "WATCH":   "👀",
    "RISK":    "⚠️",
    "HOLD":    "⏸️",
}

_SIGNAL_DESCRIPTION = {
    "ACT":     "IPO appears imminent — consider deploying a position in proxy stocks.",
    "PREPARE": "Strong IPO signals detected — start building a watchlist and sizing plan.",
    "WATCH":   "Early IPO indicators emerging — begin monitoring proxy stock momentum.",
    "RISK":    "IPO thesis weakened — negative signals detected, reassess exposure.",
    "HOLD":    "No new material developments — current monitoring stance unchanged.",
}

_SIGNAL_COLOR = {
    "ACT":     "good",       # green
    "PREPARE": "accent",     # blue
    "WATCH":   "warning",    # yellow
    "RISK":    "attention",  # red
    "HOLD":    "default",
}


# ---------------------------------------------------------------------------
# Adaptive Card builder (Teams)
# ---------------------------------------------------------------------------

def _build_adaptive_card(result: dict) -> dict:
    """
    Build a Teams Adaptive Card payload for one IPO Watch signal result.

    Schema mirrors the existing signal/earnings card patterns in teamsBot.ts.
    """
    ticker       = result["ticker"]
    company_name = result["company_name"]
    score        = result["score"]
    signal       = result["signal"]
    bd           = result.get("breakdown", {})
    checked_at   = result.get("checked_at", datetime.now(timezone.utc).isoformat())

    emoji  = _SIGNAL_EMOJI.get(signal, "📊")
    desc   = _SIGNAL_DESCRIPTION.get(signal, "")
    color  = _SIGNAL_COLOR.get(signal, "default")

    # Proxy changes table rows
    proxy_rows = []
    for t, pct in bd.get("proxy_changes", {}).items():
        if pct is not None:
            arrow = "▲" if pct >= 0 else "▼"
            proxy_rows.append({
                "type": "TableRow",
                "cells": [
                    {"type": "TableCell", "items": [{"type": "TextBlock", "text": t, "weight": "bolder"}]},
                    {"type": "TableCell", "items": [{"type": "TextBlock", "text": f"{arrow} {abs(pct):.2f}%",
                                                     "color": "good" if pct >= 0 else "attention"}]},
                ]
            })

    facts = [
        {"title": "Composite Score", "value": f"{score:.1f} / 100"},
        {"title": "Proxy Momentum",  "value": f"{bd.get('proxy_momentum', 0):.1f} pts"},
        {"title": "News Sentiment",  "value": f"{bd.get('sentiment_label', 'N/A').capitalize()} ({bd.get('news_sentiment', 0):.1f} pts)"},
        {"title": "S-1 Detected",    "value": "Yes ✓" if bd.get("s1_detected") else "No"},
        {"title": "Roadshow",        "value": "Yes ✓" if bd.get("roadshow_detected") else "No"},
        {"title": "Checked",         "value": checked_at[:16].replace("T", " ") + " UTC"},
    ]

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "Container",
                "style": color,
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f"{emoji} IPO Watch — {signal}: {company_name} ({ticker})",
                        "weight": "bolder",
                        "size": "large",
                        "wrap": True,
                    },
                    {
                        "type": "TextBlock",
                        "text": desc,
                        "wrap": True,
                        "spacing": "small",
                    },
                ],
            },
            {
                "type": "FactSet",
                "facts": facts,
                "spacing": "medium",
            },
        ],
    }

    if proxy_rows:
        card["body"].append({
            "type": "TextBlock",
            "text": "Proxy Stock Performance (1 week)",
            "weight": "bolder",
            "spacing": "medium",
        })
        card["body"].append({
            "type": "Table",
            "columns": [{"width": 2}, {"width": 3}],
            "rows": proxy_rows,
        })

    return card


# ---------------------------------------------------------------------------
# SQLite queue helper (reuses same DB as trading_memory)
# ---------------------------------------------------------------------------

def _queue_ipo_alert(user_id: str, result: dict) -> int | None:
    """
    Insert one IPO Watch alert into the alert_queue table with alert_type='ipo_watch'.
    Returns the new row id, or None on failure.
    """
    _default_db = str(
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        / "Projects" / "data" / "trading_memory.db"
    )
    db_path = os.getenv("DB_PATH", _default_db)
    now     = datetime.now(timezone.utc).isoformat()

    payload = json.dumps({
        "ticker":       result["ticker"],
        "company_name": result["company_name"],
        "score":        result["score"],
        "signal":       result["signal"],
        "breakdown":    result.get("breakdown", {}),
        "checked_at":   result.get("checked_at", now),
        "card":         _build_adaptive_card(result),
    })

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            """
            INSERT INTO alert_queue
              (user_id, ticker, signal_json, risk_json, proposed_qty, created_at, alert_type)
            VALUES (?, ?, ?, '{}', 0, ?, 'ipo_watch')
            """,
            (user_id, result["ticker"], payload, now),
        )
        conn.commit()
        alert_id = cursor.lastrowid
        conn.close()
        return alert_id
    except Exception as e:
        print(f"[alerts] DB queue failed for {result['ticker']}: {e}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Public dispatch function
# ---------------------------------------------------------------------------

# Signals that trigger notifications (exclude HOLD — it's a no-op)
_ALERTABLE_SIGNALS = {"ACT", "PREPARE", "WATCH", "RISK"}

# Default user_id written to alert_queue rows; Teams bot and web UI use
# this to fan out to the right conversation / browser session.
_DEFAULT_USER_ID = os.getenv("IPO_WATCH_USER_ID", "ipo-watch")


def dispatch_alert(result: dict, user_id: str = _DEFAULT_USER_ID) -> dict:
    """
    Evaluate a signal result and, if alertable and not already sent,
    dispatch to all configured channels.

    Args:
        result:  dict returned by signals.compute_signal()
        user_id: recipient user_id written to alert_queue (default: "ipo-watch")

    Returns:
        {
          "ticker":     str,
          "signal":     str,
          "score":      float,
          "dispatched": list[str],   # channels that fired
          "skipped":    list[str],   # channels already sent or not alertable
          "alert_id":   int | None,  # DB row id if queued
        }
    """
    ticker  = result["ticker"]
    signal  = result["signal"]
    score   = result["score"]

    dispatched: list[str] = []
    skipped:    list[str] = []
    alert_id = None

    # Always log
    emoji = _SIGNAL_EMOJI.get(signal, "📊")
    print(
        f"[ipo-watch] {emoji} {ticker}  signal={signal}  score={score:.1f}  "
        f"s1={result.get('breakdown', {}).get('s1_detected', False)}  "
        f"roadshow={result.get('breakdown', {}).get('roadshow_detected', False)}",
        flush=True,
    )
    dispatched.append("log")

    if signal not in _ALERTABLE_SIGNALS:
        skipped.extend(["teams", "web"])
        return {"ticker": ticker, "signal": signal, "score": score,
                "dispatched": dispatched, "skipped": skipped, "alert_id": None}

    # Teams + Web — both use the same alert_queue row; the card payload
    # contains the Adaptive Card JSON so teamsBot.ts can render it.
    for channel in ("teams", "web"):
        if already_alerted(ticker, signal, channel):
            skipped.append(channel)
        else:
            if alert_id is None:
                alert_id = _queue_ipo_alert(user_id, result)
            record_alert(ticker, signal, channel)
            dispatched.append(channel)
            print(
                f"[ipo-watch] queued {channel} alert for {ticker} ({signal}), "
                f"alert_id={alert_id}",
                flush=True,
            )

    return {
        "ticker":     ticker,
        "signal":     signal,
        "score":      score,
        "dispatched": dispatched,
        "skipped":    skipped,
        "alert_id":   alert_id,
    }


def dispatch_all(results: list[dict], user_id: str = _DEFAULT_USER_ID) -> list[dict]:
    """
    Dispatch alerts for every result in a run_all_signals() output.
    Returns list of dispatch summaries (one per result).
    """
    return [dispatch_alert(r, user_id=user_id) for r in results]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Synthetic result — does not hit Brave or Claude
    fake_result = {
        "ticker":       "OAII",
        "company_name": "OpenAI",
        "score":        68.0,
        "signal":       "PREPARE",
        "breakdown": {
            "proxy_momentum":  20.0,
            "proxy_changes":   {"MSFT": 5.02, "NVDA": 7.93},
            "news_sentiment":  8.0,
            "sentiment_label": "positive",
            "s1_score":        40.0,
            "s1_detected":     True,
            "roadshow_score":  0.0,
            "roadshow_detected": False,
            "is_negative":     False,
        },
        "snippets_used": 9,
        "checked_at":   datetime.now(timezone.utc).isoformat(),
    }

    print("=== Adaptive Card ===")
    print(json.dumps(_build_adaptive_card(fake_result), indent=2))

    print("\n=== Dispatch (dry run — no DB needed) ===")
    summary = dispatch_alert(fake_result, user_id="test-user")
    print(json.dumps(summary, indent=2))
