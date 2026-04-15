"""
IPO Watch — signals engine.

Computes a composite readiness score (0–100) for each watched IPO candidate
by combining:
  1. Proxy stock momentum   (up to 20 pts) — weighted average of 1-week % change
                                             across proxy stocks
  2. News sentiment         (up to 10 pts) — Claude Haiku grades Brave Search results
  3. S-1 filed keyword      (up to 40 pts) — detected in news headlines/snippets
  4. Roadshow announced     (up to 30 pts) — detected in news headlines/snippets

Maps score to a signal label:
  WATCH   — score ≥ WATCH threshold   (default 30)  → monitor closely
  PREPARE — score ≥ PREPARE threshold (default 55)  → line up capital
  ACT     — score ≥ ACT threshold     (default 75)  → deploy position
  RISK    — score drops below RISK threshold (20)   → re-evaluate thesis
  HOLD    — score between WATCH and PREPARE         → status quo

All I/O is synchronous to keep it compatible with the existing FastAPI thread model.
"""

import os
import re
import json
import requests
import anthropic
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

_brave_key = os.getenv("BRAVE_API_KEY", "")
_anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

HAIKU = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Keyword patterns that trigger hard signal score boosts
# ---------------------------------------------------------------------------

_S1_PATTERNS = re.compile(
    r"\b(s-1|s1 filing|sec filing|filed.*ipo|ipo.*filing|form s-1|registration statement)\b",
    re.IGNORECASE,
)

_ROADSHOW_PATTERNS = re.compile(
    r"\b(roadshow|road show|ipo roadshow|investor roadshow|pricing.*ipo|ipo.*pricing|going public)\b",
    re.IGNORECASE,
)

_NEGATIVE_PATTERNS = re.compile(
    r"\b(delayed|cancelled|canceled|pulled|withdrawn|postponed|no ipo|not going public|abandoned)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 1. Proxy stock momentum (0–20 pts)
# ---------------------------------------------------------------------------

def _proxy_momentum_score(proxy_stocks: list[str]) -> tuple[float, dict]:
    """
    Fetch 1-week price change for each proxy stock and compute a weighted score.

    Returns:
        (score 0–20, details dict)
    """
    if not proxy_stocks:
        return 0.0, {}

    changes = {}
    for ticker in proxy_stocks:
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) >= 2:
                pct = (hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100
                changes[ticker] = round(float(pct), 2)
            else:
                changes[ticker] = None
        except Exception as e:
            changes[ticker] = None
            print(f"[signals] proxy fetch failed for {ticker}: {e}")

    valid = [v for v in changes.values() if v is not None]
    if not valid:
        return 0.0, changes

    avg_change = sum(valid) / len(valid)

    # +5% avg → full 20 pts; -5% avg → 0 pts; linear in between
    score = max(0.0, min(20.0, (avg_change + 5.0) / 10.0 * 20.0))
    return round(score, 2), changes


# ---------------------------------------------------------------------------
# 2. Brave Search — fetch news snippets for IPO candidate
# ---------------------------------------------------------------------------

def _fetch_brave_snippets(queries: list[str], max_per_query: int = 3) -> list[str]:
    """
    Run up to 3 Brave news searches and collect headline + description snippets.
    Returns a flat list of text snippets (title + description).
    """
    if not _brave_key:
        return []

    snippets: list[str] = []
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": _brave_key,
    }

    for query in queries[:3]:  # cap at 3 queries to limit API cost
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/news/search",
                headers=headers,
                params={"q": query, "count": max_per_query, "freshness": "pm"},  # past month
                timeout=10,
            )
            data = resp.json()
            for item in data.get("results", []):
                title = item.get("title", "")
                desc = item.get("description", "")
                if title or desc:
                    snippets.append(f"{title}. {desc}".strip())
        except Exception as e:
            print(f"[signals] Brave search failed for '{query}': {e}")

    return snippets


# ---------------------------------------------------------------------------
# 3. Keyword detection — S-1 filed / roadshow (0–40 pts / 0–30 pts)
# ---------------------------------------------------------------------------

def _detect_keyword_signals(snippets: list[str]) -> tuple[float, float, bool]:
    """
    Scan snippets for S-1 filing and roadshow keywords.
    Also check for negative (cancellation) signals.

    Returns:
        (s1_score 0–40, roadshow_score 0–30, is_negative bool)
    """
    combined = " ".join(snippets)

    is_negative = bool(_NEGATIVE_PATTERNS.search(combined))
    s1_found = bool(_S1_PATTERNS.search(combined))
    roadshow_found = bool(_ROADSHOW_PATTERNS.search(combined))

    s1_score = 40.0 if s1_found else 0.0
    roadshow_score = 30.0 if roadshow_found else 0.0

    # If both detected simultaneously, don't double-count — cap at 70
    return s1_score, roadshow_score, is_negative


# ---------------------------------------------------------------------------
# 4. News sentiment scoring via Claude Haiku (0–10 pts)
# ---------------------------------------------------------------------------

