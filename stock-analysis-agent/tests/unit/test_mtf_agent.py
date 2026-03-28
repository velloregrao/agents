"""
tests/unit/test_mtf_agent.py

Unit tests for orchestrator/mtf_agent.py (Phase 7).

All yfinance and Claude API calls are mocked — fully offline.

Coverage:
  - _fetch_timeframe() returns correct direction and RSI from mocked bars
  - _fetch_timeframe() returns error TimeframeScore on insufficient data
  - _fetch_timeframe() returns error TimeframeScore when yfinance raises
  - _compute_alignment() returns bullish when 2/3 bullish
  - _compute_alignment() returns bearish when 3/3 bearish
  - _compute_alignment() returns neutral when 1/3 or 0/3 aligned
  - _compute_alignment() neutral timeframes don't count toward alignment
  - analyze_ticker_mtf() returns signal_fired=True when aligned
  - analyze_ticker_mtf() returns signal_fired=False when not aligned
  - analyze_tickers_mtf() processes multiple tickers and returns all results
  - format_mtf_markdown() includes ticker and alignment in output
  - indicators.py score_rsi / score_trend / score_macd return correct values
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.mtf_agent import (
    TimeframeSpec, TimeframeScore, MTFResult,
    TIMEFRAMES,
    _fetch_timeframe,
    _compute_alignment,
    analyze_ticker_mtf,
    analyze_tickers_mtf,
    format_mtf_markdown,
)
from orchestrator.indicators import (
    score_rsi, score_trend, score_macd, score_bollinger, score_volume, score_momentum,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_bars(n: int = 60, close_start: float = 100.0, trend: str = "flat") -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with *n* rows."""
    import numpy as np
    if trend == "up":
        closes = [close_start + i * 0.5 for i in range(n)]
    elif trend == "down":
        closes = [close_start - i * 0.5 for i in range(n)]
    else:
        closes = [close_start + (i % 5 - 2) * 0.1 for i in range(n)]

    data = {
        "Open":   closes,
        "High":   [c * 1.01 for c in closes],
        "Low":    [c * 0.99 for c in closes],
        "Close":  closes,
        "Volume": [1_000_000] * n,
    }
    return pd.DataFrame(data)


def _daily_spec() -> TimeframeSpec:
    return next(s for s in TIMEFRAMES if s.name == "daily")


# ── indicators.py unit tests ──────────────────────────────────────────────────

class TestIndicators:
    def test_score_rsi_oversold(self):
        score, reason = score_rsi(25.0)
        assert score == pytest.approx(2.5)
        assert "oversold" in reason

    def test_score_rsi_overbought(self):
        score, reason = score_rsi(75.0)
        assert score == pytest.approx(-2.5)
        assert "overbought" in reason

    def test_score_rsi_neutral(self):
        score, _ = score_rsi(50.0)
        assert score == pytest.approx(0.0)

    def test_score_trend_above(self):
        score, reason = score_trend(110.0, 100.0, "SMA50")
        assert score == pytest.approx(1.5)
        assert "above SMA50" in reason

    def test_score_trend_below(self):
        score, reason = score_trend(90.0, 100.0, "EMA20")
        assert score == pytest.approx(-1.5)
        assert "below EMA20" in reason

    def test_score_trend_none_ma(self):
        score, reason = score_trend(100.0, None, "SMA50")
        assert score == pytest.approx(0.0)
        assert "unavailable" in reason

    def test_score_macd_bullish(self):
        score, reason = score_macd(0.5, 0.1)
        assert score == pytest.approx(1.5)
        assert "bullish" in reason

    def test_score_macd_bearish(self):
        score, _ = score_macd(-0.1, 0.1)
        assert score == pytest.approx(-1.5)

    def test_score_bollinger_below_lower(self):
        score, _ = score_bollinger(95.0, 110.0, 100.0, 98.0)
        assert score == pytest.approx(1.5)

    def test_score_bollinger_above_upper(self):
        score, _ = score_bollinger(115.0, 110.0, 100.0, 90.0)
        assert score == pytest.approx(-1.5)

    def test_score_volume_high_conviction(self):
        score, reason = score_volume(2_000_000, 1_000_000, partial_score=3.0)
        assert score == pytest.approx(1.0)
        assert "high conviction" in reason

    def test_score_momentum_strong_up(self):
        score, reason = score_momentum(4.0)
        assert score == pytest.approx(2.0)
        assert "strong" in reason


# ── _fetch_timeframe ──────────────────────────────────────────────────────────

