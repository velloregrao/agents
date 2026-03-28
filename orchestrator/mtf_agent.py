"""
orchestrator/mtf_agent.py

Multi-timeframe (MTF) analysis agent (Phase 7).

Pattern: parallel fan-out/gather + evaluator-optimizer

Flow for one ticker:
    1. Fetch OHLCV bars for 3 timeframes concurrently via asyncio.gather():
          15-minute  (period="5d",  interval="15m")  — intraday momentum
          daily      (period="3mo", interval="1d")   — medium-term trend
          weekly     (period="2y",  interval="1wk")  — macro structure
    2. Score each timeframe independently:
          RSI(±2.5), Trend(±1.5), MACD(±1.5), BB(±1.5), Volume(±1.0), Momentum(±2.0)
    3. Evaluator: count aligned votes (bullish / bearish / neutral)
    4. Signal fires when aligned_count >= MTF_ALIGNMENT_THRESHOLD (default 2)
    5. Haiku narrates when signal fires; deterministic table always returned

Higher conviction than single-timeframe — only alerts when multiple
timeframes agree, filtering out short-term noise.

Public API:
    analyze_ticker_mtf(ticker) -> MTFResult
    analyze_tickers_mtf(tickers) -> list[MTFResult]
"""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

import anthropic
import yfinance as yf

from orchestrator.indicators import (
    score_rsi, score_trend, score_macd,
    score_bollinger, score_volume, score_momentum,
)
from orchestrator.signal_scorer import SIGNAL_THRESHOLD
from stock_agent.tools import get_current_price

# ── Config ────────────────────────────────────────────────────────────────────

MTF_ALIGNMENT_THRESHOLD = int(os.getenv("MTF_ALIGNMENT_THRESHOLD", "2"))
MTF_MAX_WORKERS         = int(os.getenv("MTF_MAX_WORKERS", "6"))
HAIKU = "claude-haiku-4-5-20251001"

# ── Timeframe specifications ──────────────────────────────────────────────────

@dataclass
class TimeframeSpec:
    name:          str    # internal key: "15m" | "daily" | "weekly"
    label:         str    # display label: "15-min" | "Daily" | "Weekly"
    interval:      str    # yfinance interval string
    period:        str    # yfinance period string
    trend_periods: int    # MA lookback in bars
    trend_type:    str    # "ema" | "sma"
    trend_label:   str    # display label for the MA: "EMA20" | "SMA50" | "SMA20(wk)"


TIMEFRAMES: list[TimeframeSpec] = [
    TimeframeSpec(
        name="15m", label="15-min",
        interval="15m", period="5d",
        trend_periods=20, trend_type="ema", trend_label="EMA20",
    ),
    TimeframeSpec(
        name="daily", label="Daily",
        interval="1d", period="3mo",
        trend_periods=50, trend_type="sma", trend_label="SMA50",
    ),
    TimeframeSpec(
        name="weekly", label="Weekly",
        interval="1wk", period="2y",
        trend_periods=20, trend_type="sma", trend_label="SMA20(wk)",
    ),
]

# ── Contracts ─────────────────────────────────────────────────────────────────

@dataclass
class TimeframeScore:
    """
    Technical score for one timeframe.

    Fields:
        name        Internal key matching TimeframeSpec.name
        label       Human-readable label for display
        score       Aggregate score clamped to [-10, +10]
        direction   "bullish" | "bearish" | "neutral"
        rsi         RSI-14 value
        trend_val   Moving average value (None if insufficient bars)
        components  Per-component breakdown (same shape as SignalScore)
        fired       True when abs(score) >= SIGNAL_THRESHOLD
        error       Set if data fetch failed for this timeframe
    """
    name:       str
    label:      str
    score:      float
    direction:  str
    rsi:        float
    trend_val:  float | None
    components: dict
    fired:      bool
    error:      str | None


@dataclass
class MTFResult:
    """
    Combined multi-timeframe result for one ticker.

    Fields:
        ticker          Stock symbol
        price           Current price at analysis time
        timeframes      List of 3 TimeframeScore (15m, daily, weekly)
        alignment       Dominant direction: "bullish" | "bearish" | "neutral"
        aligned_count   How many timeframes agree (0–3)
        alignment_type  Display string: "3/3" | "2/3" | "1/3" | "0/3"
        signal_fired    True when aligned_count >= MTF_ALIGNMENT_THRESHOLD
        narrative       Haiku-generated paragraph (empty if signal didn't fire)
        summary         One-line header for Teams card
    """
    ticker:         str
    price:          float
    timeframes:     list[TimeframeScore]
    alignment:      str
    aligned_count:  int
    alignment_type: str
    signal_fired:   bool
    narrative:      str
    summary:        str


