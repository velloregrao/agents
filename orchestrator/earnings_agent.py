"""
orchestrator/earnings_agent.py

Earnings intelligence pipeline (Phase 6).

Flow per ticker:
    1. Fetch earnings calendar via yfinance (date, EPS/revenue estimates)
    2. Pull analyst ratings and price target from yfinance info
    3. Run 2 Brave Search news queries for pre-earnings sentiment
    4. Claude Sonnet synthesises a thesis + sentiment verdict
    5. Return EarningsAlert dataclasses, one per ticker with an upcoming event

Concurrency: all per-ticker I/O (yfinance, Brave, Sonnet) runs in a
ThreadPoolExecutor via asyncio.gather() — same pattern as watchlist_monitor.py.
A 5-ticker scan runs in ~3-4 s instead of ~15 s sequentially.

Deduplication: run_full_earnings_scan() scores each unique ticker once across
all watchlists and fans the result back to every user who watches it.

Public API:
    scan_user_earnings(user_id, tickers, days_ahead=7) -> list[EarningsAlert]
    run_full_earnings_scan(queue_alerts=True) -> dict[str, list[EarningsAlert]]
"""

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

import anthropic
import yfinance as yf
from stock_agent.watchlist import get_all_active_watchlists

# ── Config ────────────────────────────────────────────────────────────────────

EARNINGS_LOOKAHEAD_DAYS = int(os.getenv("EARNINGS_LOOKAHEAD_DAYS", "7"))
_MAX_WORKERS            = int(os.getenv("EARNINGS_MAX_WORKERS", "8"))
SONNET = "claude-sonnet-4-6"

# ── Contract ──────────────────────────────────────────────────────────────────

@dataclass
class EarningsAlert:
    """
    One upcoming earnings event for a watchlist ticker.

    Passed to the alert queue so the Teams bot can push an Adaptive Card
    before the earnings date.

    Fields:
        ticker            Stock symbol
        user_id           Canonical user the watchlist belongs to
        earnings_date     ISO date string e.g. "2026-04-01"
        days_until        Calendar days from today to earnings date
        eps_estimate      Consensus EPS estimate (dollars per share)
        eps_low           Low end of analyst EPS range
        eps_high          High end of analyst EPS range
        revenue_estimate  Consensus revenue estimate (dollars, full scale)
        analyst_rating    recommendationKey from yfinance: buy/hold/sell/N/A
        analyst_target    Mean analyst price target
        thesis            Sonnet-generated 3-4 sentence pre-earnings thesis
        summary           One-line summary for the Teams card header
        sentiment         Overall direction: "bullish" | "bearish" | "neutral"
    """
    ticker:           str
    user_id:          str
    earnings_date:    str
    days_until:       int
    eps_estimate:     float | None
    eps_low:          float | None
    eps_high:         float | None
    revenue_estimate: float | None
    analyst_rating:   str | None
    analyst_target:   float | None
    thesis:           str
    summary:          str
    sentiment:        str


# ── Data helpers ──────────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (f != f) else f   # reject NaN
    except (TypeError, ValueError):
        return None


def fetch_earnings_calendar(ticker: str, days_ahead: int = EARNINGS_LOOKAHEAD_DAYS) -> dict | None:
    """
    Return earnings calendar data if an event falls within *days_ahead* days.

    Handles both dict and DataFrame returns from yfinance (varies by version).
    Returns None if no upcoming event is found or if data is unavailable.
    """
    try:
        t   = yf.Ticker(ticker)
        cal = t.calendar
    except Exception:
        return None

    if cal is None:
        return None

    # yfinance ≥ 0.2.x returns a dict; older versions return a DataFrame
    if hasattr(cal, "to_dict"):
        raw: dict = {}
        try:
            # DataFrame: each column has one value per row
            for col in cal.columns:
                vals = cal[col].dropna().tolist()
                raw[col] = vals[0] if vals else None
        except Exception:
            return None
        cal = raw

    if not isinstance(cal, dict) or not cal:
        return None

    # Extract earnings date — may be a list, Timestamp, or string
    raw_date = cal.get("Earnings Date")
    if raw_date is None:
        return None
    if isinstance(raw_date, (list, tuple)):
        raw_date = raw_date[0] if raw_date else None
    if raw_date is None:
        return None

    try:
        if isinstance(raw_date, datetime):
            # datetime.datetime subclasses date — call .date() to get a pure date
            earnings_date = raw_date.date()
        elif isinstance(raw_date, date):
            # plain datetime.date — use as-is (yfinance ≥ 0.2.x returns these)
            earnings_date = raw_date
        elif hasattr(raw_date, "date"):
            # pd.Timestamp or other objects with a .date() method
            earnings_date = raw_date.date()
        elif isinstance(raw_date, str):
            earnings_date = date.fromisoformat(raw_date[:10])
        else:
            earnings_date = date.fromtimestamp(float(raw_date))
    except Exception:
        return None

    today      = date.today()
    days_until = (earnings_date - today).days

    if days_until < 0 or days_until > days_ahead:
        return None

    return {
        "earnings_date":    earnings_date.isoformat(),
        "days_until":       days_until,
        "eps_estimate":     _safe_float(cal.get("Earnings Average")),
        "eps_low":          _safe_float(cal.get("Earnings Low")),
        "eps_high":         _safe_float(cal.get("Earnings High")),
        "revenue_estimate": _safe_float(cal.get("Revenue Average")),
    }