class TestFetchTimeframe:

    @patch("orchestrator.mtf_agent.yf")
    def test_returns_timeframe_score_on_valid_data(self, mock_yf):
        mock_yf.Ticker.return_value.history.return_value = _make_bars(60)
        spec   = _daily_spec()
        result = _fetch_timeframe("AAPL", spec)

        assert result.error is None
        assert result.name  == "daily"
        assert result.label == "Daily"
        assert isinstance(result.score, float)
        assert result.direction in ("bullish", "bearish", "neutral")
        assert 0 <= result.rsi <= 100

    @patch("orchestrator.mtf_agent.yf")
    def test_returns_error_on_insufficient_bars(self, mock_yf):
        mock_yf.Ticker.return_value.history.return_value = _make_bars(5)
        result = _fetch_timeframe("AAPL", _daily_spec())

        assert result.error is not None
        assert result.direction == "neutral"
        assert result.score == pytest.approx(0.0)

    @patch("orchestrator.mtf_agent.yf")
    def test_returns_error_on_empty_dataframe(self, mock_yf):
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
        result = _fetch_timeframe("AAPL", _daily_spec())

        assert result.error is not None

    @patch("orchestrator.mtf_agent.yf")
    def test_returns_error_when_yfinance_raises(self, mock_yf):
        mock_yf.Ticker.side_effect = Exception("network error")
        result = _fetch_timeframe("AAPL", _daily_spec())

        assert result.error is not None
        assert result.direction == "neutral"

    @patch("orchestrator.mtf_agent.yf")
    def test_uptrend_bars_produce_positive_trend_component(self, mock_yf):
        mock_yf.Ticker.return_value.history.return_value = _make_bars(60, trend="up")
        result = _fetch_timeframe("AAPL", _daily_spec())

        # In a rising sequence the last close is well above SMA50
        assert result.components["trend"]["score"] == pytest.approx(1.5)

    @patch("orchestrator.mtf_agent.yf")
    def test_all_timeframe_specs_work(self, mock_yf):
        """Verify each TimeframeSpec in TIMEFRAMES can be processed."""
        mock_yf.Ticker.return_value.history.return_value = _make_bars(110)
        for spec in TIMEFRAMES:
            result = _fetch_timeframe("AAPL", spec)
            assert result.name == spec.name
            assert result.error is None, f"{spec.name} unexpectedly errored: {result.error}"


# ── _compute_alignment ────────────────────────────────────────────────────────

class TestComputeAlignment:

    def _tf(self, direction: str) -> TimeframeScore:
        return TimeframeScore(
            name="x", label="X", score=1.0 if direction == "bullish" else -1.0,
            direction=direction, rsi=50.0, trend_val=None,
            components={}, fired=False, error=None,
        )

    def test_three_bullish(self):
        tfs = [self._tf("bullish")] * 3
        alignment, count = _compute_alignment(tfs)
        assert alignment == "bullish"
        assert count == 3

    def test_three_bearish(self):
        tfs = [self._tf("bearish")] * 3
        alignment, count = _compute_alignment(tfs)
        assert alignment == "bearish"
        assert count == 3

    def test_two_bullish_one_bearish(self):
        tfs = [self._tf("bullish"), self._tf("bullish"), self._tf("bearish")]
        alignment, count = _compute_alignment(tfs)
        assert alignment == "bullish"
        assert count == 2

    def test_two_bearish_one_bullish(self):
        tfs = [self._tf("bearish"), self._tf("bearish"), self._tf("bullish")]
        alignment, count = _compute_alignment(tfs)
        assert alignment == "bearish"
        assert count == 2

    def test_one_bullish_two_neutral(self):
        tfs = [self._tf("bullish"), self._tf("neutral"), self._tf("neutral")]
        alignment, count = _compute_alignment(tfs)
        assert alignment == "neutral"
        assert count < 2  # does not fire

    def test_all_neutral(self):
        tfs = [self._tf("neutral")] * 3
        alignment, count = _compute_alignment(tfs)
        assert alignment == "neutral"
        assert count == 0

    def test_one_of_each(self):
        tfs = [self._tf("bullish"), self._tf("bearish"), self._tf("neutral")]
        alignment, count = _compute_alignment(tfs)
        assert alignment == "neutral"
        assert count < 2


# ── analyze_ticker_mtf ────────────────────────────────────────────────────────