# ── Per-timeframe sync worker ──────────────────────────────────────────────────

def _fetch_timeframe(ticker: str, spec: TimeframeSpec) -> TimeframeScore:
    """
    Fetch OHLCV bars and compute all technical indicators for one timeframe.

    Sync/blocking — designed to run in a ThreadPoolExecutor so the asyncio
    event loop stays free while yfinance is fetching over the network.

    Returns a neutral error TimeframeScore on any data or compute failure.
    """
    try:
        hist = yf.Ticker(ticker).history(interval=spec.interval, period=spec.period)

        if hist.empty or len(hist) < 20:
            return TimeframeScore(
                name=spec.name, label=spec.label, score=0.0,
                direction="neutral", rsi=50.0, trend_val=None,
                components={}, fired=False,
                error=f"Insufficient data ({len(hist)} bars)",
            )

        close = hist["Close"].dropna()
        current_price = float(close.iloc[-1])

        # ── Trend moving average ───────────────────────────────────────────────
        if len(close) >= spec.trend_periods:
            if spec.trend_type == "ema":
                trend_series = close.ewm(span=spec.trend_periods, adjust=False).mean()
            else:
                trend_series = close.rolling(spec.trend_periods).mean()
            trend_val = float(trend_series.iloc[-1])
        else:
            trend_val = None

        # ── RSI-14 ────────────────────────────────────────────────────────────
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = round(float(100 - (100 / (1 + rs.iloc[-1]))), 2)

        # ── MACD (12/26/9) ────────────────────────────────────────────────────
        ema12       = close.ewm(span=12, adjust=False).mean()
        ema26       = close.ewm(span=26, adjust=False).mean()
        macd_line   = float((ema12 - ema26).iloc[-1])
        macd_signal = float((ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1])

        # ── Bollinger Bands (20-period, 2σ) ──────────────────────────────────
        bb_mid    = close.rolling(20).mean()
        bb_std    = close.rolling(20).std()
        bb_upper  = float((bb_mid + 2 * bb_std).iloc[-1])
        bb_lower  = float((bb_mid - 2 * bb_std).iloc[-1])
        bb_middle = float(bb_mid.iloc[-1])

        # ── Volume ────────────────────────────────────────────────────────────
        volume     = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else None
        avg_volume = int(hist["Volume"].mean())   if "Volume" in hist.columns else None

        # ── Bar-over-bar momentum ─────────────────────────────────────────────
        change_pct = (
            float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
            if len(close) >= 2 else None
        )

        # ── Score each component ──────────────────────────────────────────────
        rsi_val,   rsi_reason   = score_rsi(rsi)
        trend_val_s, trend_reason = score_trend(current_price, trend_val, spec.trend_label)
        macd_val,  macd_reason  = score_macd(macd_line, macd_signal)
        bb_val,    bb_reason    = score_bollinger(current_price, bb_upper, bb_middle, bb_lower)
        partial                 = rsi_val + trend_val_s + macd_val + bb_val
        vol_val,   vol_reason   = score_volume(volume, avg_volume, partial)
        mom_val,   mom_reason   = score_momentum(change_pct)

        raw_total = partial + vol_val + mom_val
        total     = round(max(-10.0, min(10.0, raw_total)), 2)
        direction = "bullish" if total > 0 else "bearish" if total < 0 else "neutral"

        components = {
            "rsi":       {"score": rsi_val,     "reason": rsi_reason},
            "trend":     {"score": trend_val_s, "reason": trend_reason},
            "macd":      {"score": macd_val,    "reason": macd_reason},
            "bollinger": {"score": bb_val,      "reason": bb_reason},
            "volume":    {"score": vol_val,     "reason": vol_reason},
            "momentum":  {"score": mom_val,     "reason": mom_reason},
        }

        return TimeframeScore(
            name=spec.name, label=spec.label, score=total,
            direction=direction, rsi=rsi, trend_val=trend_val,
            components=components, fired=abs(total) >= SIGNAL_THRESHOLD,
            error=None,
        )

    except Exception as exc:
        print(f"[mtf] fetch error for {ticker} {spec.name}: {exc}", file=sys.stderr)
        return TimeframeScore(
            name=spec.name, label=spec.label, score=0.0,
            direction="neutral", rsi=50.0, trend_val=None,
            components={}, fired=False, error=str(exc),
        )


