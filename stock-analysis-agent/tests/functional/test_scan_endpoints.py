"""
tests/functional/test_scan_endpoints.py

Functional tests for the watchlist scan API endpoints (Phase 5 Step 5.5).

  POST /monitor/watchlist/scan  — on-demand single-user scan
  POST /monitor/scan/run        — full scan (all users), alerts queued
  GET  /monitor/scan/status     — scheduler state

All network calls and the scheduler itself are mocked so tests run fully
offline and don't start a background thread.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))


# ── Mock builders ─────────────────────────────────────────────────────────────

def _make_monitor_result(ticker="AAPL", user_id="user:1", verdict="APPROVED"):
    """Lightweight MonitorResult stand-in with all fields api.py accesses."""
    class _Verdict:
        value = verdict

    class _Signal:
        score     = 7.5
        direction = "bullish"
        summary   = f"📈 Bullish signal (+7.5)"
        price     = 150.0
        rsi       = 28.4
        fired     = True

    class _Risk:
        verdict      = _Verdict()
        adjusted_qty = 33
        reason       = "all_rules_passed"
        narrative    = ""

    class _Result:
        pass

    r = _Result()
    r.ticker       = ticker
    r.user_id      = user_id
    r.signal       = _Signal()
    r.risk         = _Risk()
    r.proposed_qty = 33
    return r


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_scheduler(monkeypatch):
    """Prevent the scheduler from actually starting during tests."""
    monkeypatch.setattr("orchestrator.scheduler.start", lambda: None)
    monkeypatch.setattr("orchestrator.scheduler.stop",  lambda: None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from stock_agent.api import app
    return TestClient(app, raise_server_exceptions=True)


# ── POST /monitor/watchlist/scan ──────────────────────────────────────────────

class TestWatchlistScanEndpoint:

    @patch("orchestrator.watchlist_monitor.score_ticker",
           return_value=None)   # overridden per test
    @patch("orchestrator.watchlist_monitor.evaluate_proposal",
           return_value=None)
    @patch("orchestrator.watchlist_monitor.get_account_balance",
           return_value={"equity": 100_000.0, "cash": 100_000.0, "buying_power": 200_000.0})
    def test_fired_signal_returns_alert(self, mock_bal, mock_risk, mock_score, client):
        from orchestrator.signal_scorer import SignalScore
        from orchestrator.risk_agent import RiskResult, Verdict

        mock_score.return_value = SignalScore(
            ticker="AAPL", score=7.5, direction="bullish",
            components={}, fired=True,
            summary="📈 Bullish signal (+7.5): RSI oversold",
            price=150.0, rsi=28.4,
        )
        mock_risk.return_value = RiskResult(
            verdict=Verdict.APPROVED, adjusted_qty=33,
            reason="all_rules_passed", narrative="", rule=0,
        )

        res = client.post("/monitor/watchlist/scan", json={
            "user_id": "user:1",
            "tickers": ["AAPL"],
            "equity":  100_000.0,
        })

        assert res.status_code == 200
        body = res.json()
        assert body["user_id"]      == "user:1"
        assert body["alerts_count"] == 1
        assert body["alerts"][0]["ticker"]           == "AAPL"
        assert body["alerts"][0]["signal"]["fired"]  is True
        assert body["alerts"][0]["risk"]["verdict"]  == "APPROVED"
        assert body["alerts"][0]["proposed_qty"]     == 33

    @patch("orchestrator.watchlist_monitor.get_account_balance",
           return_value={"equity": 100_000.0})
    @patch("orchestrator.watchlist_monitor.score_ticker")
    def test_neutral_signal_returns_empty_alerts(self, mock_score, mock_bal, client):
        from orchestrator.signal_scorer import SignalScore

        mock_score.return_value = SignalScore(
            ticker="AAPL", score=2.0, direction="bullish",
            components={}, fired=False,
            summary="➡️ Neutral (+2.0)",
            price=150.0, rsi=50.0,
        )

        res = client.post("/monitor/watchlist/scan", json={
            "user_id": "user:1",
            "tickers": ["AAPL"],
        })

        assert res.status_code == 200
        assert res.json()["alerts_count"] == 0
        assert res.json()["alerts"]       == []

    def test_empty_tickers_returns_empty(self, client):
        res = client.post("/monitor/watchlist/scan", json={
            "user_id": "user:1",
            "tickers": [],
        })
        assert res.status_code == 200
        assert res.json()["alerts_count"] == 0

    def test_missing_user_id_returns_422(self, client):
        res = client.post("/monitor/watchlist/scan", json={"tickers": ["AAPL"]})
        assert res.status_code == 422


# ── POST /monitor/scan/run ────────────────────────────────────────────────────

class TestScanRunNow:

    @patch("orchestrator.scheduler.run_now", return_value={
        "user:1": [_make_monitor_result("AAPL", "user:1")],
        "user:2": [_make_monitor_result("NVDA", "user:2")],
    })
    def test_returns_summary_of_queued_alerts(self, mock_run, client):
        res = client.post("/monitor/scan/run")

        assert res.status_code == 200
        body = res.json()
        assert body["status"]              == "ok"
        assert body["users_with_alerts"]   == 2
        assert body["total_alerts"]        == 2
        assert body["per_user"]["user:1"]  == 1
        assert body["per_user"]["user:2"]  == 1

    @patch("orchestrator.scheduler.run_now", return_value={})
    def test_no_signals_returns_zero_counts(self, mock_run, client):
        res = client.post("/monitor/scan/run")

        assert res.status_code == 200
        body = res.json()
        assert body["total_alerts"]      == 0
        assert body["users_with_alerts"] == 0

    @patch("orchestrator.scheduler.run_now", side_effect=Exception("DB connection failed"))
    def test_exception_returns_500(self, mock_run, client):
        res = client.post("/monitor/scan/run")
        assert res.status_code == 500


# ── GET /monitor/scan/status ──────────────────────────────────────────────────

class TestScanStatus:

    def test_returns_expected_fields(self, client):
        res = client.get("/monitor/scan/status")

        assert res.status_code == 200
        body = res.json()
        assert "scheduler_running"     in body
        assert "market_hours_now"      in body
        assert "scan_interval_minutes" in body
        assert "next_run_time"         in body
        assert "current_time_et"       in body

    def test_scan_interval_is_15(self, client):
        res = client.get("/monitor/scan/status")
        assert res.json()["scan_interval_minutes"] == 15

    def test_market_hours_now_is_bool(self, client):
        res = client.get("/monitor/scan/status")
        assert isinstance(res.json()["market_hours_now"], bool)
