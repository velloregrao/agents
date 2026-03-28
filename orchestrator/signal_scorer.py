"""
orchestrator/signal_scorer.py

Deterministic technical signal scorer for the watchlist monitor (Phase 5).

Entry point:
    score_ticker(ticker) -> SignalScore

Six scoring components (uses existing tools — no new API calls):
    1. RSI 14-period          ±2.5   oversold / overbought
    2. Trend (price vs SMA50) ±1.5   uptrend / downtrend
    3. MACD crossover         ±1.5   momentum direction
    4. Bollinger Band position ±1.5  mean-reversion pressure
    5. Volume amplifier       ±1.0   unusual volume confirms direction
    6. Momentum (day change%) ±2.0   intraday conviction

Max possible score: ±10.0
Signal fires when abs(score) >= SIGNAL_THRESHOLD (default 6.5 via env).

No LLM used here — pure math, fully offline-testable.
Haiku narrative is added in Step 5.4 only when the signal fires.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from stock_agent.tools import get_technical_indicators, get_current_price
from orchestrator.indicators import (
    score_rsi, score_trend, score_macd,
    score_bollinger, score_volume, score_momentum, build_summary,
)

# ── Config ────────────────────────────────────────────────────────────────────

SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "6.5"))

# ── Contract ──────────────────────────────────────────────────────────────────

@dataclass
class SignalScore:
    """
    Result of scoring one ticker.

    Fields:
        ticker      Stock symbol
        score       Aggregate score clamped to [-10, +10]
        direction   "bullish" | "bearish" | "neutral"
        components  Per-component breakdown:
                    {"rsi": {"score": 2.5, "reason": "RSI 28.4 oversold"}, ...}
        fired       True when abs(score) >= SIGNAL_THRESHOLD
        summary     1-line human-readable description (built from top components)
        price       Current price at scoring time
        rsi         RSI-14 value (displayed in the Teams alert card)
    """
    ticker:     str
    score:      float
    direction:  str
    components: dict
    fired:      bool
    summary:    str
    price:      float
    rsi:        float


# ── Component scorers ─────────────────────────────────────────────────────────
# Thin wrappers kept for backward compatibility with any callers that imported
# the private names directly.  All logic lives in orchestrator/indicators.py.

def _score_rsi(rsi: float) -> tuple[float, str]:
    return score_rsi(rsi)

def _score_trend(price: float, sma_50: float | None) -> tuple[float, str]:
    return score_trend(price, sma_50, label="SMA50")

def _score_macd(macd_line: float, macd_signal: float) -> tuple[float, str]:
    return score_macd(macd_line, macd_signal)

def _score_bollinger(price, bb_upper, bb_middle, bb_lower) -> tuple[float, str]:
    return score_bollinger(price, bb_upper, bb_middle, bb_lower)

def _score_volume(volume, avg_volume, partial_score) -> tuple[float, str]:
    return score_volume(volume, avg_volume, partial_score)

def _score_momentum(change_pct) -> tuple[float, str]:
    return score_momentum(change_pct)

def _build_summary(direction: str, components: dict, score: float) -> str:
    return build_summary(direction, components, score)


# ── Public entry point ────────────────────────────────────────────────────────

def score_ticker(ticker: str) -> SignalScore:
    """
    Score a single ticker against 6 technical components.

    Makes two yfinance-backed API calls via existing tools:
        get_technical_indicators(ticker, "3mo")
        get_current_price(ticker)

    Returns fired=True when abs(score) >= SIGNAL_THRESHOLD.
    Returns a safe neutral SignalScore (fired=False) on any data error
    so a single bad ticker never crashes the fan-out loop.
    """
    ticker = ticker.upper()

    # ── Data fetch ─────────────────────────────────────────────────────────────
    tech       = get_technical_indicators(ticker, "3mo")
    price_data = get_current_price(ticker)

    if tech.get("error") or price_data.get("error"):
        err = tech.get("error") or price_data.get("error")
        return SignalScore(
            ticker=ticker, score=0.0, direction="neutral",
            components={}, fired=False,
            summary=f"⚠️ Data error for {ticker}: {err}",
            price=0.0, rsi=50.0,
        )

    price      = float(price_data.get("current_price") or tech.get("current_price") or 0.0)
    rsi        = float(tech.get("rsi_14", 50.0))
    sma_50     = tech.get("sma_50")        # may be None
    macd_line  = float(tech.get("macd_line",   0.0))
    macd_sig   = float(tech.get("macd_signal", 0.0))
    bb_upper   = float(tech.get("bollinger_upper",  price * 1.05))
    bb_middle  = float(tech.get("bollinger_middle", price))
    bb_lower   = float(tech.get("bollinger_lower",  price * 0.95))
    volume     = price_data.get("volume")
    avg_volume = price_data.get("avg_volume")
    change_pct = price_data.get("change_pct")

    # ── Score each component ───────────────────────────────────────────────────
    rsi_val,   rsi_reason   = _score_rsi(rsi)
    trend_val, trend_reason = _score_trend(price, sma_50)
    macd_val,  macd_reason  = _score_macd(macd_line, macd_sig)
    bb_val,    bb_reason    = _score_bollinger(price, bb_upper, bb_middle, bb_lower)

    # Partial score (before volume + momentum) determines volume direction
    partial = rsi_val + trend_val + macd_val + bb_val

    vol_val,   vol_reason   = _score_volume(volume, avg_volume, partial)
    mom_val,   mom_reason   = _score_momentum(change_pct)

    raw_total = partial + vol_val + mom_val
    total     = round(max(-10.0, min(10.0, raw_total)), 2)  # clamp to [-10, +10]

    components = {
        "rsi":       {"score": rsi_val,   "reason": rsi_reason},
        "trend":     {"score": trend_val, "reason": trend_reason},
        "macd":      {"score": macd_val,  "reason": macd_reason},
        "bollinger": {"score": bb_val,    "reason": bb_reason},
        "volume":    {"score": vol_val,   "reason": vol_reason},
        "momentum":  {"score": mom_val,   "reason": mom_reason},
    }

    direction = "bullish" if total > 0 else "bearish" if total < 0 else "neutral"
    fired     = abs(total) >= SIGNAL_THRESHOLD
    summary   = _build_summary(direction, components, total)

    return SignalScore(
        ticker=ticker,
        score=total,
        direction=direction,
        components=components,
        fired=fired,
        summary=summary,
        price=round(price, 4),
        rsi=round(rsi, 2),
    )


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    tickers = sys.argv[1:] or ["AAPL", "NVDA", "AMD"]
    for t in tickers:
        s = score_ticker(t)
        print(f"\n{'─' * 50}")
        print(f"  {s.ticker}  price=${s.price:.2f}  RSI={s.rsi}")
        print(f"  score={s.score:+.2f}  direction={s.direction}  fired={s.fired}")
        print(f"  {s.summary}")
        print("  Components:")
        for k, v in s.components.items():
            bar = "█" * int(abs(v["score"]) * 2)
            sign = "+" if v["score"] >= 0 else ""
            print(f"    {k:12s} {sign}{v['score']:.2f}  {bar}  {v['reason']}")
