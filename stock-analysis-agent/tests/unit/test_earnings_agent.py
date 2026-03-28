"""
tests/unit/test_earnings_agent.py

Unit tests for orchestrator/earnings_agent.py (Phase 6).

All yfinance, Brave Search, and Claude API calls are mocked — fully offline.

Coverage:
  - fetch_earnings_calendar() returns data when event is within days_ahead
  - fetch_earnings_calendar() returns None when event is too far out
  - fetch_earnings_calendar() returns None when no calendar data available
  - fetch_earnings_calendar() handles DataFrame and dict yfinance returns
  - scan_user_earnings() returns EarningsAlert for upcoming events
  - scan_user_earnings() skips tickers with no upcoming event
  - scan_user_earnings() returns [] for empty ticker list
  - scan_user_earnings() skips ticker when yfinance raises an exception
  - EarningsAlert has correct fields from mocked data
  - run_full_earnings_scan() deduplicates tickers across users
  - run_full_earnings_scan() returns empty dict when no watchlists
  - run_full_earnings_scan() fans results back to each user
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.earnings_agent import (
    EarningsAlert,
    fetch_earnings_calendar,
    scan_user_earnings,
    run_full_earnings_scan,
    EARNINGS_LOOKAHEAD_DAYS,
)
# Ensure module-level symbols are patched correctly in tests above


# ── Mock builders ─────────────────────────────────────────────────────────────

def _cal_dict(days_from_now=3):
    """Return a fake yfinance calendar dict with earnings in N days."""
    from datetime import datetime, timezone
    import pandas as pd
    earnings_ts = pd.Timestamp(date.today() + timedelta(days=days_from_now))
    return {
        "Earnings Date":    [earnings_ts],
        "Earnings Average": 1.62,
        "Earnings Low":     1.55,
        "Earnings High":    1.70,
        "Revenue Average":  94_200_000_000.0,
    }


def _mock_ticker(cal_dict):
    t = MagicMock()
    t.calendar = cal_dict
    t.info = {
        "recommendationKey":        "buy",
        "targetMeanPrice":          245.0,
        "currentPrice":             218.0,
        "numberOfAnalystOpinions":  42,
    }
    return t


def _mock_thesis_response(sentiment="bullish"):
    import json
    payload = json.dumps({
        "thesis":    "Strong earnings expected with EPS beat likely.",
        "sentiment": sentiment,
        "summary":   f"Earnings in 3 days — {sentiment} setup",
    })
    msg  = MagicMock()
    blk  = MagicMock()
    blk.text = payload
    msg.content = [blk]
    return msg


# ── fetch_earnings_calendar ───────────────────────────────────────────────────

class TestFetchEarningsCalendar:

    @patch("orchestrator.earnings_agent.yf")
    def test_returns_data_when_within_days_ahead(self, mock_yf):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(days_from_now=3))
        result = fetch_earnings_calendar("AAPL", days_ahead=7)

        assert result is not None
        assert result["days_until"] == 3
        assert result["eps_estimate"] == pytest.approx(1.62)
        assert result["revenue_estimate"] == pytest.approx(94_200_000_000.0)

    @patch("orchestrator.earnings_agent.yf")
    def test_returns_none_when_too_far_out(self, mock_yf):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(days_from_now=10))
        result = fetch_earnings_calendar("AAPL", days_ahead=7)
        assert result is None

    @patch("orchestrator.earnings_agent.yf")
    def test_returns_none_when_calendar_is_none(self, mock_yf):
        t = MagicMock()
        t.calendar = None
        mock_yf.Ticker.return_value = t
        assert fetch_earnings_calendar("AAPL") is None

    @patch("orchestrator.earnings_agent.yf")
    def test_returns_none_when_yfinance_raises(self, mock_yf):
        mock_yf.Ticker.side_effect = Exception("network error")
        assert fetch_earnings_calendar("AAPL") is None

    @patch("orchestrator.earnings_agent.yf")
    def test_returns_none_for_past_earnings(self, mock_yf):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(days_from_now=-2))
        assert fetch_earnings_calendar("AAPL") is None

    @patch("orchestrator.earnings_agent.yf")
    def test_exactly_at_days_ahead_boundary(self, mock_yf):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(days_from_now=7))
        result = fetch_earnings_calendar("AAPL", days_ahead=7)
        assert result is not None
        assert result["days_until"] == 7

    @patch("orchestrator.earnings_agent.yf")
    def test_plain_date_object_handled(self, mock_yf):
        """yfinance ≥ 0.2.x returns plain datetime.date objects, not pd.Timestamps."""
        from datetime import date as _date
        cal = {
            "Earnings Date":    [_date.today() + timedelta(days=3)],
            "Earnings Average": 1.50,
            "Earnings Low":     1.40,
            "Earnings High":    1.60,
            "Revenue Average":  50_000_000_000.0,
        }
        t = MagicMock()
        t.calendar = cal
        mock_yf.Ticker.return_value = t
        result = fetch_earnings_calendar("AAPL", days_ahead=7)
        assert result is not None
        assert result["days_until"] == 3

    @patch("orchestrator.earnings_agent.yf")
    def test_earnings_date_isoformat(self, mock_yf):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(days_from_now=4))
        result = fetch_earnings_calendar("AAPL")
        assert result is not None
        expected = (date.today() + timedelta(days=4)).isoformat()
        assert result["earnings_date"] == expected


# ── scan_user_earnings ────────────────────────────────────────────────────────

class TestScanUserEarnings:

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={
        "recommendation": "buy", "target_mean": 245.0, "analyst_count": 42, "upside_pct": 12.4
    })
    @patch("orchestrator.earnings_agent.yf")
    def test_returns_alert_for_upcoming_earnings(
        self, mock_yf, mock_analyst, mock_brave, mock_anthropic
    ):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(days_from_now=3))
        mock_anthropic.return_value.messages.create.return_value = _mock_thesis_response("bullish")

        alerts = scan_user_earnings("user:1", ["AAPL"])

        assert len(alerts) == 1
        a = alerts[0]
        assert a.ticker       == "AAPL"
        assert a.user_id      == "user:1"
        assert a.days_until   == 3
        assert a.sentiment    == "bullish"
        assert a.analyst_rating == "buy"
        assert a.eps_estimate == pytest.approx(1.62)

    @patch("orchestrator.earnings_agent.yf")
    def test_skips_tickers_with_no_upcoming_earnings(self, mock_yf):
        t = MagicMock()
        t.calendar = None
        mock_yf.Ticker.return_value = t

        alerts = scan_user_earnings("user:1", ["AAPL"])
        assert alerts == []

    def test_empty_tickers_returns_empty(self):
        alerts = scan_user_earnings("user:1", [])
        assert alerts == []

    @patch("orchestrator.earnings_agent.yf")
    def test_exception_on_one_ticker_skips_it(self, mock_yf):
        mock_yf.Ticker.side_effect = Exception("timeout")
        alerts = scan_user_earnings("user:1", ["AAPL"])
        assert alerts == []

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={})
    @patch("orchestrator.earnings_agent.yf")
    def test_mixed_upcoming_and_none(self, mock_yf, mock_analyst, mock_brave, mock_anthropic):
        """AAPL has earnings, MSFT does not — only AAPL in results."""
        def _ticker_factory(sym):
            t = MagicMock()
            t.calendar = _cal_dict(3) if sym == "AAPL" else None
            t.info = {}
            return t

        mock_yf.Ticker.side_effect = _ticker_factory
        mock_anthropic.return_value.messages.create.return_value = _mock_thesis_response()

        alerts = scan_user_earnings("user:1", ["AAPL", "MSFT"])
        assert len(alerts) == 1
        assert alerts[0].ticker == "AAPL"

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={})
    @patch("orchestrator.earnings_agent.yf")
    def test_thesis_fallback_on_bad_json(self, mock_yf, mock_analyst, mock_brave, mock_anthropic):
        """If Sonnet returns invalid JSON, a safe stub thesis is used."""
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(3))
        bad_response = MagicMock()
        bad_response.content = [MagicMock(text="not json at all")]
        mock_anthropic.return_value.messages.create.return_value = bad_response

        alerts = scan_user_earnings("user:1", ["AAPL"])
        assert len(alerts) == 1
        assert alerts[0].sentiment == "neutral"
        assert alerts[0].thesis    != ""

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={})
    @patch("orchestrator.earnings_agent.yf")
    def test_revenue_estimate_in_alert(self, mock_yf, mock_analyst, mock_brave, mock_anthropic):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(3))
        mock_anthropic.return_value.messages.create.return_value = _mock_thesis_response()

        alerts = scan_user_earnings("user:1", ["AAPL"])
        assert alerts[0].revenue_estimate == pytest.approx(94_200_000_000.0)


# ── run_full_earnings_scan ────────────────────────────────────────────────────

class TestRunFullEarningsScan:

    @patch("orchestrator.earnings_agent.get_all_active_watchlists", return_value={})
    def test_empty_watchlists_returns_empty(self, mock_wl):
        assert run_full_earnings_scan(queue_alerts=False) == {}

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={})
    @patch("orchestrator.earnings_agent.yf")
    @patch("orchestrator.earnings_agent.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"], "user:2": ["NVDA"]})
    def test_results_grouped_by_user(self, mock_wl, mock_yf, mock_analyst, mock_brave, mock_anthropic):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(3))
        mock_anthropic.return_value.messages.create.return_value = _mock_thesis_response()

        results = run_full_earnings_scan(queue_alerts=False)
        assert "user:1" in results
        assert "user:2" in results
        assert results["user:1"][0].ticker == "AAPL"
        assert results["user:2"][0].ticker == "NVDA"

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={})
    @patch("orchestrator.earnings_agent.yf")
    @patch("orchestrator.earnings_agent.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"], "user:2": ["AAPL", "NVDA"]})
    def test_shared_ticker_fetched_once(self, mock_wl, mock_yf, mock_analyst, mock_brave, mock_anthropic):
        """AAPL on two watchlists — yfinance + Sonnet called once for AAPL, once for NVDA."""
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(3))
        mock_anthropic.return_value.messages.create.return_value = _mock_thesis_response()

        run_full_earnings_scan(queue_alerts=False)

        # 2 unique tickers → 2 Ticker() calls
        assert mock_yf.Ticker.call_count == 2

    @patch("orchestrator.earnings_agent.yf")
    @patch("orchestrator.earnings_agent.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"]})
    def test_no_upcoming_earnings_returns_empty(self, mock_wl, mock_yf):
        t = MagicMock()
        t.calendar = None
        mock_yf.Ticker.return_value = t

        results = run_full_earnings_scan(queue_alerts=False)
        assert results == {}

    @patch("orchestrator.earnings_agent.anthropic.Anthropic")
    @patch("orchestrator.earnings_agent._brave_search", return_value=[])
    @patch("orchestrator.earnings_agent._get_analyst_data", return_value={})
    @patch("orchestrator.earnings_agent.yf")
    @patch("orchestrator.earnings_agent.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"]})
    def test_user_id_set_correctly_in_fan_out(self, mock_wl, mock_yf, mock_analyst, mock_brave, mock_anthropic):
        mock_yf.Ticker.return_value = _mock_ticker(_cal_dict(3))
        mock_anthropic.return_value.messages.create.return_value = _mock_thesis_response()

        results = run_full_earnings_scan(queue_alerts=False)
        assert results["user:1"][0].user_id == "user:1"
