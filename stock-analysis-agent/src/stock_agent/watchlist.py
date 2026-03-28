"""
stock_agent/watchlist.py

Per-user watchlist — tickers the user wants monitored proactively.

The cron scanner (Phase 5.3) calls get_all_active_watchlists() to fan
out across every user's tickers each run.

Public API:
    initialize_db()                                 — create table if not exists
    add_to_watchlist(user_id, tickers) -> list[str] — returns tickers added
    remove_from_watchlist(user_id, tickers) -> list[str] — returns tickers removed
    get_watchlist(user_id) -> list[str]             — sorted active tickers
    get_all_active_watchlists() -> dict[str, list[str]] — all users, for cron
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── DB path — same file as trades, lessons, pending_approvals ─────────────────

_DEFAULT_DB = str(
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    / "Projects" / "data" / "trading_memory.db"
)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    # Read DB_PATH at call time (not import time) so tests can override via env.
    db_path = os.getenv("DB_PATH", _DEFAULT_DB)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def initialize_db() -> None:
    """Create the watchlist table if it doesn't exist."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  TEXT    NOT NULL,
                ticker   TEXT    NOT NULL,
                added_at TEXT    NOT NULL,
                active   INTEGER NOT NULL DEFAULT 1,
                UNIQUE (user_id, ticker)
            )
        """)


# ── Public API ────────────────────────────────────────────────────────────────

def add_to_watchlist(user_id: str, tickers: list[str]) -> list[str]:
    """
    Add tickers to a user's watchlist.

    If a ticker was previously unwatched (active=0) it is reactivated.
    Duplicate adds are silently ignored.

    Returns the list of tickers that were added or reactivated.
    """
    initialize_db()
    added: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as c:
        for raw in tickers:
            ticker = raw.upper().strip()
            if not ticker:
                continue
            c.execute(
                """
                INSERT INTO watchlist (user_id, ticker, added_at, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT (user_id, ticker)
                DO UPDATE SET active = 1, added_at = excluded.added_at
                """,
                (user_id, ticker, now),
            )
            added.append(ticker)

    return added


def remove_from_watchlist(user_id: str, tickers: list[str]) -> list[str]:
    """
    Remove tickers from a user's watchlist (soft delete — sets active=0).

    Returns the list of tickers that were actually removed.
    Tickers not on the watchlist are silently ignored.
    """
    initialize_db()
    removed: list[str] = []

    with _conn() as c:
        for raw in tickers:
            ticker = raw.upper().strip()
            if not ticker:
                continue
            cursor = c.execute(
                """
                UPDATE watchlist SET active = 0
                WHERE user_id = ? AND ticker = ? AND active = 1
                """,
                (user_id, ticker),
            )
            if cursor.rowcount > 0:
                removed.append(ticker)

    return removed


def get_watchlist(user_id: str) -> list[str]:
    """
    Return all active watchlist tickers for a user, sorted alphabetically.
    Returns an empty list if the user has no watchlist.
    """
    initialize_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT ticker FROM watchlist
            WHERE user_id = ? AND active = 1
            ORDER BY ticker ASC
            """,
            (user_id,),
        ).fetchall()
    return [row["ticker"] for row in rows]


def get_all_active_watchlists() -> dict[str, list[str]]:
    """
    Return every user's active watchlist tickers, grouped by user_id.

    Used by the cron scanner to fan out across all users each run.
    Returns an empty dict if no watchlists exist.

    Example:
        {
            "teams:abc123": ["AAPL", "NVDA"],
            "teams:def456": ["MSFT", "TSLA"],
        }
    """
    initialize_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT user_id, ticker FROM watchlist
            WHERE active = 1
            ORDER BY user_id, ticker ASC
            """
        ).fetchall()

    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["user_id"], []).append(row["ticker"])
    return result


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    USER = "teams:test-user"
    print("=== Watchlist smoke test ===\n")

    add_to_watchlist(USER, ["AAPL", "NVDA", "MSFT"])
    print(f"After add AAPL NVDA MSFT: {get_watchlist(USER)}")

    remove_from_watchlist(USER, ["NVDA"])
    print(f"After remove NVDA:        {get_watchlist(USER)}")

    add_to_watchlist(USER, ["NVDA"])
    print(f"After re-add NVDA:        {get_watchlist(USER)}")

    add_to_watchlist("teams:user-2", ["TSLA", "AMZN"])
    print(f"\nAll watchlists:\n{json.dumps(get_all_active_watchlists(), indent=2)}")

    # Cleanup
    remove_from_watchlist(USER, ["AAPL", "NVDA", "MSFT"])
    remove_from_watchlist("teams:user-2", ["TSLA", "AMZN"])
    print("\n✅ Smoke test passed")