# ── Async concurrency layer ────────────────────────────────────────────────────

async def _fetch_all_timeframes(
    ticker:   str,
    executor: ThreadPoolExecutor,
) -> list[TimeframeScore]:
    """
    Fetch all 3 timeframes concurrently.

    return_exceptions=True — one failed timeframe never aborts the batch.
    """
    loop    = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(executor, _fetch_timeframe, ticker, spec)
          for spec in TIMEFRAMES],
        return_exceptions=True,
    )

    output: list[TimeframeScore] = []
    for spec, result in zip(TIMEFRAMES, results):
        if isinstance(result, TimeframeScore):
            output.append(result)
        else:
            print(f"[mtf] unexpected error for {ticker} {spec.name}: {result}", file=sys.stderr)
            output.append(TimeframeScore(
                name=spec.name, label=spec.label, score=0.0,
                direction="neutral", rsi=50.0, trend_val=None,
                components={}, fired=False, error=str(result),
            ))
    return output


# ── Alignment evaluator ────────────────────────────────────────────────────────

def _compute_alignment(timeframes: list[TimeframeScore]) -> tuple[str, int]:
    """
    Count bullish vs bearish votes. Neutral timeframes abstain.

    Returns (dominant_direction, vote_count).
    """
    bullish = sum(1 for tf in timeframes if tf.direction == "bullish")
    bearish = sum(1 for tf in timeframes if tf.direction == "bearish")

    if bullish >= 2 and bullish >= bearish:
        return "bullish", bullish
    if bearish >= 2 and bearish > bullish:
        return "bearish", bearish
    return "neutral", max(bullish, bearish)


# ── Haiku narrative ────────────────────────────────────────────────────────────

