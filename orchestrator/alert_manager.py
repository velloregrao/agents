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
    """Create both tables if they don't exist."""
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
                delivered_at TEXT
            )
        """)


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
