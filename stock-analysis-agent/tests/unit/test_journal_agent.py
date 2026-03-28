"""
tests/unit/test_journal_agent.py

Unit tests for orchestrator/journal_agent.py (Phase 9).

All Alpaca API calls, Claude API calls, and DB writes are mocked — fully offline.

Coverage:
  - sync_closed_trades() closes a trade when ticker gone from Alpaca positions
  - sync_closed_trades() leaves trade open when ticker still held
  - sync_closed_trades() returns no-op when no open DB trades
  - sync_closed_trades() skips trade when price fetch returns zero
  - sync_closed_trades() records error when close_trade fails
  - sync_closed_trades() handles all positions closed (empty Alpaca response)
  - build_weekly_digest() returns skipped when reflect() returns skipped
  - build_weekly_digest() returns completed digest when reflect() succeeds
  - build_weekly_digest() includes performance stats
  - run_journal_sync() delegates to sync_closed_trades and returns result
  - run_weekly_reflection() calls sync then reflect
  - run_weekly_reflection() queues alert when digest completed
  - run_weekly_reflection() does not queue alert when digest skipped
  - memory.py store_trade() accepts new signal_score/momentum_score/thesis_text params
  - memory.py store_trade() is backward compatible (new params all optional)
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.journal_agent import (
    sync_closed_trades,
    build_weekly_digest,
    run_journal_sync,
    run_weekly_reflection,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _positions(*tickers) -> dict:
    """Build a mock get_positions() response holding the given tickers."""
    return {
        "positions": [
            {"ticker": t, "market_value": 1000.0, "quantity": 5.0, "current_price": 200.0}
            for t in tickers
        ]
    }


def _open_trades(*tickers) -> dict:
    """Build a mock get_open_trades() response with one open trade per ticker."""
    return {
        "open_trades": [
            {
                "order_id":    f"ord-{t.lower()}",
                "ticker":      t,
                "side":        "BUY",
                "quantity":    5.0,
                "entry_price": 190.0,
                "status":      "OPEN",
            }
            for t in tickers
        ]
    }


def _price(price: float) -> dict:
    return {"current_price": price}


def _close_ok(pnl=50.0, pnl_pct=2.5, hold_days=3) -> dict:
    return {"status": "closed", "pnl": pnl, "pnl_pct": pnl_pct, "hold_days": hold_days}


def _reflect_completed(n_lessons=3) -> dict:
    return {
        "status":          "completed",
        "trades_analyzed": 5,
        "lessons":         [f"Lesson {i+1}" for i in range(n_lessons)],
        "summary":         "Patterns observed over 5 trades.",
    }


def _reflect_skipped() -> dict:
    return {
        "status":           "skipped",
        "reason":           "Need at least 3 closed trades. Have 1.",
        "trades_available": 1,
    }


# ── sync_closed_trades ─────────────────────────────────────────────────────────

class TestSyncClosedTrades:

    @patch("orchestrator.journal_agent.close_trade", return_value=_close_ok())
    @patch("orchestrator.journal_agent.get_current_price", return_value=_price(210.0))
    @patch("orchestrator.journal_agent.get_open_trades", return_value=_open_trades("AAPL"))
    @patch("orchestrator.journal_agent.get_positions",   return_value=_positions())   # empty
    def test_closes_trade_when_ticker_gone(self, _pos, _open, _price, mock_close):
        result = sync_closed_trades()

        assert result["synced"]  == 1
        assert result["skipped"] == 0
        assert result["errors"]  == 0
        mock_close.assert_called_once_with(
            order_id="ord-aapl",
            exit_price=210.0,
            outcome_notes=pytest.approx("Auto-closed by journal sync — position no longer held in Alpaca"),
        )

    @patch("orchestrator.journal_agent.close_trade")
    @patch("orchestrator.journal_agent.get_current_price")
    @patch("orchestrator.journal_agent.get_open_trades", return_value=_open_trades("AAPL"))
    @patch("orchestrator.journal_agent.get_positions",   return_value=_positions("AAPL"))
    def test_keeps_trade_open_when_still_held(self, _pos, _open, mock_price, mock_close):
        result = sync_closed_trades()

        assert result["synced"]  == 0
        assert result["skipped"] == 0
        assert result["errors"]  == 0
        mock_close.assert_not_called()
        mock_price.assert_not_called()

    @patch("orchestrator.journal_agent.close_trade")
    @patch("orchestrator.journal_agent.get_current_price")
    @patch("orchestrator.journal_agent.get_open_trades", return_value={"open_trades": []})
    @patch("orchestrator.journal_agent.get_positions",   return_value=_positions())
    def test_no_op_when_no_open_trades(self, _pos, _open, mock_price, mock_close):
        result = sync_closed_trades()

        assert result["synced"]  == 0
        assert result["skipped"] == 0
        mock_close.assert_not_called()

    @patch("orchestrator.journal_agent.close_trade")
    @patch("orchestrator.journal_agent.get_current_price", return_value={"current_price": 0})
    @patch("orchestrator.journal_agent.get_open_trades", return_value=_open_trades("AAPL"))
    @patch("orchestrator.journal_agent.get_positions",   return_value=_positions())
    def test_skips_trade_when_price_is_zero(self, _pos, _open, _price, mock_close):
        result = sync_closed_trades()

        assert result["synced"]  == 0
        assert result["skipped"] == 1
        mock_close.assert_not_called()

    @patch("orchestrator.journal_agent.close_trade", return_value={"error": "trade not found"})
    @patch("orchestrator.journal_agent.get_current_price", return_value=_price(200.0))
    @patch("orchestrator.journal_agent.get_open_trades", return_value=_open_trades("AAPL"))
    @patch("orchestrator.journal_agent.get_positions",   return_value=_positions())
    def test_records_error_when_close_trade_fails(self, _pos, _open, _price, _close):
        result = sync_closed_trades()

        assert result["errors"]  == 1
        assert result["synced"]  == 0
        assert result["details"][0]["status"] == "error"

    @patch("orchestrator.journal_agent.close_trade", return_value=_close_ok())
    @patch("orchestrator.journal_agent.get_current_price", return_value=_price(205.0))
    @patch("orchestrator.journal_agent.get_open_trades",
           return_value=_open_trades("AAPL", "NVDA", "MSFT"))
    @patch("orchestrator.journal_agent.get_positions", return_value=_positions())  # all gone
    def test_closes_multiple_trades_when_all_positions_gone(self, _pos, _open, _price, mock_close):
        result = sync_closed_trades()

        assert result["synced"] == 3
        assert mock_close.call_count == 3

    @patch("orchestrator.journal_agent.close_trade", return_value=_close_ok())
    @patch("orchestrator.journal_agent.get_current_price", return_value=_price(200.0))
    @patch("orchestrator.journal_agent.get_open_trades",
           return_value=_open_trades("AAPL", "NVDA"))
    @patch("orchestrator.journal_agent.get_positions", return_value=_positions("NVDA"))  # AAPL gone
    def test_closes_only_missing_tickers(self, _pos, _open, _price, mock_close):
        result = sync_closed_trades()

        assert result["synced"] == 1
        closed_tickers = [
            c.kwargs.get("order_id") or c.args[0]
            for c in mock_close.call_args_list
        ]
        assert any("aapl" in str(t).lower() for t in closed_tickers)

    @patch("orchestrator.journal_agent.get_positions",
           return_value={"error": "network timeout"})
    def test_returns_empty_on_alpaca_error(self, _pos):
        result = sync_closed_trades()

        assert result["synced"]  == 0
        assert result["skipped"] == 0
        assert result["errors"]  == 0


# ── build_weekly_digest ────────────────────────────────────────────────────────

class TestBuildWeeklyDigest:

    @patch("orchestrator.journal_agent.get_performance_summary",
           return_value={"total_trades": 1, "win_rate": 100.0, "total_pnl": 20.0})
    @patch("orchestrator.journal_agent.reflect", return_value=_reflect_skipped())
    def test_returns_skipped_when_not_enough_trades(self, _reflect, _perf):
        digest = build_weekly_digest()

        assert digest["status"]   == "skipped"
        assert digest["lessons"]  == []
        assert "performance" in digest

    @patch("orchestrator.journal_agent.get_performance_summary",
           return_value={"total_trades": 5, "win_rate": 60.0, "total_pnl": 120.0})
    @patch("orchestrator.journal_agent.reflect", return_value=_reflect_completed(3))
    def test_returns_completed_with_lessons(self, _reflect, _perf):
        digest = build_weekly_digest()

        assert digest["status"]          == "completed"
        assert len(digest["lessons"])    == 3
        assert digest["trades_analyzed"] == 5
        assert "summary" in digest
        assert "performance" in digest

    @patch("orchestrator.journal_agent.get_performance_summary",
           return_value={"win_rate": 75.0, "total_pnl": 250.0, "total_trades": 8})
    @patch("orchestrator.journal_agent.reflect", return_value=_reflect_completed(5))
    def test_performance_stats_included(self, _reflect, mock_perf):
        digest = build_weekly_digest()

        assert digest["performance"]["win_rate"]   == 75.0
        assert digest["performance"]["total_pnl"]  == 250.0
        assert digest["performance"]["total_trades"] == 8

    @patch("orchestrator.journal_agent.get_performance_summary", return_value={})
    @patch("orchestrator.journal_agent.reflect", return_value=_reflect_completed(0))
    def test_handles_zero_lessons(self, _reflect, _perf):
        digest = build_weekly_digest()

        assert digest["status"]       == "completed"
        assert digest["lessons"]      == []
        assert digest["summary"]      != ""


# ── run_journal_sync ───────────────────────────────────────────────────────────

class TestRunJournalSync:

    @patch("orchestrator.journal_agent.sync_closed_trades",
           return_value={"synced": 2, "skipped": 0, "errors": 0, "details": []})
    def test_delegates_to_sync_and_returns_result(self, mock_sync):
        result = run_journal_sync()

        mock_sync.assert_called_once()
        assert result["synced"] == 2

    @patch("orchestrator.journal_agent.sync_closed_trades",
           return_value={"synced": 0, "skipped": 0, "errors": 0, "details": []})
    def test_returns_zero_counts_when_nothing_to_sync(self, _sync):
        result = run_journal_sync()

        assert result["synced"]  == 0
        assert result["errors"]  == 0


# ── run_weekly_reflection ──────────────────────────────────────────────────────

class TestRunWeeklyReflection:

    def _patch_all(self, digest_status="completed"):
        """Return a dict of patches for run_weekly_reflection."""
        patches = {
            "sync":  patch("orchestrator.journal_agent.sync_closed_trades",
                           return_value={"synced": 1, "skipped": 0, "errors": 0, "details": []}),
            "build": patch("orchestrator.journal_agent.build_weekly_digest",
                           return_value={
                               "status":          digest_status,
                               "week_of":         "Jan 27, 2026",
                               "trades_analyzed": 5,
                               "lessons":         ["Lesson 1", "Lesson 2"],
                               "summary":         "Good week.",
                               "performance":     {"win_rate": 60.0},
                           }),
            "queue": patch("orchestrator.journal_agent.queue_journal_alert"),
            "users": patch("orchestrator.journal_agent.get_all_active_watchlists",
                           return_value={"user:1": ["AAPL"], "user:2": ["NVDA"]}),
        }
        return patches

    def test_calls_sync_before_reflect(self):
        call_order = []
        with patch("orchestrator.journal_agent.sync_closed_trades",
                   side_effect=lambda: call_order.append("sync") or
                   {"synced": 0, "skipped": 0, "errors": 0, "details": []}), \
             patch("orchestrator.journal_agent.build_weekly_digest",
                   side_effect=lambda: call_order.append("build") or {
                       "status": "skipped", "week_of": "", "trades_analyzed": 0,
                       "lessons": [], "summary": "", "performance": {},
                   }):
            run_weekly_reflection()

        assert call_order.index("sync") < call_order.index("build")

    def test_queues_alert_for_all_users_when_completed(self):
        p = self._patch_all("completed")
        with p["sync"], p["build"], p["queue"] as mock_queue, p["users"]:
            from orchestrator.alert_manager import queue_journal_alert
            with patch("orchestrator.journal_agent.queue_journal_alert") as mock_q:
                with patch("orchestrator.journal_agent.get_all_active_watchlists",
                           return_value={"user:1": ["AAPL"], "user:2": ["NVDA"]}):
                    run_weekly_reflection()
                    assert mock_q.call_count == 2

    def test_does_not_queue_when_skipped(self):
        p = self._patch_all("skipped")
        with p["sync"], p["build"], p["queue"] as mock_queue, p["users"]:
            with patch("orchestrator.journal_agent.queue_journal_alert") as mock_q:
                run_weekly_reflection()
                mock_q.assert_not_called()

    def test_returns_digest(self):
        p = self._patch_all("completed")
        with p["sync"], p["build"], p["queue"], p["users"]:
            with patch("orchestrator.journal_agent.queue_journal_alert"):
                with patch("orchestrator.journal_agent.get_all_active_watchlists",
                           return_value={"user:1": ["AAPL"]}):
                    digest = run_weekly_reflection()
        assert digest["status"]       == "completed"
        assert digest["trades_analyzed"] == 5


# ── memory.py store_trade backward compatibility ───────────────────────────────

class TestStoreTrade:

    def test_new_params_are_optional(self):
        """store_trade must accept calls without the new Phase 9 params."""
        from stock_agent.memory import store_trade
        import inspect
        sig = inspect.signature(store_trade)
        params = sig.parameters

        assert "signal_score"   in params
        assert "momentum_score" in params
        assert "thesis_text"    in params

        # All three must have defaults (i.e. be optional)
        assert params["signal_score"].default   is not inspect.Parameter.empty
        assert params["momentum_score"].default is not inspect.Parameter.empty
        assert params["thesis_text"].default    is not inspect.Parameter.empty

    def test_new_params_default_to_none(self):
        from stock_agent.memory import store_trade
        import inspect
        sig    = inspect.signature(store_trade)
        params = sig.parameters

        assert params["signal_score"].default   is None
        assert params["momentum_score"].default is None
        assert params["thesis_text"].default    is None
