"""
orchestrator/approval_manager.py

Platform-agnostic approval state machine.

Stores ESCALATE trade proposals in SQLite, keyed by a UUID approval_id.
Channel adapters (Teams, Slack, etc.) render their platform-native approval
UI and POST the human decision back to POST /agent/approve, which calls
resolve() here and resumes trade execution.

Public API:
    initialize_db()                             — create table if not exists
    store_pending(ticker, side, qty, ...) -> str — persist proposal, return id
    get_pending(approval_id) -> dict | None      — fetch live proposal
    resolve(approval_id, decision) -> bool       — mark approved/rejected
"""

import os
import uuid
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── DB path (same DB as trading memory — one file, multiple tables) ────────────

_AGENTS_ROOT  = Path(__file__).resolve().parent.parent
_DEFAULT_DB   = _AGENTS_ROOT / "stock-analysis-agent" / "trading_memory.db"
DB_PATH       = os.getenv("DB_PATH", str(_DEFAULT_DB))

APPROVAL_TTL_HOURS = 24   # proposals expire after 24 hours


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def initialize_db() -> None:
    """Create the pending_approvals table if it doesn't exist."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                approval_id  TEXT PRIMARY KEY,
                ticker       TEXT NOT NULL,
                side         TEXT NOT NULL,
                qty          INTEGER NOT NULL,
                reason       TEXT,
                narrative    TEXT,
                user_id      TEXT,
                created_at   TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending'
            )
        """)


# ── Public API ────────────────────────────────────────────────────────────────

def store_pending(
    ticker:    str,
    side:      str,
    qty:       int,
    reason:    str,
    narrative: str,
    user_id:   str,
) -> str:
    """
    Persist an ESCALATE proposal and return a UUID approval_id.

    The approval_id is embedded in the channel adapter's approval UI
    (e.g. Teams Adaptive Card button data, Slack block action value)
    so the POST /agent/approve endpoint knows which proposal to act on.
    """
    initialize_db()
    approval_id = str(uuid.uuid4())
    now         = datetime.now(timezone.utc)
    expires     = now + timedelta(hours=APPROVAL_TTL_HOURS)

    with _conn() as c:
        c.execute(
            """
            INSERT INTO pending_approvals
                (approval_id, ticker, side, qty, reason, narrative,
                 user_id, created_at, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (approval_id, ticker.upper(), side.lower(), qty,
             reason, narrative, user_id,
             now.isoformat(), expires.isoformat()),
        )
    return approval_id


def get_pending(approval_id: str) -> dict | None:
    """
    Return the pending proposal if it exists and has not expired or been resolved.
    Returns None if the proposal is missing, expired, or already actioned.
    """
    initialize_db()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pending_approvals WHERE approval_id = ? AND status = 'pending'",
            (approval_id,),
        ).fetchone()

    if not row:
        return None

    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if now > expires:
        # Auto-expire
        with _conn() as c:
            c.execute(
                "UPDATE pending_approvals SET status = 'expired' WHERE approval_id = ?",
                (approval_id,),
            )
        return None

    return dict(row)


def resolve(approval_id: str, decision: str) -> bool:
    """
    Mark a pending proposal as 'approved' or 'rejected'.
    Returns True if the proposal was found and updated, False otherwise.
    """
    initialize_db()
    with _conn() as c:
        cursor = c.execute(
            """
            UPDATE pending_approvals
            SET status = ?
            WHERE approval_id = ? AND status = 'pending'
            """,
            (decision, approval_id),
        )
    return cursor.rowcount > 0
