"""
orchestrator/alert_manager.py

SQLite-backed alert queue + conversation-reference store for proactive
Teams push (Phase 5 Step 5.4).

Two tables (same DB as trades / watchlist):
    conversation_refs  — per-user Teams ConversationReference JSON needed
                         by CloudAdapter.continueConversation() to push messages
                         without an incoming activity.
    alert_queue        — pending signal alerts queued by the watchlist scanner,
                         polled and delivered by the Teams bot.

Public API:
    initialize_db()
    store_conversation_ref(user_id, ref_json)
    get_conversation_ref(user_id) -> dict | None
    queue_alert(user_id, monitor_result) -> int          — returns alert_id
    get_pending_alerts(user_id=None) -> list[dict]       — includes conv ref
    mark_alert_delivered(alert_id)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── DB path ────────────────────────────────────────────────────────────────────

_DEFAULT_DB = str(
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    / "Projects" / "data" / "trading_memory.db"
)


def _conn() -> sqlite3.Connection:
    db_path = os.getenv("DB_PATH", _DEFAULT_DB)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


# ── Schema ─────────────────────────────────────────────────────────────────────

def initialize_db() -> None:
    """Create both tables if they don't exist, and migrate existing schemas."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversation_refs (
                user_id     TEXT PRIMARY KEY,
                ref_json    TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS alert_queue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                ticker       TEXT    NOT NULL,
                signal_json  TEXT    NOT NULL,
                risk_json    TEXT    NOT NULL,
                proposed_qty INTEGER NOT NULL,
                created_at   TEXT    NOT NULL,
                delivered_at TEXT,
                alert_type   TEXT    NOT NULL DEFAULT 'signal'
            )
        """)
        # Migration: add alert_type to existing tables that predate Phase 6
        try:
            c.execute(
                "ALTER TABLE alert_queue ADD COLUMN alert_type TEXT NOT NULL DEFAULT 'signal'"
            )
        except Exception:
            pass  # column already exists — safe to ignore


# ── Conversation references ────────────────────────────────────────────────────

def store_conversation_ref(user_id: str, ref_json: dict) -> None:
    """
    Upsert the Teams ConversationReference for a user.

    Called by the bot on every incoming message so we always have a fresh
    reference. Stale references (e.g. after a bot reinstall) are overwritten.
    """
    initialize_db()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO conversation_refs (user_id, ref_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id)
            DO UPDATE SET ref_json = excluded.ref_json,
                          updated_at = excluded.updated_at
            """,
            (user_id, json.dumps(ref_json), now),
        )