def _generate_narrative(ticker: str, result: "MTFResult") -> str:
    """
    Ask Haiku for a 2-3 sentence confluence narrative when the signal fires.

    Uses Haiku (not Sonnet) — this is formatting/description from structured
    data, not reasoning. Haiku is the correct model per CLAUDE.md tiering.
    Falls back to a deterministic stub on any error.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    tf_lines = "\n".join(
        f"- {tf.label}: {tf.direction} (score {tf.score:+.1f}, RSI {tf.rsi:.1f})"
        + (f", error: {tf.error}" if tf.error else "")
        for tf in result.timeframes
    )

    prompt = (
        f"You are a technical analyst. Write 2-3 sentences describing this "
        f"multi-timeframe signal for {ticker}.\n\n"
        f"{tf_lines}\n\n"
        f"Overall: {result.alignment} — {result.alignment_type} timeframes agree.\n"
        f"Current price: ${result.price:.2f}\n\n"
        f"Be specific about the timeframe confluence and what it implies. "
        f"Use plain language. No markdown, no bullet points."
    )

    try:
        response = client.messages.create(
            model=HAIKU,
            max_tokens=180,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        print(f"[mtf] narrative failed for {ticker}: {exc}", file=sys.stderr)
        return (
            f"{ticker} shows {result.alignment} alignment across "
            f"{result.alignment_type} timeframes at ${result.price:.2f}."
        )


# ── Teams output formatter ─────────────────────────────────────────────────────

def format_mtf_markdown(result: MTFResult) -> str:
    """
    Build the Teams-ready markdown response for one MTFResult.

    Structure:
        ## MTF TICKER — Multi-Timeframe Analysis
        **Overall: BULLISH 2/3 aligned** (or No signal: 1/3)
        | Timeframe | Score | Direction | RSI | Trend |
        ...
        > Haiku narrative (only when signal fired)
    """
    if result.signal_fired:
        emoji = "🟢" if result.alignment == "bullish" else "🔴"
        verdict = f"{emoji} **{result.alignment.upper()} — {result.alignment_type} aligned**"
    else:
        verdict = f"⚪ No MTF signal ({result.alignment_type} aligned)"

    price_str = f"${result.price:.2f}" if result.price > 0 else "N/A"

    lines = [
        f"## 📊 MTF {result.ticker} — Multi-Timeframe Analysis",
        f"{verdict} | Price: {price_str}",
        "",
        "| Timeframe | Score | Direction | RSI | Key driver |",
        "|-----------|-------|-----------|-----|------------|",
    ]

    for tf in result.timeframes:
        if tf.error:
            lines.append(
                f"| {tf.label} | — | ⚠️ Error | — | {tf.error[:40]} |"
            )
        else:
            dir_emoji = "🟢" if tf.direction == "bullish" else "🔴" if tf.direction == "bearish" else "🟡"
            # top component by abs score
            top = max(tf.components.items(), key=lambda kv: abs(kv[1]["score"]), default=None)
            driver = top[1]["reason"] if top else "—"
            lines.append(
                f"| {tf.label} | {tf.score:+.1f} | {dir_emoji} {tf.direction.capitalize()} "
                f"| {tf.rsi:.1f} | {driver} |"
            )

    if result.signal_fired and result.narrative:
        lines += ["", f"> {result.narrative}"]

    return "\n".join(lines)


# ── Public entry points ────────────────────────────────────────────────────────

def analyze_ticker_mtf(ticker: str) -> MTFResult:
    """
    Full 3-timeframe MTF analysis for a single ticker.

    Fetches all 3 timeframes concurrently via asyncio.gather() +
    ThreadPoolExecutor (3 workers — one per timeframe).
    Calls Haiku for a narrative only when the signal fires.

    Never raises — data errors are captured per-timeframe.
    """
    ticker   = ticker.upper()
    executor = ThreadPoolExecutor(max_workers=3)  # exactly one thread per timeframe

    try:
        timeframes = asyncio.run(_fetch_all_timeframes(ticker, executor))
    finally:
        executor.shutdown(wait=False)

    # Current price from the daily timeframe (most reliable for price)
    daily_tf   = next((tf for tf in timeframes if tf.name == "daily"), None)
    price = 0.0
    if daily_tf and not daily_tf.error:
        try:
            p = get_current_price(ticker)
            price = float(p.get("current_price") or 0.0)
        except Exception:
            pass

    alignment, aligned_count = _compute_alignment(timeframes)
    alignment_type = f"{aligned_count}/{len(TIMEFRAMES)}"
    signal_fired   = aligned_count >= MTF_ALIGNMENT_THRESHOLD

    # Build a provisional result for the narrative call
    result = MTFResult(
        ticker=ticker, price=price,
        timeframes=timeframes,
        alignment=alignment, aligned_count=aligned_count,
        alignment_type=alignment_type,
        signal_fired=signal_fired,
        narrative="", summary="",
    )

    narrative = _generate_narrative(ticker, result) if signal_fired else ""

    if signal_fired:
        emoji   = "🟢" if alignment == "bullish" else "🔴"
        summary = (
            f"{emoji} {ticker} {alignment.upper()} — {alignment_type} timeframes aligned"
        )
    else:
        summary = f"⚪ {ticker} — no MTF signal ({alignment_type} aligned)"

    return MTFResult(
        ticker=ticker, price=price,
        timeframes=timeframes,
        alignment=alignment, aligned_count=aligned_count,
        alignment_type=alignment_type,
        signal_fired=signal_fired,
        narrative=narrative, summary=summary,
    )


def analyze_tickers_mtf(tickers: list[str]) -> list[MTFResult]:
    """
    MTF analysis for multiple tickers in parallel.

    Each ticker gets one worker thread; within that thread all 3 timeframe
    fetches run sequentially (avoids nested executor complexity).

    return_exceptions=True — a bad ticker never aborts the batch.
    """
    if not tickers:
        return []

    async def _gather_tickers(executor: ThreadPoolExecutor) -> list[MTFResult]:
        loop = asyncio.get_running_loop()
        results = await asyncio.gather(
            *[loop.run_in_executor(executor, analyze_ticker_mtf, t) for t in tickers],
            return_exceptions=True,
        )
        output: list[MTFResult] = []
        for ticker, result in zip(tickers, results):
            if isinstance(result, MTFResult):
                output.append(result)
            else:
                print(f"[mtf] error for {ticker}: {result}", file=sys.stderr)
        return output

    n_workers = min(MTF_MAX_WORKERS, len(tickers))
    executor  = ThreadPoolExecutor(max_workers=n_workers)
    try:
        return asyncio.run(_gather_tickers(executor))
    finally:
        executor.shutdown(wait=False)


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL"]

    for ticker in tickers:
        result = analyze_ticker_mtf(ticker)
        print(f"\n{'─' * 60}")
        print(format_mtf_markdown(result))
        print()
        print(f"  signal_fired={result.signal_fired}  "
              f"aligned_count={result.aligned_count}  "
              f"alignment={result.alignment}")
        for tf in result.timeframes:
            status = f"score={tf.score:+.2f} rsi={tf.rsi:.1f}"
            if tf.error:
                status = f"ERROR: {tf.error}"
            print(f"  [{tf.label:8s}] {tf.direction:8s}  {status}")