def _get_analyst_data(ticker: str) -> dict:
    """
    Pull analyst consensus and price target from yfinance.info.
    Returns an empty dict on any error — caller handles missing fields.
    """
    try:
        info    = yf.Ticker(ticker).info
        current = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")) or 0
        target  = _safe_float(info.get("targetMeanPrice")) or 0
        upside  = round((target - current) / current * 100, 1) if current > 0 and target > 0 else None
        return {
            "recommendation": info.get("recommendationKey", "N/A"),
            "target_mean":    _safe_float(info.get("targetMeanPrice")),
            "analyst_count":  info.get("numberOfAnalystOpinions"),
            "upside_pct":     upside,
        }
    except Exception:
        return {}


def _brave_search(query: str, count: int = 5) -> list[dict]:
    """
    Run a Brave news search.  Returns [] when BRAVE_API_KEY is not set or
    on any network/parse error — never raises.
    """
    import requests

    api_key = os.getenv("BRAVE_API_KEY", "")
    if not api_key:
        return []

    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/news/search",
            headers={
                "Accept":           "application/json",
                "Accept-Encoding":  "gzip",
                "X-Subscription-Token": api_key,
            },
            params={"q": query, "count": count, "freshness": "pw"},
            timeout=10,
        )
        data = resp.json()
        return [
            {
                "title":       item.get("title", ""),
                "description": item.get("description", ""),
                "source":      item.get("source", ""),
            }
            for item in data.get("results", [])
        ]
    except Exception:
        return []


# ── Sonnet thesis generator ────────────────────────────────────────────────────

def _generate_thesis(
    ticker:        str,
    cal_data:      dict,
    brave_results: list[dict],
    analyst:       dict,
) -> tuple[str, str, str]:
    """
    Ask Claude Sonnet to synthesise a pre-earnings thesis from calendar,
    analyst, and news data.

    Returns (thesis, summary, sentiment).
    Falls back to a safe stub if the API call fails or returns invalid JSON.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    rev = cal_data.get("revenue_estimate")
    rev_str = f"${rev / 1e9:.1f}B" if rev else "N/A"

    prompt = f"""You are a pre-earnings intelligence analyst. Analyse the upcoming earnings event for {ticker}.

EARNINGS DATA:
- Date: {cal_data['earnings_date']} ({cal_data['days_until']} days away)
- EPS Estimate: {cal_data.get('eps_estimate')} (range: {cal_data.get('eps_low')} – {cal_data.get('eps_high')})
- Revenue Estimate: {rev_str}

ANALYST CONSENSUS:
- Recommendation: {analyst.get('recommendation', 'N/A')}
- Mean Price Target: ${analyst.get('target_mean', 'N/A')} ({analyst.get('upside_pct', 'N/A')}% upside)
- Number of Analysts: {analyst.get('analyst_count', 'N/A')}

RECENT NEWS (past week):
{json.dumps(brave_results[:8], indent=2)}

Generate a concise pre-earnings thesis. Respond with valid JSON only — no markdown, no explanation:
{{
  "thesis": "3-4 sentence analysis covering consensus expectations, key catalysts or risks, and why sentiment leans a particular direction",
  "sentiment": "bullish" | "bearish" | "neutral",
  "summary": "One-line summary under 90 characters for a Teams alert card"
}}"""

    try:
        response = client.messages.create(
            model=SONNET,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        parsed = json.loads(raw)
        return (
            parsed.get("thesis", ""),
            parsed.get("summary", f"Earnings in {cal_data['days_until']} days"),
            parsed.get("sentiment", "neutral"),
        )
    except Exception as exc:
        print(f"[earnings] thesis generation failed for {ticker}: {exc}", file=sys.stderr)
        eps = cal_data.get("eps_estimate")
        eps_str = f"${eps:.2f}" if eps else "N/A"
        return (
            f"{ticker} reports earnings in {cal_data['days_until']} days. "
            f"Consensus EPS estimate: {eps_str}. Revenue estimate: {rev_str}.",
            f"Earnings in {cal_data['days_until']} days — {eps_str} EPS est.",
            "neutral",
        )


# ── Async concurrency layer ────────────────────────────────────────────────────

def _process_one_ticker(ticker: str, days_ahead: int) -> EarningsAlert | None:
    """
    Full pipeline for a single ticker: calendar → analyst → Brave → Sonnet.

    Sync/blocking — designed to be run inside a ThreadPoolExecutor so the
    asyncio event loop stays free while network I/O is in flight.

    Returns an EarningsAlert (user_id="") or None if no upcoming event.
    """
    cal = fetch_earnings_calendar(ticker, days_ahead)
    if cal is None:
        return None

    analyst      = _get_analyst_data(ticker)
    brave_results = (
        _brave_search(f"{ticker} earnings estimate analyst expectations", count=5)
        + _brave_search(f"{ticker} stock earnings preview outlook", count=5)
    )
    thesis, summary, sentiment = _generate_thesis(ticker, cal, brave_results, analyst)

    return EarningsAlert(
        ticker=ticker,
        user_id="",               # filled in per-user during fan-out
        earnings_date=cal["earnings_date"],
        days_until=cal["days_until"],
        eps_estimate=cal.get("eps_estimate"),
        eps_low=cal.get("eps_low"),
        eps_high=cal.get("eps_high"),
        revenue_estimate=cal.get("revenue_estimate"),
        analyst_rating=analyst.get("recommendation"),
        analyst_target=analyst.get("target_mean"),
        thesis=thesis,
        summary=summary,
        sentiment=sentiment,
    )


async def _process_one_async(
    ticker:    str,
    days_ahead: int,
    executor:  ThreadPoolExecutor,
) -> EarningsAlert | None:
    """Run _process_one_ticker() in the thread pool without blocking the loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _process_one_ticker, ticker, days_ahead)


