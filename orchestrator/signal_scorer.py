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


# ── Component scorers (each returns (score, reason_string)) ───────────────────

def _score_rsi(rsi: float) -> tuple[float, str]:
    """
    RSI < 30 = oversold → bullish.  RSI > 70 = overbought → bearish.
    Two tiers each side; max ±2.5.
    """
    if rsi < 30:
        return +2.5, f"RSI {rsi:.1f} — oversold"
    if rsi < 45:
        return +1.0, f"RSI {rsi:.1f} — mildly oversold"
    if rsi > 70:
        return -2.5, f"RSI {rsi:.1f} — overbought"
    if rsi > 55:
        return -1.0, f"RSI {rsi:.1f} — mildly overbought"
    return 0.0, f"RSI {rsi:.1f} — neutral"


def _score_trend(price: float, sma_50: float | None) -> tuple[float, str]:
    """
    Price above 50-day SMA = uptrend (+1.5).
    Price below 50-day SMA = downtrend (−1.5).
    If SMA50 is unavailable (< 50 days of history), score 0.
    """
    if sma_50 is None:
        return 0.0, "SMA50 unavailable"
    if price > sma_50:
        return +1.5, f"above SMA50 ({sma_50:.2f})"
    return -1.5, f"below SMA50 ({sma_50:.2f})"


def _score_macd(macd_line: float, macd_signal: float) -> tuple[float, str]:
    """
    MACD line above signal line = bullish momentum (+1.5).
    MACD line below signal line = bearish momentum (−1.5).
    """
    if macd_line > macd_signal:
        return +1.5, "MACD bullish crossover"
    if macd_line < macd_signal:
        return -1.5, "MACD bearish crossover"
    return 0.0, "MACD flat"


def _score_bollinger(
    price: float,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
) -> tuple[float, str]:
    """
    Mean-reversion pressure from Bollinger Band position. Max ±1.5.

    Outside the bands → strong mean-reversion signal (±1.5).
    Inside the bands → weak directional lean toward the midline (±0.25).
    """
    if price < bb_lower:
        return +1.5, f"below lower BB ({bb_lower:.2f}) — mean-reversion buy"
    if price > bb_upper:
        return -1.5, f"above upper BB ({bb_upper:.2f}) — mean-reversion sell"
    # Inside bands: small lean toward midline
    if price < bb_middle:
        return +0.25, "below BB midline"
    return -0.25, "above BB midline"


def _score_volume(
    volume: int | None,
    avg_volume: int | None,
    partial_score: float,
) -> tuple[float, str]:
    """
    Unusual volume amplifies the existing signal direction. Max ±1.0.

    Direction taken from the sign of partial_score (sum of RSI + trend + MACD + BB).
    Neutral volume contributes nothing — doesn't override signal direction.
    """
    if not volume or not avg_volume or avg_volume == 0:
        return 0.0, "volume data unavailable"

    ratio     = volume / avg_volume
    direction = 1.0 if partial_score >= 0 else -1.0

    if ratio >= 1.5:
        return direction * 1.0, f"volume {ratio:.1f}× avg — high conviction"
    if ratio >= 1.2:
        return direction * 0.5, f"volume {ratio:.1f}× avg — moderate conviction"
    return 0.0, f"volume {ratio:.1f}× avg — normal"


def _score_momentum(change_pct: float | None) -> tuple[float, str]:
    """
    Day-over-day price change percentage. Max ±2.0.

    Two tiers each side:
        ≥ +3% → +2.0   strong up day
        ≥ +1% → +1.0   moderate up day
        ≤ -3% → -2.0   strong down day
        ≤ -1% → -1.0   moderate down day
    """
    if change_pct is None:
        return 0.0, "momentum unavailable"
    if change_pct >= 3.0:
        return +2.0, f"+{change_pct:.1f}% — strong up day"
    if change_pct >= 1.0:
        return +1.0, f"+{change_pct:.1f}% — moderate up day"
    if change_pct <= -3.0:
        return -2.0, f"{change_pct:.1f}% — strong down day"
    if change_pct <= -1.0:
        return -1.0, f"{change_pct:.1f}% — moderate down day"
    return 0.0, f"{change_pct:+.1f}% — flat"


# ── Summary builder ───────────────────────────────────────────────────────────

def _build_summary(direction: str, components: dict, score: float) -> str:
    """
    Build a 1-line summary from the top contributing components.
    Deterministic — no LLM. The full Haiku narrative is added in Step 5.4.

    Example:
        "📈 Bullish signal (+7.5): RSI 28.4 — oversold, below lower BB, MACD bullish"
    """
    emoji = "📈" if direction == "bullish" else "📉" if direction == "bearish" else "➡️"

    # Sort components by absolute contribution, take top 3
    ranked = sorted(
        [(abs(v["score"]), v["reason"]) for v in components.values() if abs(v["score"]) >= 0.5],
        reverse=True,
    )
    reasons = ", ".join(r for _, r in ranked[:3]) if ranked else "mixed signals"

    sign = "+" if score > 0 else ""
    return f"{emoji} {direction.capitalize()} signal ({sign}{score:.1f}): {reasons}"


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
