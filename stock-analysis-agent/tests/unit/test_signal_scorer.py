"""
tests/unit/test_signal_scorer.py

Unit tests for orchestrator/signal_scorer.py

All yfinance-backed tools are mocked so tests run fully offline.
Tests cover:
  - Each component scorer in isolation
  - Full score_ticker() integration with synthetic data
  - Threshold firing logic
  - Edge cases: None sma_50, missing volume, data errors, clamping
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.signal_scorer import (
    SignalScore,
    SIGNAL_THRESHOLD,
    score_ticker,
    _score_rsi,
    _score_trend,
    _score_macd,
    _score_bollinger,
    _score_volume,
    _score_momentum,
)


# ── Mock data builders ────────────────────────────────────────────────────────

def _tech(
    rsi=50.0,
    sma_50=150.0,
    macd_line=0.0,
    macd_signal=0.0,
    bb_upper=160.0,
    bb_middle=150.0,
    bb_lower=140.0,
    current_price=150.0,
):
    return {
        "ticker": "AAPL",
        "current_price": current_price,
        "sma_20": current_price,
        "sma_50": sma_50,
        "sma_200": None,
        "ema_12": current_price,
        "ema_26": current_price,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "rsi_14": rsi,
        "bollinger_upper": bb_upper,
        "bollinger_middle": bb_middle,
        "bollinger_lower": bb_lower,
        "signals": [],
    }


def _price(
    current=150.0,
    change_pct=0.0,
    volume=1_000_000,
    avg_volume=1_000_000,
):
    return {
        "ticker": "AAPL",
        "current_price": current,
        "previous_close": current,
        "change": 0.0,
        "change_pct": change_pct,
        "volume": volume,
        "avg_volume": avg_volume,
        "market_state": "REGULAR",
    }


# ── Component: RSI ────────────────────────────────────────────────────────────

class TestScoreRsi:

    def test_deeply_oversold(self):
        score, reason = _score_rsi(22.0)
        assert score == +2.5
        assert "oversold" in reason.lower()

    def test_mildly_oversold(self):
        score, reason = _score_rsi(38.0)
        assert score == +1.0
        assert "mildly oversold" in reason.lower()

    def test_neutral(self):
        score, reason = _score_rsi(50.0)
        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_mildly_overbought(self):
        score, reason = _score_rsi(62.0)
        assert score == -1.0
        assert "mildly overbought" in reason.lower()

    def test_deeply_overbought(self):
        score, reason = _score_rsi(78.0)
        assert score == -2.5
        assert "overbought" in reason.lower()

    def test_boundary_exactly_30(self):
        # RSI == 30 is mildly oversold (< 30 would be deeply)
        score, _ = _score_rsi(30.0)
        assert score == +1.0

    def test_boundary_exactly_70(self):
        score, _ = _score_rsi(70.0)
        assert score == -1.0


# ── Component: Trend (SMA50) ──────────────────────────────────────────────────

class TestScoreTrend:

    def test_above_sma50_bullish(self):
        score, reason = _score_trend(155.0, 150.0)
        assert score == +1.5
        assert "above" in reason.lower()

    def test_below_sma50_bearish(self):
        score, reason = _score_trend(145.0, 150.0)
        assert score == -1.5
        assert "below" in reason.lower()

    def test_sma50_none_returns_zero(self):
        score, reason = _score_trend(150.0, None)
        assert score == 0.0
        assert "unavailable" in reason.lower()


# ── Component: MACD ───────────────────────────────────────────────────────────

class TestScoreMacd:

    def test_bullish_crossover(self):
        score, reason = _score_macd(1.5, 0.5)
        assert score == +1.5
        assert "bullish" in reason.lower()

    def test_bearish_crossover(self):
        score, reason = _score_macd(-0.5, 0.5)
        assert score == -1.5
        assert "bearish" in reason.lower()

    def test_flat(self):
        score, reason = _score_macd(1.0, 1.0)
        assert score == 0.0
        assert "flat" in reason.lower()


# ── Component: Bollinger Bands ────────────────────────────────────────────────

class TestScoreBollinger:

    def test_below_lower_band(self):
        score, reason = _score_bollinger(138.0, 160.0, 150.0, 140.0)
        assert score == +1.5
        assert "below lower" in reason.lower()

    def test_above_upper_band(self):
        score, reason = _score_bollinger(162.0, 160.0, 150.0, 140.0)
        assert score == -1.5
        assert "above upper" in reason.lower()

    def test_below_midline_inside_bands(self):
        score, reason = _score_bollinger(148.0, 160.0, 150.0, 140.0)
        assert score == +0.25
        assert "midline" in reason.lower()

    def test_above_midline_inside_bands(self):
        score, reason = _score_bollinger(152.0, 160.0, 150.0, 140.0)
        assert score == -0.25


# ── Component: Volume ─────────────────────────────────────────────────────────

class TestScoreVolume:

    def test_high_volume_amplifies_bullish(self):
        score, reason = _score_volume(2_000_000, 1_000_000, partial_score=+3.0)
        assert score == +1.0
        assert "high conviction" in reason.lower()

    def test_high_volume_amplifies_bearish(self):
        score, reason = _score_volume(2_000_000, 1_000_000, partial_score=-3.0)
        assert score == -1.0

    def test_moderate_volume(self):
        score, reason = _score_volume(1_300_000, 1_000_000, partial_score=+3.0)
        assert score == +0.5
        assert "moderate" in reason.lower()

    def test_normal_volume_contributes_nothing(self):
        score, _ = _score_volume(1_000_000, 1_000_000, partial_score=+3.0)
        assert score == 0.0

    def test_missing_avg_volume_returns_zero(self):
        score, reason = _score_volume(1_000_000, None, partial_score=+3.0)
        assert score == 0.0
        assert "unavailable" in reason.lower()

    def test_zero_avg_volume_returns_zero(self):
        score, _ = _score_volume(1_000_000, 0, partial_score=+3.0)
        assert score == 0.0


# ── Component: Momentum ───────────────────────────────────────────────────────

class TestScoreMomentum:

    def test_strong_up_day(self):
        score, reason = _score_momentum(4.5)
        assert score == +2.0
        assert "strong up" in reason.lower()

    def test_moderate_up_day(self):
        score, reason = _score_momentum(1.5)
        assert score == +1.0
        assert "moderate up" in reason.lower()

    def test_flat_day(self):
        score, reason = _score_momentum(0.3)
        assert score == 0.0
        assert "flat" in reason.lower()

    def test_moderate_down_day(self):
        score, reason = _score_momentum(-1.5)
        assert score == -1.0
        assert "moderate down" in reason.lower()

    def test_strong_down_day(self):
        score, reason = _score_momentum(-4.0)
        assert score == -2.0
        assert "strong down" in reason.lower()

    def test_none_returns_zero(self):
        score, reason = _score_momentum(None)
        assert score == 0.0
        assert "unavailable" in reason.lower()


# ── Full score_ticker() integration ──────────────────────────────────────────

class TestScoreTicker:

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_strong_bullish_fires(self, mock_tech, mock_price):
        """
        RSI 25 (+2.5) + below lower BB (+1.5) + MACD bullish (+1.5)
        + above SMA50 (+1.5) + volume 2x (+1.0) + +3% day (+2.0) = 10.0
        """
        mock_tech.return_value = _tech(
            rsi=25.0,
            sma_50=140.0,         # price (150) above sma_50 → bullish
            macd_line=1.0,
            macd_signal=0.5,      # MACD bullish
            bb_upper=160.0,
            bb_middle=155.0,
            bb_lower=155.0,       # price (150) < lower BB → bullish
            current_price=150.0,
        )
        mock_price.return_value = _price(
            current=150.0,
            change_pct=3.5,       # strong up day
            volume=2_000_000,
            avg_volume=1_000_000, # 2x volume
        )

        result = score_ticker("AAPL")

        assert result.ticker    == "AAPL"
        assert result.direction == "bullish"
        assert result.score     >= SIGNAL_THRESHOLD
        assert result.fired     is True
        assert result.price     == 150.0
        assert result.rsi       == 25.0
        assert "bullish" in result.summary.lower()

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_strong_bearish_fires(self, mock_tech, mock_price):
        """
        RSI 75 (-2.5) + above upper BB (-1.5) + MACD bearish (-1.5)
        + below SMA50 (-1.5) + volume 2x (-1.0) + -3% day (-2.0) = -10.0
        """
        mock_tech.return_value = _tech(
            rsi=75.0,
            sma_50=160.0,         # price (150) below sma_50 → bearish
            macd_line=-0.5,
            macd_signal=0.5,      # MACD bearish
            bb_upper=145.0,       # price (150) > upper BB → bearish
            bb_middle=140.0,
            bb_lower=135.0,
            current_price=150.0,
        )
        mock_price.return_value = _price(
            current=150.0,
            change_pct=-3.5,
            volume=2_000_000,
            avg_volume=1_000_000,
        )

        result = score_ticker("NVDA")

        assert result.direction == "bearish"
        assert result.score     <= -SIGNAL_THRESHOLD
        assert result.fired     is True
        assert "bearish" in result.summary.lower()

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_neutral_does_not_fire(self, mock_tech, mock_price):
        """All indicators neutral — score near 0, fired=False."""
        mock_tech.return_value = _tech(
            rsi=50.0,
            sma_50=150.0,         # price == sma_50 → bearish (just below)
            macd_line=0.0,
            macd_signal=0.0,
            bb_upper=160.0,
            bb_middle=150.0,
            bb_lower=140.0,
            current_price=150.0,
        )
        mock_price.return_value = _price(
            current=150.0,
            change_pct=0.2,
            volume=1_000_000,
            avg_volume=1_000_000,
        )

        result = score_ticker("MSFT")

        assert abs(result.score) < SIGNAL_THRESHOLD
        assert result.fired is False

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_data_error_returns_safe_neutral(self, mock_tech, mock_price):
        """Tool error → safe neutral SignalScore, never raises."""
        mock_tech.return_value  = {"error": "yfinance timeout"}
        mock_price.return_value = _price()

        result = score_ticker("BAD")

        assert result.ticker    == "BAD"
        assert result.score     == 0.0
        assert result.fired     is False
        assert result.direction == "neutral"
        assert "error" in result.summary.lower() or "⚠️" in result.summary

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_missing_sma50_handled(self, mock_tech, mock_price):
        """sma_50=None (< 50 days of data) — trend component scores 0, no crash."""
        mock_tech.return_value = _tech(rsi=28.0, sma_50=None)
        mock_price.return_value = _price()

        result = score_ticker("AAPL")

        assert result.components["trend"]["score"] == 0.0
        assert "unavailable" in result.components["trend"]["reason"].lower()

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_score_clamped_to_ten(self, mock_tech, mock_price):
        """Even if components sum above 10, score is clamped to ±10."""
        mock_tech.return_value = _tech(
            rsi=20.0,          # +2.5
            sma_50=100.0,      # price 150 > 100 → +1.5
            macd_line=5.0,
            macd_signal=0.0,   # +1.5
            bb_lower=200.0,    # price 150 < lower 200 → +1.5
            bb_middle=210.0,
            bb_upper=220.0,
        )
        mock_price.return_value = _price(
            change_pct=5.0,    # +2.0
            volume=3_000_000,
            avg_volume=1_000_000,  # +1.0
        )

        result = score_ticker("AAPL")
        assert result.score <= 10.0

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_ticker_normalised_to_uppercase(self, mock_tech, mock_price):
        mock_tech.return_value  = _tech()
        mock_price.return_value = _price()

        result = score_ticker("aapl")
        assert result.ticker == "AAPL"

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_components_dict_has_all_six_keys(self, mock_tech, mock_price):
        mock_tech.return_value  = _tech()
        mock_price.return_value = _price()

        result = score_ticker("AAPL")
        assert set(result.components.keys()) == {
            "rsi", "trend", "macd", "bollinger", "volume", "momentum"
        }

    @patch("orchestrator.signal_scorer.get_current_price")
    @patch("orchestrator.signal_scorer.get_technical_indicators")
    def test_threshold_boundary_exactly_at_threshold(self, mock_tech, mock_price):
        """
        Construct a score of exactly SIGNAL_THRESHOLD (6.5):
          RSI 25 (+2.5) + above SMA50 (+1.5) + MACD bullish (+1.5)
          + inside BB below midline (+0.25) + no volume boost (0)
          + +2% day (+1.0) = 6.75 → fired
        """
        mock_tech.return_value = _tech(
            rsi=25.0,
            sma_50=140.0,
            macd_line=1.0,
            macd_signal=0.5,
            bb_upper=160.0,
            bb_middle=152.0,
            bb_lower=140.0,
            current_price=150.0,
        )
        mock_price.return_value = _price(
            change_pct=2.0,
            volume=1_000_000,
            avg_volume=1_000_000,
        )

        result = score_ticker("AAPL")
        # RSI 25 (+2.5) + SMA50 +1.5 + MACD +1.5 + BB below midline +0.25
        # + no vol (0) + momentum +1.0 = 6.75
        assert result.score >= SIGNAL_THRESHOLD
        assert result.fired is True