async def _process_all_async(
    tickers:    list[str],
    days_ahead: int,
    executor:   ThreadPoolExecutor,
) -> dict[str, EarningsAlert | None]:
    """
    Process all tickers concurrently.

    return_exceptions=True — a network timeout or parse error on one ticker
    never aborts the whole batch; that ticker gets None in the cache.
    """
    results = await asyncio.gather(
        *[_process_one_async(t, days_ahead, executor) for t in tickers],
        return_exceptions=True,
    )

    cache: dict[str, EarningsAlert | None] = {}
    for ticker, result in zip(tickers, results):
        if isinstance(result, Exception):
            print(f"[earnings] error for {ticker}: {result}", file=sys.stderr)
            cache[ticker] = None
        else:
            cache[ticker] = result  # EarningsAlert or None (no upcoming event)

    return cache


# ── Public entry points ────────────────────────────────────────────────────────

def scan_user_earnings(
    user_id:    str,
    tickers:    list[str],
    days_ahead: int = EARNINGS_LOOKAHEAD_DAYS,
) -> list[EarningsAlert]:
    """
    On-demand earnings scan for one user's ticker list.

    All tickers are processed concurrently via asyncio.gather() +
    ThreadPoolExecutor. Skips tickers with no event within *days_ahead* days.
    Never raises — per-ticker errors are logged and skipped.

    Used by:
      - POST /earnings/scan (on-demand via Teams or API)
      - router.py earnings intent handler
    """
    if not tickers:
        return []

    executor = ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(tickers)))
    try:
        cache = asyncio.run(
            _process_all_async(tickers, days_ahead, executor)
        )
    finally:
        executor.shutdown(wait=False)

    return [
        replace(alert, user_id=user_id)
        for alert in cache.values()
        if alert is not None
    ]


def run_full_earnings_scan(
    queue_alerts: bool = True,
    days_ahead:   int  = EARNINGS_LOOKAHEAD_DAYS,
) -> dict[str, list[EarningsAlert]]:
    """
    Full earnings scan across all active watchlists.

    Deduplicates tickers — if AAPL is watched by 10 users the Brave + Sonnet
    calls run once and the result is fanned out to all 10.

    All unique tickers are processed concurrently via asyncio.gather() +
    ThreadPoolExecutor, then results are fanned back to users synchronously.

    When queue_alerts=True (default), each EarningsAlert is persisted to the
    alert_queue table so the Teams bot can push it proactively.

    Called by:
      - APScheduler daily cron at 08:00 ET (Mon–Fri)
      - POST /earnings/scan/run (manual trigger)
    """
    watchlists = get_all_active_watchlists()
    if not watchlists:
        return {}

    # Score each unique ticker once — concurrently
    unique_tickers = list({t for tickers in watchlists.values() for t in tickers})
    n_workers      = min(_MAX_WORKERS, len(unique_tickers))
    executor       = ThreadPoolExecutor(max_workers=n_workers)
    try:
        ticker_cache = asyncio.run(
            _process_all_async(unique_tickers, days_ahead, executor)
        )
    finally:
        executor.shutdown(wait=False)

    # Fan results back to users (sync — just dict lookups + optional DB write)
    results: dict[str, list[EarningsAlert]] = {}

    for user_id, tickers in watchlists.items():
        user_alerts: list[EarningsAlert] = []

        for ticker in tickers:
            proto = ticker_cache.get(ticker)
            if proto is None:
                continue

            alert = replace(proto, user_id=user_id)
            user_alerts.append(alert)

            if queue_alerts:
                try:
                    from orchestrator.alert_manager import queue_earnings_alert
                    queue_earnings_alert(user_id, alert)
                except Exception as exc:
                    print(
                        f"[earnings] failed to queue alert {ticker} for {user_id}: {exc}",
                        file=sys.stderr,
                    )

        if user_alerts:
            results[user_id] = user_alerts

    return results