def _sentiment_score(company_name: str, snippets: list[str]) -> tuple[float, str]:
    """
    Ask Claude Haiku to grade IPO likelihood sentiment from news snippets.

    Returns:
        (score 0–10, sentiment_label)
    """
    if not snippets:
        return 5.0, "neutral"  # no news → neutral baseline

    snippet_block = "\n".join(f"- {s}" for s in snippets[:10])
    prompt = f"""You are analyzing news about {company_name}'s potential IPO.

News snippets:
{snippet_block}

Rate the IPO likelihood sentiment on a scale of 0–10:
- 0–3: Negative (delays, denials, cancelled, far from IPO)
- 4–6: Neutral (speculative, uncertain, no new developments)
- 7–10: Positive (S-1 filed, roadshow, imminent listing, strong signals)

Respond with ONLY a JSON object:
{{"score": <number 0-10>, "label": "<negative|neutral|positive>", "reason": "<one sentence>"}}"""

    try:
        resp = _anthropic_client.messages.create(
            model=HAIKU,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Extract JSON even if there's surrounding text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            score = max(0.0, min(10.0, float(data.get("score", 5))))
            label = data.get("label", "neutral")
            return round(score, 1), label
    except Exception as e:
        print(f"[signals] sentiment scoring failed: {e}")

    return 5.0, "neutral"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_signal(profile: dict) -> dict:
    """
    Compute a composite readiness score and signal label for one IPO profile.

    Args:
        profile: Dict loaded from load_profile() or load_all_active_profiles()

    Returns:
        {
          "ticker": str,
          "company_name": str,
          "score": float (0–100),
          "signal": "WATCH" | "PREPARE" | "ACT" | "RISK" | "HOLD" | "INACTIVE",
          "breakdown": {
              "proxy_momentum": float,
              "news_sentiment": float,
              "s1_detected": bool,
              "roadshow_detected": bool,
              "s1_score": float,
              "roadshow_score": float,
              "is_negative": bool,
              "proxy_changes": dict,
              "sentiment_label": str,
              "sentiment_reason": str (optional),
          },
          "snippets_used": int,
          "checked_at": str (ISO 8601),
        }
    """
    ticker = profile.get("ticker", "UNKNOWN")
    company_name = profile.get("company_name", ticker)
    proxy_stocks = profile.get("proxy_stocks", [])
    queries = profile.get("brave_search_queries", [])
    thresholds = profile.get("alert_thresholds", {
        "WATCH": 30, "PREPARE": 55, "ACT": 75, "RISK": 20
    })

    # --- collect data ---
    proxy_score, proxy_changes = _proxy_momentum_score(proxy_stocks)
    snippets = _fetch_brave_snippets(queries)
    s1_score, roadshow_score, is_negative = _detect_keyword_signals(snippets)
    sentiment_score, sentiment_label = _sentiment_score(company_name, snippets)

    # --- composite ---
    raw_score = proxy_score + sentiment_score + s1_score + roadshow_score
    score = round(min(100.0, raw_score), 1)

    # Negative signals hard-cap score at RISK threshold
    if is_negative:
        score = min(score, thresholds.get("RISK", 20) - 0.1)

    # --- signal label ---
    if score >= thresholds.get("ACT", 75):
        signal = "ACT"
    elif score >= thresholds.get("PREPARE", 55):
        signal = "PREPARE"
    elif score >= thresholds.get("WATCH", 30):
        signal = "WATCH"
    elif score < thresholds.get("RISK", 20):
        signal = "RISK"
    else:
        signal = "HOLD"

    return {
        "ticker": ticker,
        "company_name": company_name,
        "score": score,
        "signal": signal,
        "breakdown": {
            "proxy_momentum": proxy_score,
            "proxy_changes": proxy_changes,
            "news_sentiment": sentiment_score,
            "sentiment_label": sentiment_label,
            "s1_score": s1_score,
            "s1_detected": s1_score > 0,
            "roadshow_score": roadshow_score,
            "roadshow_detected": roadshow_score > 0,
            "is_negative": is_negative,
        },
        "snippets_used": len(snippets),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def run_all_signals() -> list[dict]:
    """
    Run compute_signal() for every active profile and return results sorted by score desc.
    Also persists state to SQLite via set_ipo_state().
    """
    import sys
    from pathlib import Path
    _agents_root = Path(__file__).resolve().parent.parent
    _ipo_watch_path = str(_agents_root / "ipo-watch")
    _src_path = str(_agents_root / "stock-analysis-agent" / "src")
    for p in (_ipo_watch_path, _src_path):
        if p not in sys.path:
            sys.path.insert(0, p)

    from profiles import load_all_active_profiles  # type: ignore
    try:
        from stock_agent.memory import set_ipo_state
    except ImportError:
        set_ipo_state = None  # graceful degradation if memory module not available

    profiles = load_all_active_profiles()
    results = []
    for profile in profiles:
        try:
            result = compute_signal(profile)
            results.append(result)
            if set_ipo_state:
                set_ipo_state(
                    ticker=result["ticker"],
                    score=result["score"],
                    signal=result["signal"],
                    analysis=json.dumps(result["breakdown"]),
                )
        except Exception as e:
            print(f"[signals] compute_signal failed for {profile.get('ticker')}: {e}")

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


if __name__ == "__main__":
    from profiles import load_profile

    import argparse
    parser = argparse.ArgumentParser(description="Run IPO watch signal for a ticker")
    parser.add_argument("ticker", nargs="?", default=None, help="e.g. SPCE")
    args = parser.parse_args()

    if args.ticker:
        p = load_profile(args.ticker)
        result = compute_signal(p)
        print(json.dumps(result, indent=2))
    else:
        results = run_all_signals()
        for r in results:
            bd = r["breakdown"]
            print(
                f"{r['ticker']:6s}  score={r['score']:5.1f}  signal={r['signal']:8s} "
                f"proxy={bd['proxy_momentum']:4.1f}  s1={bd['s1_detected']}  "
                f"roadshow={bd['roadshow_detected']}  sentiment={bd['sentiment_label']}"
            )
