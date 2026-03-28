"""
tests/unit/test_watchlist.py

Unit tests for stock_agent/watchlist.py

Uses a temporary SQLite file so tests never touch the real trading DB.
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

# Point at a temp DB BEFORE importing watchlist (module reads DB_PATH at import time)
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DB_PATH"] = _tmp_db.name
_tmp_db.close()

from stock_agent.watchlist import (
    initialize_db,
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    get_all_active_watchlists,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_table():
    """Drop and re-create the watchlist table before every test."""
    with sqlite3.connect(os.environ["DB_PATH"]) as c:
        c.execute("DROP TABLE IF EXISTS watchlist")
    initialize_db()
    yield


# ── add_to_watchlist ───────────────────────────────────────────────────────────

class TestAddToWatchlist:

    def test_add_single_ticker(self):
        added = add_to_watchlist("user:1", ["AAPL"])
        assert added == ["AAPL"]
        assert get_watchlist("user:1") == ["AAPL"]

    def test_add_multiple_tickers(self):
        added = add_to_watchlist("user:1", ["NVDA", "AAPL", "MSFT"])
        assert set(added) == {"NVDA", "AAPL", "MSFT"}
        assert get_watchlist("user:1") == ["AAPL", "MSFT", "NVDA"]  # alphabetical

    def test_normalises_to_uppercase(self):
        add_to_watchlist("user:1", ["aapl", "nvda"])
        assert get_watchlist("user:1") == ["AAPL", "NVDA"]

    def test_duplicate_add_is_idempotent(self):
        add_to_watchlist("user:1", ["AAPL"])
        added = add_to_watchlist("user:1", ["AAPL"])
        assert added == ["AAPL"]           # returns it (reactivated)
        assert get_watchlist("user:1") == ["AAPL"]   # still one entry

    def test_is_scoped_per_user(self):
        add_to_watchlist("user:1", ["AAPL"])
        add_to_watchlist("user:2", ["NVDA"])
        assert get_watchlist("user:1") == ["AAPL"]
        assert get_watchlist("user:2") == ["NVDA"]

    def test_reactivates_previously_removed_ticker(self):
        add_to_watchlist("user:1", ["AAPL"])
        remove_from_watchlist("user:1", ["AAPL"])
        assert get_watchlist("user:1") == []
        added = add_to_watchlist("user:1", ["AAPL"])
        assert added == ["AAPL"]
        assert get_watchlist("user:1") == ["AAPL"]


# ── remove_from_watchlist ──────────────────────────────────────────────────────

class TestRemoveFromWatchlist:

    def test_remove_existing_ticker(self):
        add_to_watchlist("user:1", ["AAPL", "NVDA"])
        removed = remove_from_watchlist("user:1", ["AAPL"])
        assert removed == ["AAPL"]
        assert get_watchlist("user:1") == ["NVDA"]

    def test_remove_nonexistent_returns_empty(self):
        removed = remove_from_watchlist("user:1", ["TSLA"])
        assert removed == []

    def test_remove_multiple(self):
        add_to_watchlist("user:1", ["AAPL", "MSFT", "NVDA"])
        removed = remove_from_watchlist("user:1", ["AAPL", "NVDA"])
        assert set(removed) == {"AAPL", "NVDA"}
        assert get_watchlist("user:1") == ["MSFT"]

    def test_remove_already_removed_returns_empty(self):
        add_to_watchlist("user:1", ["AAPL"])
        remove_from_watchlist("user:1", ["AAPL"])
        removed = remove_from_watchlist("user:1", ["AAPL"])
        assert removed == []

    def test_remove_is_scoped_per_user(self):
        add_to_watchlist("user:1", ["AAPL"])
        add_to_watchlist("user:2", ["AAPL"])
        remove_from_watchlist("user:1", ["AAPL"])
        assert get_watchlist("user:1") == []
        assert get_watchlist("user:2") == ["AAPL"]   # user:2 unaffected


# ── get_watchlist ──────────────────────────────────────────────────────────────

class TestGetWatchlist:

    def test_empty_watchlist_returns_empty_list(self):
        assert get_watchlist("user:nobody") == []

    def test_sorted_alphabetically(self):
        add_to_watchlist("user:1", ["TSLA", "AAPL", "MSFT"])
        assert get_watchlist("user:1") == ["AAPL", "MSFT", "TSLA"]

    def test_only_active_tickers_returned(self):
        add_to_watchlist("user:1", ["AAPL", "NVDA", "MSFT"])
        remove_from_watchlist("user:1", ["NVDA"])
        assert get_watchlist("user:1") == ["AAPL", "MSFT"]


# ── get_all_active_watchlists ─────────────────────────────────────────────────

class TestGetAllActiveWatchlists:

    def test_returns_all_users(self):
        add_to_watchlist("user:1", ["AAPL", "NVDA"])
        add_to_watchlist("user:2", ["MSFT"])
        result = get_all_active_watchlists()
        assert set(result["user:1"]) == {"AAPL", "NVDA"}
        assert result["user:2"] == ["MSFT"]

    def test_inactive_tickers_excluded(self):
        add_to_watchlist("user:1", ["AAPL", "NVDA"])
        remove_from_watchlist("user:1", ["NVDA"])
        result = get_all_active_watchlists()
        assert result["user:1"] == ["AAPL"]
        assert "NVDA" not in result.get("user:1", [])

    def test_empty_returns_empty_dict(self):
        assert get_all_active_watchlists() == {}

    def test_user_with_all_removed_not_in_result(self):
        add_to_watchlist("user:1", ["AAPL"])
        remove_from_watchlist("user:1", ["AAPL"])
        result = get_all_active_watchlists()
        assert "user:1" not in result
