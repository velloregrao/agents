"""
IPO Watch — scheduler integration.

Contains the job function that APScheduler calls and a run_now() helper
for manual/test triggers from the API.

IPO signals run every 4 hours, 24/7 (not market-hours-gated — S-1 filings
and IPO news drop any time, and proxy stock momentum is computed from
recent closes that don't change during off-hours).

The job:
  1. Loads all active profiles
  2. Calls compute_signal() for each
  3. Persists state to ipo_watch_state via set_ipo_state()
  4. Dispatches alerts for any threshold crossings (deduped)
  5. Logs a one-line summary
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

# Ensure both ipo-watch/ and stock-analysis-agent/src are importable
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
for _p in (
    str(_AGENTS_ROOT / "ipo-watch"),
    str(_AGENTS_ROOT / "stock-analysis-agent" / "src"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def run_ipo_watch_scan(user_id: str = "ipo-watch") -> dict:
    """
    Run a full IPO Watch scan: signals → state persistence → alert dispatch.

    Args:
        user_id: alert_queue recipient (default "ipo-watch"; Teams bot fans out
                 to the right conversation via conversation_refs lookup)

    Returns:
        {
          "run_at": str,
          "profiles_checked": int,
          "results": list[dict],        # one per active profile
          "alerts_dispatched": list[dict],
        }
    """
    from signals import run_all_signals
    from alerts import dispatch_all

    run_at = datetime.now(timezone.utc).isoformat()
    print(f"[ipo-watch] scan started at {run_at}", flush=True)

    results = run_all_signals()         # signals + state persistence
    dispatches = dispatch_all(results, user_id=user_id)

    fired = [d for d in dispatches if len(d["dispatched"]) > 1]  # >1 → beyond just "log"
    print(
        f"[ipo-watch] scan complete — {len(results)} profile(s) checked, "
        f"{len(fired)} alert(s) dispatched",
        flush=True,
    )

    return {
        "run_at":             run_at,
        "profiles_checked":   len(results),
        "results":            results,
        "alerts_dispatched":  dispatches,
    }


def get_current_status() -> list[dict]:
    """
    Return the latest persisted state for all active profiles without
    re-running signals (no API calls, no yfinance, instant).

    Returns a list of dicts from ipo_watch_state merged with profile metadata.
    """
    from profiles import load_all_active_profiles

    try:
        from stock_agent.memory import get_ipo_state
    except ImportError:
        def get_ipo_state(ticker):
            return {}

    rows = []
    for profile in load_all_active_profiles():
        ticker = profile["ticker"]
        state  = get_ipo_state(ticker)
        rows.append({
            "ticker":                  ticker,
            "company_name":            profile.get("company_name"),
            "estimated_listing_window": profile.get("estimated_listing_window"),
            "proxy_stocks":            profile.get("proxy_stocks", []),
            "last_score":              state.get("last_score"),
            "last_signal":             state.get("last_signal"),
            "last_checked":            state.get("last_checked"),
            "breakdown":               json.loads(state["last_analysis"])
                                       if state.get("last_analysis") else None,
        })
    rows.sort(key=lambda r: (r["last_score"] or 0), reverse=True)
    return rows


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IPO Watch scheduler integration")
    parser.add_argument(
        "--status", action="store_true",
        help="Show current persisted state (no API calls)",
    )
    args = parser.parse_args()

    if args.status:
        rows = get_current_status()
        for r in rows:
            score = f"{r['last_score']:.1f}" if r["last_score"] is not None else "N/A"
            print(
                f"{r['ticker']:6s}  score={score:5s}  signal={str(r['last_signal']):8s}  "
                f"checked={str(r['last_checked'])[:16]}"
            )
    else:
        result = run_ipo_watch_scan()
        print(json.dumps(result, indent=2, default=str))