def get_conversation_ref(user_id: str) -> dict | None:
    """Return the stored ConversationReference for a user, or None."""
    initialize_db()
    with _conn() as c:
        row = c.execute(
            "SELECT ref_json FROM conversation_refs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return json.loads(row["ref_json"]) if row else None


# ── Alert queue ────────────────────────────────────────────────────────────────

def queue_alert(user_id: str, monitor_result) -> int:
    """
    Persist one MonitorResult to the alert_queue.

    Serialises signal and risk fields to JSON so the alert is self-contained
    and can be polled without importing orchestrator types.

    Returns the new alert_id (used to mark the alert as delivered).
    """
    initialize_db()
    now = datetime.now(timezone.utc).isoformat()

    signal_json = json.dumps({
        "ticker":    monitor_result.signal.ticker,
        "score":     monitor_result.signal.score,
        "direction": monitor_result.signal.direction,
        "summary":   monitor_result.signal.summary,
        "price":     monitor_result.signal.price,
        "rsi":       monitor_result.signal.rsi,
        "fired":     monitor_result.signal.fired,
    })
    risk_json = json.dumps({
        "verdict":      monitor_result.risk.verdict.value,
        "adjusted_qty": monitor_result.risk.adjusted_qty,
        "reason":       monitor_result.risk.reason,
        "narrative":    monitor_result.risk.narrative,
    })

    with _conn() as c:
        cursor = c.execute(
            """
            INSERT INTO alert_queue
              (user_id, ticker, signal_json, risk_json, proposed_qty, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                monitor_result.ticker,
                signal_json,
                risk_json,
                monitor_result.proposed_qty,
                now,
            ),
        )
        return cursor.lastrowid


def queue_earnings_alert(user_id: str, earnings_alert) -> int:
    """
    Persist one EarningsAlert to the alert_queue with alert_type='earnings'.

    The full earnings payload is stored in signal_json so the Teams bot can
    build the card without importing EarningsAlert. risk_json is unused for
    earnings alerts (set to '{}').

    Returns the new alert_id.
    """
    initialize_db()
    now = datetime.now(timezone.utc).isoformat()

    payload_json = json.dumps({
        "ticker":           earnings_alert.ticker,
        "earnings_date":    earnings_alert.earnings_date,
        "days_until":       earnings_alert.days_until,
        "eps_estimate":     earnings_alert.eps_estimate,
        "eps_low":          earnings_alert.eps_low,
        "eps_high":         earnings_alert.eps_high,
        "revenue_estimate": earnings_alert.revenue_estimate,
        "analyst_rating":   earnings_alert.analyst_rating,
        "analyst_target":   earnings_alert.analyst_target,
        "thesis":           earnings_alert.thesis,
        "summary":          earnings_alert.summary,
        "sentiment":        earnings_alert.sentiment,
    })

    with _conn() as c:
        cursor = c.execute(
            """
            INSERT INTO alert_queue
              (user_id, ticker, signal_json, risk_json, proposed_qty, created_at, alert_type)
            VALUES (?, ?, ?, ?, ?, ?, 'earnings')
            """,
            (user_id, earnings_alert.ticker, payload_json, "{}", 0, now),
        )
        return cursor.lastrowid


def get_pending_alerts(user_id: str | None = None) -> list[dict]:
    """
    Return all undelivered alerts, each enriched with the user's
    stored ConversationReference (None if the user has never messaged the bot).

    Filters to one user when user_id is provided; returns all users otherwise.
    """
    initialize_db()
    with _conn() as c:
        if user_id:
            rows = c.execute(
                """
                SELECT a.id, a.user_id, a.ticker,
                       a.signal_json, a.risk_json, a.proposed_qty, a.created_at,
                       r.ref_json
                FROM   alert_queue a
                LEFT JOIN conversation_refs r USING (user_id)
                WHERE  a.delivered_at IS NULL AND a.user_id = ?
                ORDER  BY a.created_at ASC
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT a.id, a.user_id, a.ticker,
                       a.signal_json, a.risk_json, a.proposed_qty, a.created_at,
                       r.ref_json
                FROM   alert_queue a
                LEFT JOIN conversation_refs r USING (user_id)
                WHERE  a.delivered_at IS NULL
                ORDER  BY a.created_at ASC
                """,
            ).fetchall()

    return [
        {
            "id":               row["id"],
            "user_id":          row["user_id"],
            "ticker":           row["ticker"],
            "alert_type":       row["alert_type"] if "alert_type" in row.keys() else "signal",
            "signal":           json.loads(row["signal_json"]),
            "risk":             json.loads(row["risk_json"]),
            "proposed_qty":     row["proposed_qty"],
            "created_at":       row["created_at"],
            "conversation_ref": json.loads(row["ref_json"]) if row["ref_json"] else None,
        }
        for row in rows
    ]


def mark_alert_delivered(alert_id: int) -> None:
    """Mark an alert as delivered (sets delivered_at timestamp)."""
    initialize_db()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE alert_queue SET delivered_at = ? WHERE id = ?",
            (now, alert_id),
        )


# ── Journal alert (Phase 9) ────────────────────────────────────────────────────

def queue_journal_alert(user_id: str, digest: dict) -> int:
    """
    Persist a weekly trading digest to the alert_queue with alert_type='journal'.

    The full digest payload (lessons, summary, performance stats) is stored in
    signal_json so the Teams bot can build the card without importing journal types.
    risk_json is unused for journal alerts (set to '{}').

    Returns the new alert_id.
    """
    initialize_db()
    now = datetime.now(timezone.utc).isoformat()

    payload_json = json.dumps({
        "status":          digest.get("status", "completed"),
        "week_of":         digest.get("week_of", now[:10]),
        "trades_analyzed": digest.get("trades_analyzed", 0),
        "lessons":         digest.get("lessons", []),
        "summary":         digest.get("summary", ""),
        "performance":     digest.get("performance", {}),
    })

    with _conn() as c:
        cursor = c.execute(
            """
            INSERT INTO alert_queue
              (user_id, ticker, signal_json, risk_json, proposed_qty, created_at, alert_type)
            VALUES (?, ?, ?, ?, ?, ?, 'journal')
            """,
            (user_id, "JOURNAL", payload_json, "{}", 0, now),
        )
        return cursor.lastrowid


# ── Rebalance plan store (Phase 8) ─────────────────────────────────────────────

def _ensure_rebalance_table() -> None:
    """Create rebalance_proposals table if it doesn't exist."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS rebalance_proposals (
                plan_id      TEXT PRIMARY KEY,
                user_id      TEXT    NOT NULL,
                plan_json    TEXT    NOT NULL,
                created_at   TEXT    NOT NULL,
                executed_at  TEXT
            )
        """)


def store_rebalance_plan(plan) -> None:
    """
    Persist a RebalancePlan to the rebalance_proposals table.

    plan must be a RebalancePlan dataclass instance. The full plan is
    stored as JSON so execution can be resumed without re-running the
    generator/critic pipeline.
    """
    from dataclasses import asdict
    _ensure_rebalance_table()
    plan_dict = asdict(plan)
    with _conn() as c:
        c.execute(
            """
            INSERT INTO rebalance_proposals (plan_id, user_id, plan_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (plan_id) DO UPDATE
                SET plan_json  = excluded.plan_json,
                    created_at = excluded.created_at
            """,
            (plan.plan_id, plan.user_id, json.dumps(plan_dict), plan.created_at),
        )


def get_rebalance_plan(plan_id: str) -> dict | None:
    """
    Retrieve a stored rebalance plan by plan_id.

    Returns None if the plan is not found or has already been executed.
    Returns the full plan as a dict (same structure as RebalancePlan.__dict__).
    """
    _ensure_rebalance_table()
    with _conn() as c:
        row = c.execute(
            "SELECT plan_json, executed_at FROM rebalance_proposals WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
    if not row:
        return None
    if row["executed_at"]:
        return None  # already executed
    return json.loads(row["plan_json"])


def mark_rebalance_executed(plan_id: str) -> None:
    """Mark a rebalance plan as executed (sets executed_at timestamp)."""
    _ensure_rebalance_table()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE rebalance_proposals SET executed_at = ? WHERE plan_id = ?",
            (now, plan_id),
        )


def queue_rebalance_alert(user_id: str, plan) -> int:
    """
    Persist a rebalance plan alert to the alert_queue with alert_type='rebalance'.

    The plan summary (plan_id, trades, totals, rationale) is stored in
    signal_json so the Teams bot can build the approval card without importing
    RebalancePlan. risk_json is unused for rebalance alerts (set to '{}').

    Returns the new alert_id.
    """
    initialize_db()
    now = datetime.now(timezone.utc).isoformat()

    trades_summary = [
        {
            "ticker":       t.ticker,
            "side":         t.side,
            "adjusted_qty": t.adjusted_qty,
            "trade_value":  t.trade_value,
            "current_pct":  t.current_pct,
            "target_pct":   t.target_pct,
            "drift_pct":    t.drift_pct,
            "risk_verdict": t.risk_verdict,
        }
        for t in plan.trades
    ]
    blocked_summary = [
        {"ticker": b.ticker, "side": b.side, "risk_note": b.risk_note}
        for b in plan.blocked
    ]

    payload_json = json.dumps({
        "plan_id":          plan.plan_id,
        "equity":           plan.equity,
        "cash":             plan.cash,
        "trades":           trades_summary,
        "blocked":          blocked_summary,
        "total_sell_value": plan.total_sell_value,
        "total_buy_value":  plan.total_buy_value,
        "net_cash_change":  plan.net_cash_change,
        "rationale":        plan.rationale,
    })

    with _conn() as c:
        cursor = c.execute(
            """
            INSERT INTO alert_queue
              (user_id, ticker, signal_json, risk_json, proposed_qty, created_at, alert_type)
            VALUES (?, ?, ?, ?, ?, ?, 'rebalance')
            """,
            (user_id, "PORTFOLIO", payload_json, "{}", 0, now),
        )
        return cursor.lastrowid