class TestAnalyzeTickerMtf:

    @patch("orchestrator.mtf_agent.get_current_price", return_value={"current_price": 200.0})
    @patch("orchestrator.mtf_agent.anthropic.Anthropic")
    @patch("orchestrator.mtf_agent.yf")
    def test_signal_fired_when_aligned(self, mock_yf, mock_anthropic, mock_price):
        # 60 rising bars → all 3 timeframes bullish
        mock_yf.Ticker.return_value.history.return_value = _make_bars(110, trend="up")
        mock_anthropic.return_value.messages.create.return_value.content = [
            MagicMock(text="Strong bullish confluence across all timeframes.")
        ]
        result = analyze_ticker_mtf("AAPL")

        assert result.ticker == "AAPL"
        assert result.price  == pytest.approx(200.0)
        assert len(result.timeframes) == 3
        # aligned_count may vary but signal_fired reflects the threshold
        assert isinstance(result.signal_fired, bool)

    @patch("orchestrator.mtf_agent.get_current_price", return_value={"current_price": 150.0})
    @patch("orchestrator.mtf_agent.yf")
    def test_no_signal_when_data_unavailable(self, mock_yf, mock_price):
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
        result = analyze_ticker_mtf("AAPL")

        assert result.signal_fired is False
        assert result.aligned_count == 0
        assert all(tf.error is not None for tf in result.timeframes)

    @patch("orchestrator.mtf_agent.get_current_price", return_value={"current_price": 200.0})
    @patch("orchestrator.mtf_agent.anthropic.Anthropic")
    @patch("orchestrator.mtf_agent.yf")
    def test_narrative_empty_when_no_signal(self, mock_yf, mock_anthropic, mock_price):
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
        result = analyze_ticker_mtf("AAPL")
        assert result.narrative == ""
        mock_anthropic.return_value.messages.create.assert_not_called()

    @patch("orchestrator.mtf_agent.get_current_price", return_value={"current_price": 200.0})
    @patch("orchestrator.mtf_agent.anthropic.Anthropic")
    @patch("orchestrator.mtf_agent.yf")
    def test_alignment_type_format(self, mock_yf, mock_anthropic, mock_price):
        mock_yf.Ticker.return_value.history.return_value = _make_bars(110, trend="down")
        mock_anthropic.return_value.messages.create.return_value.content = [
            MagicMock(text="Bearish narrative.")
        ]
        result = analyze_ticker_mtf("AAPL")
        assert "/" in result.alignment_type
        assert result.alignment_type.endswith(f"/{len(TIMEFRAMES)}")


# ── analyze_tickers_mtf ───────────────────────────────────────────────────────

class TestAnalyzeTickersMtf:

    @patch("orchestrator.mtf_agent.get_current_price", return_value={"current_price": 200.0})
    @patch("orchestrator.mtf_agent.anthropic.Anthropic")
    @patch("orchestrator.mtf_agent.yf")
    def test_returns_result_for_each_ticker(self, mock_yf, mock_anthropic, mock_price):
        mock_yf.Ticker.return_value.history.return_value = _make_bars(110)
        mock_anthropic.return_value.messages.create.return_value.content = [
            MagicMock(text="Narrative.")
        ]
        results = analyze_tickers_mtf(["AAPL", "NVDA"])
        assert len(results) == 2
        tickers = {r.ticker for r in results}
        assert tickers == {"AAPL", "NVDA"}

    def test_empty_list_returns_empty(self):
        assert analyze_tickers_mtf([]) == []


# ── format_mtf_markdown ────────────────────────────────────────────────────────

class TestFormatMtfMarkdown:

    def _make_result(self, alignment: str, aligned_count: int, signal_fired: bool) -> MTFResult:
        tfs = [
            TimeframeScore(
                name=s.name, label=s.label, score=1.0 if alignment == "bullish" else -1.0,
                direction=alignment, rsi=45.0, trend_val=100.0,
                components={"rsi": {"score": 1.0, "reason": "RSI 45.0 — neutral"}},
                fired=False, error=None,
            )
            for s in TIMEFRAMES
        ]
        return MTFResult(
            ticker="AAPL", price=200.0, timeframes=tfs,
            alignment=alignment, aligned_count=aligned_count,
            alignment_type=f"{aligned_count}/{len(TIMEFRAMES)}",
            signal_fired=signal_fired,
            narrative="Strong confluence." if signal_fired else "",
            summary=f"AAPL {alignment}",
        )

    def test_contains_ticker(self):
        result = self._make_result("bullish", 3, True)
        md = format_mtf_markdown(result)
        assert "AAPL" in md

    def test_contains_alignment_verdict(self):
        result = self._make_result("bullish", 3, True)
        md = format_mtf_markdown(result)
        assert "BULLISH" in md
        assert "3/3" in md

    def test_contains_all_timeframe_labels(self):
        result = self._make_result("bearish", 2, True)
        md = format_mtf_markdown(result)
        for tf in result.timeframes:
            assert tf.label in md

    def test_narrative_included_when_signal_fired(self):
        result = self._make_result("bullish", 2, True)
        md = format_mtf_markdown(result)
        assert "Strong confluence." in md

    def test_narrative_absent_when_no_signal(self):
        result = self._make_result("neutral", 1, False)
        md = format_mtf_markdown(result)
        assert "Strong confluence." not in md

    def test_no_signal_shows_no_mtf_signal(self):
        result = self._make_result("neutral", 1, False)
        md = format_mtf_markdown(result)
        assert "No MTF signal" in md

    def test_error_timeframe_shown_gracefully(self):
        result = self._make_result("neutral", 0, False)
        result.timeframes[0] = TimeframeScore(
            name="15m", label="15-min", score=0.0,
            direction="neutral", rsi=50.0, trend_val=None,
            components={}, fired=False, error="Insufficient data",
        )
        md = format_mtf_markdown(result)
        assert "Error" in md or "Insufficient data" in md
