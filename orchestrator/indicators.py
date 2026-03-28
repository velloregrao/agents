"""
orchestrator/indicators.py

Shared technical scoring functions used by both signal_scorer.py (daily
single-timeframe) and mtf_agent.py (15m / daily / weekly multi-timeframe).

Each function takes raw indicator values and returns (score, reason_string).
Scores are additive and clamped to [-10, +10] by the caller.

No I/O, no imports beyond stdlib — fully offline-testable.
"""


def score_rsi(rsi: float) -> tuple[float, str]:
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


def score_trend(
    price:       float,
    moving_avg:  float | None,
    label:       str = "SMA50",
) -> tuple[float, str]:
    """
    Price above the moving average = uptrend (+1.5).
    Price below the moving average = downtrend (−1.5).
    If moving_avg is None (insufficient bars), score 0.

    The *label* parameter identifies the MA in the reason string so callers
    can pass "SMA50", "EMA20", "SMA20(wk)", etc. without modifying this function.
    """
    if moving_avg is None:
        return 0.0, f"{label} unavailable"
    if price > moving_avg:
        return +1.5, f"above {label} ({moving_avg:.2f})"
    return -1.5, f"below {label} ({moving_avg:.2f})"


def score_macd(macd_line: float, macd_signal: float) -> tuple[float, str]:
    """
    MACD line above signal line = bullish momentum (+1.5).
    MACD line below signal line = bearish momentum (−1.5).
    """
    if macd_line > macd_signal:
        return +1.5, "MACD bullish crossover"
    if macd_line < macd_signal:
        return -1.5, "MACD bearish crossover"
    return 0.0, "MACD flat"


def score_bollinger(
    price:     float,
    bb_upper:  float,
    bb_middle: float,
    bb_lower:  float,
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
    if price < bb_middle:
        return +0.25, "below BB midline"
    return -0.25, "above BB midline"


def score_volume(
    volume:        int | None,
    avg_volume:    int | None,
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


def score_momentum(change_pct: float | None) -> tuple[float, str]:
    """
    Bar-over-bar price change percentage. Max ±2.0.

    Two tiers each side:
        ≥ +3% → +2.0   strong up bar
        ≥ +1% → +1.0   moderate up bar
        ≤ -3% → -2.0   strong down bar
        ≤ -1% → -1.0   moderate down bar
    """
    if change_pct is None:
        return 0.0, "momentum unavailable"
    if change_pct >= 3.0:
        return +2.0, f"+{change_pct:.1f}% — strong up bar"
    if change_pct >= 1.0:
        return +1.0, f"+{change_pct:.1f}% — moderate up bar"
    if change_pct <= -3.0:
        return -2.0, f"{change_pct:.1f}% — strong down bar"
    if change_pct <= -1.0:
        return -1.0, f"{change_pct:.1f}% — moderate down bar"
    return 0.0, f"{change_pct:+.1f}% — flat"


def build_summary(direction: str, components: dict, score: float) -> str:
    """
    Build a 1-line summary from the top contributing components.
    Deterministic — no LLM.

    Example:
        "📈 Bullish signal (+7.5): RSI 28.4 — oversold, below lower BB, MACD bullish"
    """
    emoji = "📈" if direction == "bullish" else "📉" if direction == "bearish" else "➡️"

    ranked = sorted(
        [(abs(v["score"]), v["reason"]) for v in components.values() if abs(v["score"]) >= 0.5],
        reverse=True,
    )
    reasons = ", ".join(r for _, r in ranked[:3]) if ranked else "mixed signals"

    sign = "+" if score > 0 else ""
    return f"{emoji} {direction.capitalize()} signal ({sign}{score:.1f}): {reasons}"
