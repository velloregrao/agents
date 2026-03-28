"""
tests/unit/test_scheduler.py

Unit tests for orchestrator/scheduler.py (Phase 5 Step 5.5).

All tests are fully offline — no APScheduler is started, no network calls.

Coverage:
  - is_market_hours() returns True inside Mon–Fri 09:30–16:00 ET
  - is_market_hours() returns False before 09:30
  - is_market_hours() returns False at exactly 16:00 (close is exclusive)
  - is_market_hours() returns False after 16:00
  - is_market_hours() returns False on Saturday
  - is_market_hours() returns False on Sunday
  - is_market_hours() returns True at exactly 09:30 (open is inclusive)
  - is_market_hours() at 15:59 returns True (one minute before close)
  - Naive datetime (no tzinfo) treated as ET
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.scheduler import is_market_hours

_ET = ZoneInfo("America/New_York")


def _et(year=2024, month=1, day=2, hour=10, minute=0):
    """Build an ET-aware datetime. Jan 2 2024 = Tuesday."""
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


class TestIsMarketHours:

    # ── Inside market hours ────────────────────────────────────────────────────

    def test_midday_tuesday_returns_true(self):
        assert is_market_hours(_et(hour=12, minute=0)) is True

    def test_exactly_open_returns_true(self):
        """09:30:00 is the first valid second."""
        assert is_market_hours(_et(hour=9, minute=30)) is True

    def test_one_minute_before_close_returns_true(self):
        assert is_market_hours(_et(hour=15, minute=59)) is True

    def test_friday_midday_returns_true(self):
        # Jan 5 2024 = Friday
        assert is_market_hours(_et(day=5, hour=11, minute=0)) is True

    # ── Outside market hours ───────────────────────────────────────────────────

    def test_before_open_returns_false(self):
        assert is_market_hours(_et(hour=9, minute=29)) is False

    def test_midnight_returns_false(self):
        assert is_market_hours(_et(hour=0, minute=0)) is False

    def test_exactly_close_returns_false(self):
        """16:00:00 is NOT open — market is closed."""
        assert is_market_hours(_et(hour=16, minute=0)) is False

    def test_after_close_returns_false(self):
        assert is_market_hours(_et(hour=17, minute=0)) is False

    # ── Weekends ───────────────────────────────────────────────────────────────

    def test_saturday_returns_false(self):
        # Jan 6 2024 = Saturday
        assert is_market_hours(_et(day=6, hour=12, minute=0)) is False

    def test_sunday_returns_false(self):
        # Jan 7 2024 = Sunday
        assert is_market_hours(_et(day=7, hour=12, minute=0)) is False

    # ── Naive datetime ─────────────────────────────────────────────────────────

    def test_naive_datetime_treated_as_et(self):
        """A tz-naive datetime should be treated as ET (not raise)."""
        naive = datetime(2024, 1, 2, 12, 0)   # Tuesday noon — naive
        result = is_market_hours(naive)
        assert result is True

    # ── Default (no argument) ──────────────────────────────────────────────────

    def test_no_argument_does_not_raise(self):
        """Calling with no args uses datetime.now() — should not raise."""
        result = is_market_hours()
        assert isinstance(result, bool)
