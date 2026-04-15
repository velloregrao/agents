"""
IPO Watch — profile loader.

Profiles are JSON files stored in ipo-watch/ipo_profiles/<TICKER>.json.
Each profile describes an upcoming IPO candidate, its proxy stocks,
search queries, and scoring thresholds.
"""

import json
import os
from pathlib import Path

_PROFILES_DIR = Path(__file__).parent / "ipo_profiles"


def load_profile(ticker: str) -> dict:
    """
    Load a single IPO profile by ticker symbol.

    Args:
        ticker: Stock ticker (e.g. "SPCE", "OAII", "ANTHR")

    Returns:
        Profile dict, or raises FileNotFoundError if not found.
    """
    path = _PROFILES_DIR / f"{ticker.upper()}.json"
    if not path.exists():
        raise FileNotFoundError(f"No IPO profile found for {ticker.upper()} at {path}")
    with path.open() as f:
        return json.load(f)


def load_all_active_profiles() -> list[dict]:
    """
    Load all profiles where active=true.

    Returns:
        List of profile dicts, sorted by ticker.
    """
    profiles = []
    if not _PROFILES_DIR.exists():
        return profiles

    for path in sorted(_PROFILES_DIR.glob("*.json")):
        try:
            with path.open() as f:
                profile = json.load(f)
            if profile.get("active", False):
                profiles.append(profile)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[profiles] Skipping {path.name}: {e}")

    return profiles


def list_profiles() -> list[dict]:
    """
    Return a summary list of all profiles (active and inactive).

    Returns:
        List of dicts with ticker, company_name, active, estimated_listing_window.
    """
    summaries = []
    if not _PROFILES_DIR.exists():
        return summaries

    for path in sorted(_PROFILES_DIR.glob("*.json")):
        try:
            with path.open() as f:
                p = json.load(f)
            summaries.append({
                "ticker": p.get("ticker"),
                "company_name": p.get("company_name"),
                "active": p.get("active", False),
                "estimated_listing_window": p.get("estimated_listing_window"),
                "estimated_valuation_usd": p.get("estimated_valuation_usd"),
                "proxy_stocks": p.get("proxy_stocks", []),
            })
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[profiles] Skipping {path.name}: {e}")

    return summaries


if __name__ == "__main__":
    import json as _json

    print("=== Active profiles ===")
    for p in load_all_active_profiles():
        val = p.get("estimated_valuation_usd", 0)
        val_str = f"${val / 1e12:.2f}T" if val >= 1e12 else f"${val / 1e9:.0f}B"
        print(f"  {p['ticker']:6s} — {p['company_name']:20s} {val_str:8s}  {p['estimated_listing_window']}")

    print("\n=== All profiles ===")
    print(_json.dumps(list_profiles(), indent=2))
