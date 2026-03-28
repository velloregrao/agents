"""
tests/functional/test_watchlist_monitor.py

Functional tests for orchestrator/watchlist_monitor.py (Phase 5 Step 5.3).

All network calls (score_ticker, evaluate_proposal, get_account_balance,
get_all_active_watchlists) are mocked so tests run fully offline.

Coverage:
  - Only fired signals reach the risk gate
  - BLOCK verdicts are excluded from results (silent)
  - APPROVED / RESIZE / ESCALATE are included
  - One bad ticker (exception) doesn't kill the batch
  - Tickers are deduplicated across users — scored only once
  - run_full_scan() fetches watchlists and groups results by user_id
  - Empty watchlist / all-neutral signals → empty result
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from dataclasses import dataclass

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.watchlist_monitor import (
    MonitorResult,
    scan_user_watchlist,
    run_full_scan,
)
from orchestrator.signal_scorer import SignalScore
from orchestrator.risk_agent import RiskResult, Verdict


# ── Mock builders ─────────────────────────────────────────────────────────────

def _fired_signal(ticker="AAPL", score=7.5, direction="bullish"):
    return SignalScore(
        ticker=ticker, score=score, direction=direction,
        components={}, fired=True,
        summary=f"📈 Bullish signal ({score:+.1f}): RSI oversold",
        price=150.0, rsi=28.0,
    )


def _neutral_signal(ticker="AAPL"):
    return SignalScore(
        ticker=ticker, score=2.0, direction="bullish",
        components={}, fired=False,
        summary="➡️ Neutral signal (+2.0): no confluence",
        price=150.0, rsi=50.0,
    )


def _risk(verdict=Verdict.APPROVED, reason="all_rules_passed", adjusted_qty=33):
    return RiskResult(
        verdict=verdict,
        adjusted_qty=adjusted_qty,
        reason=reason,
        narrative="" if verdict == Verdict.APPROVED else "Risk narrative here.",
        rule=0 if verdict == Verdict.APPROVED else 1,
    )


def _account(equity=100_000.0):
    return {"equity": equity, "cash": equity, "buying_power": equity * 2}


# ── scan_user_watchlist ───────────────────────────────────────────────────────

class TestScanUserWatchlist:

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker",      return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_fired_approved_signal_included(self, mock_bal, mock_score, mock_risk):
        results = scan_user_watchlist("user:1", ["AAPL"])

        assert len(results) == 1
        assert results[0].ticker  == "AAPL"
        assert results[0].user_id == "user:1"
        assert results[0].signal.fired is True
        assert results[0].risk.verdict == Verdict.APPROVED

    @patch("orchestrator.watchlist_monitor.evaluate_proposal")
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_neutral_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_neutral_signal_not_included(self, mock_bal, mock_score, mock_risk):
        """Signal below threshold (fired=False) never reaches the risk gate."""
        results = scan_user_watchlist("user:1", ["AAPL"])

        assert results == []
        mock_risk.assert_not_called()

    @patch("orchestrator.watchlist_monitor.evaluate_proposal",
           return_value=_risk(verdict=Verdict.BLOCK, reason="daily_loss_halt", adjusted_qty=0))
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_block_verdict_excluded(self, mock_bal, mock_score, mock_risk):
        """BLOCK = circuit breaker active — no alert, no result."""
        results = scan_user_watchlist("user:1", ["AAPL"])

        assert results == []

    @patch("orchestrator.watchlist_monitor.evaluate_proposal",
           return_value=_risk(verdict=Verdict.ESCALATE, reason="correlation_guard", adjusted_qty=33))
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_escalate_verdict_included(self, mock_bal, mock_score, mock_risk):
        """ESCALATE → include result so Teams can show Adaptive Card approval."""
        results = scan_user_watchlist("user:1", ["AAPL"])

        assert len(results) == 1
        assert results[0].risk.verdict == Verdict.ESCALATE

    @patch("orchestrator.watchlist_monitor.evaluate_proposal",
           return_value=_risk(verdict=Verdict.RESIZE, reason="position_size_limit", adjusted_qty=20))
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_resize_verdict_included(self, mock_bal, mock_score, mock_risk):
        """RESIZE → include result with adjusted qty."""
        results = scan_user_watchlist("user:1", ["AAPL"])

        assert len(results) == 1
        assert results[0].risk.verdict       == Verdict.RESIZE
        assert results[0].risk.adjusted_qty  == 20

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker")
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_multiple_tickers_all_fired(self, mock_bal, mock_score, mock_risk):
        mock_score.side_effect = [
            _fired_signal("AAPL"),
            _fired_signal("NVDA"),
            _fired_signal("MSFT"),
        ]
        results = scan_user_watchlist("user:1", ["AAPL", "NVDA", "MSFT"])

        assert len(results) == 3
        tickers = {r.ticker for r in results}
        assert tickers == {"AAPL", "NVDA", "MSFT"}

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker")
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_mixed_fired_and_neutral(self, mock_bal, mock_score, mock_risk):
        """Only fired tickers should appear in results."""
        # Use a dispatch function so the right signal is returned regardless
        # of the order asyncio.gather processes the tickers (set-ordering).
        def _score_dispatch(ticker, *args, **kwargs):
            if ticker == "MSFT":
                return _neutral_signal("MSFT")
            return _fired_signal(ticker)

        mock_score.side_effect = _score_dispatch
        results = scan_user_watchlist("user:1", ["AAPL", "MSFT", "NVDA"])

        assert len(results) == 2
        tickers = {r.ticker for r in results}
        assert tickers == {"AAPL", "NVDA"}
        assert "MSFT" not in tickers

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker")
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_one_exception_does_not_kill_batch(self, mock_bal, mock_score, mock_risk):
        """
        If score_ticker raises for one ticker, the others still complete.
        The failing ticker gets a neutral score (fired=False) and is excluded.

        Note: asyncio.gather processes tickers in set order (non-deterministic),
        so we can't predict which mock side_effect lands on which ticker.
        We assert only that exactly one result comes back (one fired, one errored).
        """
        mock_score.side_effect = [
            Exception("yfinance timeout"),   # one ticker errors out
            _fired_signal("NVDA"),           # the other fires successfully
        ]
        results = scan_user_watchlist("user:1", ["AAPL", "NVDA"])

        # Exactly one ticker should produce a result — the errored one is excluded
        assert len(results) == 1
        assert results[0].signal.fired is True
        assert results[0].ticker in {"AAPL", "NVDA"}

    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_empty_ticker_list_returns_empty(self, mock_bal):
        results = scan_user_watchlist("user:1", [])
        assert results == []

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_fired_signal())
    def test_uses_provided_equity_skips_account_call(self, mock_score, mock_risk):
        """When equity is provided, get_account_balance should not be called."""
        with patch("orchestrator.watchlist_monitor.get_account_balance") as mock_bal:
            scan_user_watchlist("user:1", ["AAPL"], equity=100_000.0)
            mock_bal.assert_not_called()

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_proposed_qty_uses_5pct_position_sizing(self, mock_bal, mock_score, mock_risk):
        """
        equity=100_000, price=150 → 5% = $5,000 → floor(5000/150) = 33 shares
        """
        results = scan_user_watchlist("user:1", ["AAPL"], equity=100_000.0)

        assert results[0].proposed_qty == 33

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker",
           return_value=_fired_signal(direction="bearish", score=-7.5))
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    def test_bearish_signal_uses_sell_side(self, mock_bal, mock_score, mock_risk):
        """Bearish fired signal → side='sell' passed to evaluate_proposal."""
        scan_user_watchlist("user:1", ["AAPL"], equity=100_000.0)

        call_kwargs = mock_risk.call_args
        assert call_kwargs[1].get("side") == "sell" or call_kwargs[0][2] == "sell"


# ── run_full_scan ─────────────────────────────────────────────────────────────

class TestRunFullScan:

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker",      return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    @patch("orchestrator.watchlist_monitor.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"], "user:2": ["NVDA"]})
    def test_results_grouped_by_user(self, mock_wl, mock_bal, mock_score, mock_risk):
        results = run_full_scan()

        assert "user:1" in results
        assert "user:2" in results
        assert results["user:1"][0].ticker == "AAPL"
        assert results["user:2"][0].ticker == "NVDA"

    @patch("orchestrator.watchlist_monitor.get_all_active_watchlists", return_value={})
    def test_empty_watchlists_returns_empty(self, mock_wl):
        results = run_full_scan()
        assert results == {}

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker")
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    @patch("orchestrator.watchlist_monitor.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"], "user:2": ["AAPL", "NVDA"]})
    def test_shared_ticker_scored_once(self, mock_wl, mock_bal, mock_score, mock_risk):
        """
        AAPL is on both user:1 and user:2 watchlists.
        score_ticker should be called exactly once for AAPL (deduplication)
        and once for NVDA = 2 total calls, not 3.
        """
        mock_score.side_effect = lambda ticker, *a, **kw: _fired_signal(ticker)
        run_full_scan()

        # Two unique tickers → exactly 2 score_ticker calls
        assert mock_score.call_count == 2

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_neutral_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    @patch("orchestrator.watchlist_monitor.get_all_active_watchlists",
           return_value={"user:1": ["AAPL", "NVDA"]})
    def test_all_neutral_returns_empty(self, mock_wl, mock_bal, mock_score, mock_risk):
        """No signals fired → result is empty dict (no users to alert)."""
        results = run_full_scan()
        assert results == {}

    @patch("orchestrator.watchlist_monitor.evaluate_proposal",
           return_value=_risk(verdict=Verdict.BLOCK, reason="daily_loss_halt", adjusted_qty=0))
    @patch("orchestrator.watchlist_monitor.score_ticker", return_value=_fired_signal())
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    @patch("orchestrator.watchlist_monitor.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"]})
    def test_all_blocked_returns_empty(self, mock_wl, mock_bal, mock_score, mock_risk):
        """All signals fired but all blocked → no alerts → empty result."""
        results = run_full_scan()
        assert results == {}

    @patch("orchestrator.watchlist_monitor.evaluate_proposal", return_value=_risk())
    @patch("orchestrator.watchlist_monitor.score_ticker")
    @patch("orchestrator.watchlist_monitor.get_account_balance", return_value=_account())
    @patch("orchestrator.watchlist_monitor.get_all_active_watchlists",
           return_value={"user:1": ["AAPL"], "user:2": ["MSFT"]})
    def test_partial_users_have_results(self, mock_wl, mock_bal, mock_score, mock_risk):
        """user:1's ticker fires, user:2's doesn't — only user:1 in results."""
        def _score_dispatch(ticker, *a, **kw):
            return _fired_signal(ticker) if ticker == "AAPL" else _neutral_signal(ticker)

        mock_score.side_effect = _score_dispatch
        results = run_full_scan()

        assert "user:1" in results
        assert "user:2" not in results
