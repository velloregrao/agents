"""
scripts/seed_test_trades.py

Synthetic trade seeder for testing vector DB phases.

Inserts 30 realistic closed paper trades into the SQLite trading_memory.db,
covering diverse tickers, RSI conditions, sectors, hold periods, and mixed
outcomes (winners + losers).

Run:
    python scripts/seed_test_trades.py
    python scripts/seed_test_trades.py --dry-run      # preview without writing
    python scripts/seed_test_trades.py --clear        # wipe existing trades first

The data is designed to make semantic similarity non-trivial:
  - Oversold (RSI < 30) buys that worked and ones that didn't
  - Momentum trades (RSI 55-65) with strong thesis
  - Overbought entries (RSI > 70) that reversed
  - Cross-sector spread: Tech, Consumer Discretionary, Communication
  - Hold periods from 1 day to 21 days
  - P&L range: -6.2% to +14.1%
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from stock_agent.memory import DB_PATH, initialize_db

# ── Synthetic trade data ───────────────────────────────────────────────────────
# Each dict maps directly to the trades table schema.
# entry_date is expressed as days-ago from today for reproducibility.

_BASE = datetime.now()

def _date(days_ago: int) -> str:
    return (_BASE - timedelta(days=days_ago)).strftime("%Y-%m-%d")

SYNTHETIC_TRADES: list[dict] = [

    # ── AAPL — Technology ────────────────────────────────────────────────────
    {
        "ticker": "AAPL", "side": "BUY", "sector": "Technology",
        "quantity": 10, "entry_price": 172.50, "exit_price": 188.40,
        "entry_date": _date(92), "exit_date": _date(78), "hold_days": 14,
        "pnl": 159.00, "pnl_pct": 9.22,
        "entry_rsi": 27.4, "entry_vix": 18.2,
        "signal_score": 0.82, "momentum_score": 0.74,
        "reasoning": "RSI deeply oversold at 27 following post-earnings selloff. EMA-20 curl upward. Strong iPhone demand in China quarter. High conviction oversold bounce.",
        "thesis_text": "Oversold RSI with bullish EMA crossover. Apple earnings beat expectations. Technical and fundamental alignment.",
        "outcome_notes": "Clean breakout above 200-day MA on day 8. Exited near resistance at $188.",
    },
    {
        "ticker": "AAPL", "side": "BUY", "sector": "Technology",
        "quantity": 8, "entry_price": 191.20, "exit_price": 187.60,
        "entry_date": _date(60), "exit_date": _date(57), "hold_days": 3,
        "pnl": -28.80, "pnl_pct": -1.88,
        "entry_rsi": 68.5, "entry_vix": 22.1,
        "signal_score": 0.42, "momentum_score": 0.55,
        "reasoning": "Momentum continuation trade following WWDC announcement. RSI elevated but sentiment very positive. Entered on breakout.",
        "thesis_text": "WWDC product announcement expected to drive continued buying. High-risk momentum entry.",
        "outcome_notes": "Market-wide tech selloff next session. Cut loss quickly at -2% stop.",
    },
    {
        "ticker": "AAPL", "side": "BUY", "sector": "Technology",
        "quantity": 15, "entry_price": 166.80, "exit_price": 175.90,
        "entry_date": _date(120), "exit_date": _date(113), "hold_days": 7,
        "pnl": 136.50, "pnl_pct": 5.46,
        "entry_rsi": 31.2, "entry_vix": 21.5,
        "signal_score": 0.76, "momentum_score": 0.68,
        "reasoning": "Near oversold on RSI with VWAP support holding. Services revenue guidance raised. Risk-reward 3:1.",
        "thesis_text": "RSI approaching oversold, VWAP bounce, positive analyst revision.",
        "outcome_notes": "Steady grind higher. Exited ahead of CPI print.",
    },

    # ── NVDA — Technology ────────────────────────────────────────────────────
    {
        "ticker": "NVDA", "side": "BUY", "sector": "Technology",
        "quantity": 5, "entry_price": 485.00, "exit_price": 552.40,
        "entry_date": _date(85), "exit_date": _date(68), "hold_days": 17,
        "pnl": 337.00, "pnl_pct": 13.92,
        "entry_rsi": 29.8, "entry_vix": 19.4,
        "signal_score": 0.91, "momentum_score": 0.88,
        "reasoning": "RSI at 30 on AI chip demand pullback. Datacenter growth intact. Jensen Huang confirmed Q4 Blackwell ramp. Strong conviction long.",
        "thesis_text": "Deeply oversold on profit taking. Blackwell GPU ramp thesis intact. AI infrastructure build-out continues.",
        "outcome_notes": "Best trade of the quarter. Held through volatile week 1, explosive move week 2-3.",
    },
    {
        "ticker": "NVDA", "side": "BUY", "sector": "Technology",
        "quantity": 4, "entry_price": 520.00, "exit_price": 497.80,
        "entry_date": _date(50), "exit_date": _date(46), "hold_days": 4,
        "pnl": -88.80, "pnl_pct": -4.27,
        "entry_rsi": 72.1, "entry_vix": 24.8,
        "signal_score": 0.35, "momentum_score": 0.48,
        "reasoning": "Chasing momentum after earnings gap. RSI overbought but thought trend would continue.",
        "thesis_text": "Post-earnings momentum continuation. Risky entry at overbought RSI.",
        "outcome_notes": "Entered too late after earnings gap. Profit-taking wave hit hard. Lesson: avoid RSI > 70 entries on gap-ups.",
    },
    {
        "ticker": "NVDA", "side": "BUY", "sector": "Technology",
        "quantity": 6, "entry_price": 468.50, "exit_price": 501.20,
        "entry_date": _date(140), "exit_date": _date(130), "hold_days": 10,
        "pnl": 196.20, "pnl_pct": 6.98,
        "entry_rsi": 33.5, "entry_vix": 20.1,
        "signal_score": 0.80, "momentum_score": 0.77,
        "reasoning": "RSI oversold, EMA bullish crossover confirmed. H100 supply constraints easing per channel checks. Clean setup.",
        "thesis_text": "Oversold with EMA crossover. Supply chain improving for H100.",
        "outcome_notes": "Textbook oversold bounce. Clean entry and exit.",
    },

    # ── MSFT — Technology ────────────────────────────────────────────────────
    {
        "ticker": "MSFT", "side": "BUY", "sector": "Technology",
        "quantity": 8, "entry_price": 378.20, "exit_price": 401.50,
        "entry_date": _date(75), "exit_date": _date(61), "hold_days": 14,
        "pnl": 186.40, "pnl_pct": 6.16,
        "entry_rsi": 38.4, "entry_vix": 17.8,
        "signal_score": 0.72, "momentum_score": 0.65,
        "reasoning": "RSI neutral-low, Copilot AI monetization inflecting. Azure growth reaccelerating per checks. Long-term compounder at reasonable entry.",
        "thesis_text": "Neutral RSI with improving Azure growth trajectory and AI monetization.",
        "outcome_notes": "Steady uptrend. Held through minor vol and exited at target.",
    },
    {
        "ticker": "MSFT", "side": "BUY", "sector": "Technology",
        "quantity": 10, "entry_price": 395.00, "exit_price": 388.30,
        "entry_date": _date(35), "exit_date": _date(32), "hold_days": 3,
        "pnl": -67.00, "pnl_pct": -1.70,
        "entry_rsi": 58.2, "entry_vix": 26.3,
        "signal_score": 0.50, "momentum_score": 0.44,
        "reasoning": "Pre-earnings positioning. Azure expected to beat. RSI neutral, risk defined.",
        "thesis_text": "Pre-earnings long on Azure beat expectations.",
        "outcome_notes": "Azure missed slightly. Sold next morning to avoid further drawdown.",
    },

    # ── AMZN — Consumer Discretionary ────────────────────────────────────────
    {
        "ticker": "AMZN", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 12, "entry_price": 178.40, "exit_price": 199.60,
        "entry_date": _date(100), "exit_date": _date(85), "hold_days": 15,
        "pnl": 254.40, "pnl_pct": 11.88,
        "entry_rsi": 26.8, "entry_vix": 22.6,
        "signal_score": 0.88, "momentum_score": 0.83,
        "reasoning": "RSI deeply oversold at 27 on macro fears. AWS growth structural, Prime membership growing. Bezos trust buying. High conviction.",
        "thesis_text": "Deeply oversold. AWS fundamentals intact. Insider buying signal.",
        "outcome_notes": "Strong recovery rally. AWS re-acceleration confirmed in earnings mid-hold.",
    },
    {
        "ticker": "AMZN", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 10, "entry_price": 192.50, "exit_price": 186.80,
        "entry_date": _date(48), "exit_date": _date(44), "hold_days": 4,
        "pnl": -57.00, "pnl_pct": -2.96,
        "entry_rsi": 64.2, "entry_vix": 28.5,
        "signal_score": 0.44, "momentum_score": 0.52,
        "reasoning": "Holiday spending data positive. RSI elevated but retail catalyst expected. Momentum entry.",
        "thesis_text": "Holiday season momentum play. RSI elevated but catalyst-driven.",
        "outcome_notes": "Broader market risk-off overwhelmed the catalyst. Stopped out.",
    },
    {
        "ticker": "AMZN", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 8, "entry_price": 182.10, "exit_price": 193.40,
        "entry_date": _date(115), "exit_date": _date(108), "hold_days": 7,
        "pnl": 90.40, "pnl_pct": 6.21,
        "entry_rsi": 35.1, "entry_vix": 19.9,
        "signal_score": 0.74, "momentum_score": 0.70,
        "reasoning": "RSI approaching oversold. AWS margins expanding. EMA crossover on daily. Clean risk-reward.",
        "thesis_text": "Near-oversold RSI with EMA crossover and improving AWS margins.",
        "outcome_notes": "Clean trade. Sold into resistance at $193.",
    },

    # ── GOOGL — Communication Services ───────────────────────────────────────
    {
        "ticker": "GOOGL", "side": "BUY", "sector": "Communication Services",
        "quantity": 14, "entry_price": 151.20, "exit_price": 168.90,
        "entry_date": _date(88), "exit_date": _date(74), "hold_days": 14,
        "pnl": 247.80, "pnl_pct": 11.71,
        "entry_rsi": 28.1, "entry_vix": 20.3,
        "signal_score": 0.85, "momentum_score": 0.81,
        "reasoning": "RSI at 28, near 52-week low support. Gemini AI rollout underappreciated. Search ads resilient. Strong oversold setup.",
        "thesis_text": "Deeply oversold with Gemini AI catalyst upcoming. Search market stable.",
        "outcome_notes": "Gemini announcement drove re-rating. Excellent risk-reward outcome.",
    },
    {
        "ticker": "GOOGL", "side": "BUY", "sector": "Communication Services",
        "quantity": 10, "entry_price": 161.40, "exit_price": 156.20,
        "entry_date": _date(42), "exit_date": _date(39), "hold_days": 3,
        "pnl": -52.00, "pnl_pct": -3.22,
        "entry_rsi": 55.8, "entry_vix": 25.1,
        "signal_score": 0.55, "momentum_score": 0.50,
        "reasoning": "Breakout above 20-day MA. YouTube advertising recovery thesis. RSI neutral, momentum setup.",
        "thesis_text": "20-day MA breakout with YouTube ad recovery momentum.",
        "outcome_notes": "False breakout. Macro pressure on ad spend cut the move short.",
    },
    {
        "ticker": "GOOGL", "side": "BUY", "sector": "Communication Services",
        "quantity": 12, "entry_price": 145.60, "exit_price": 155.80,
        "entry_date": _date(135), "exit_date": _date(126), "hold_days": 9,
        "pnl": 122.40, "pnl_pct": 7.00,
        "entry_rsi": 30.5, "entry_vix": 21.0,
        "signal_score": 0.78, "momentum_score": 0.72,
        "reasoning": "RSI just above oversold. Cloud (GCP) growing 28% YoY. YouTube Shorts monetization ramping. Solid entry.",
        "thesis_text": "RSI near oversold. GCP growth and YouTube Shorts monetization improving.",
        "outcome_notes": "Consistent grind higher. GCP beat confirmed during hold.",
    },

    # ── AMD — Technology ─────────────────────────────────────────────────────
    {
        "ticker": "AMD", "side": "BUY", "sector": "Technology",
        "quantity": 18, "entry_price": 158.30, "exit_price": 180.80,
        "entry_date": _date(95), "exit_date": _date(80), "hold_days": 15,
        "pnl": 405.00, "pnl_pct": 14.21,
        "entry_rsi": 25.6, "entry_vix": 23.4,
        "signal_score": 0.92, "momentum_score": 0.89,
        "reasoning": "RSI at 26, most oversold in 6 months. MI300X GPU gaining datacenter share from NVDA. Lisa Su execution track record. Maximum conviction.",
        "thesis_text": "Maximum oversold condition. MI300X GPU share gains accelerating vs Nvidia H100.",
        "outcome_notes": "Best RSI-oversold setup of the year. MI300X demand confirmed by hyperscalers.",
    },
    {
        "ticker": "AMD", "side": "BUY", "sector": "Technology",
        "quantity": 12, "entry_price": 174.50, "exit_price": 168.20,
        "entry_date": _date(38), "exit_date": _date(35), "hold_days": 3,
        "pnl": -75.60, "pnl_pct": -3.61,
        "entry_rsi": 66.8, "entry_vix": 27.2,
        "signal_score": 0.38, "momentum_score": 0.45,
        "reasoning": "Following NVDA momentum. AI sector running hot. RSI elevated but sector bid strong.",
        "thesis_text": "Sector momentum following Nvidia's move. High RSI risk accepted.",
        "outcome_notes": "Correlation with NVDA worked against us. Both sold off on rate fears.",
    },
    {
        "ticker": "AMD", "side": "BUY", "sector": "Technology",
        "quantity": 15, "entry_price": 148.70, "exit_price": 161.40,
        "entry_date": _date(145), "exit_date": _date(135), "hold_days": 10,
        "pnl": 190.50, "pnl_pct": 8.54,
        "entry_rsi": 32.4, "entry_vix": 19.2,
        "signal_score": 0.79, "momentum_score": 0.75,
        "reasoning": "Oversold RSI with EMA bullish divergence. Ryzen market share gains. Datacenter CPU taking share from Intel.",
        "thesis_text": "Oversold with EMA divergence. CPU market share gains from Intel accelerating.",
        "outcome_notes": "Clean recovery. Exited before next earnings to lock in gains.",
    },

    # ── TSLA — Consumer Discretionary ────────────────────────────────────────
    {
        "ticker": "TSLA", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 8, "entry_price": 218.40, "exit_price": 247.60,
        "entry_date": _date(105), "exit_date": _date(92), "hold_days": 13,
        "pnl": 233.60, "pnl_pct": 13.37,
        "entry_rsi": 23.8, "entry_vix": 24.1,
        "signal_score": 0.87, "momentum_score": 0.84,
        "reasoning": "RSI at 24, extreme oversold on delivery miss fears. FSD revenue recognition pending. Cybertruck ramp underestimated. High risk, high reward setup.",
        "thesis_text": "Extreme oversold RSI. FSD monetization and Cybertruck ramp as upcoming catalysts.",
        "outcome_notes": "Massive bounce from oversold. FSD announcement mid-hold turbocharged the move.",
    },
    {
        "ticker": "TSLA", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 6, "entry_price": 251.00, "exit_price": 235.40,
        "entry_date": _date(30), "exit_date": _date(26), "hold_days": 4,
        "pnl": -93.60, "pnl_pct": -6.21,
        "entry_rsi": 73.4, "entry_vix": 29.8,
        "signal_score": 0.30, "momentum_score": 0.38,
        "reasoning": "Momentum continuation after FSD announcement spike. Overbought but sentiment euphoric.",
        "thesis_text": "Momentum continuation on FSD hype. Overbought conditions accepted for high-beta trade.",
        "outcome_notes": "Worst trade of the period. Overbought RSI 73 entry reversed sharply. Clear lesson: never chase at RSI > 70.",
    },
    {
        "ticker": "TSLA", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 10, "entry_price": 204.80, "exit_price": 219.30,
        "entry_date": _date(155), "exit_date": _date(147), "hold_days": 8,
        "pnl": 145.00, "pnl_pct": 7.08,
        "entry_rsi": 29.2, "entry_vix": 22.8,
        "signal_score": 0.83, "momentum_score": 0.78,
        "reasoning": "RSI oversold near support. Model 3 Highland refresh demand strong in Europe. Margin improvement expected.",
        "thesis_text": "Oversold RSI at support. Model 3 refresh driving European demand recovery.",
        "outcome_notes": "Strong recovery. Sold into resistance. Repeatable setup.",
    },

    # ── META — Communication Services ─────────────────────────────────────────
    {
        "ticker": "META", "side": "BUY", "sector": "Communication Services",
        "quantity": 6, "entry_price": 461.20, "exit_price": 508.40,
        "entry_date": _date(80), "exit_date": _date(66), "hold_days": 14,
        "pnl": 283.20, "pnl_pct": 10.23,
        "entry_rsi": 31.8, "entry_vix": 20.7,
        "signal_score": 0.81, "momentum_score": 0.76,
        "reasoning": "RSI near oversold after macro selloff. Threads growing rapidly. Ad revenue inflecting positive. Year of efficiency paying off. Strong FCF.",
        "thesis_text": "Near oversold RSI. Meta's ad efficiency improvements and Threads growth positive.",
        "outcome_notes": "Held through initial volatility. Strong earnings mid-hold confirmed thesis.",
    },
    {
        "ticker": "META", "side": "BUY", "sector": "Communication Services",
        "quantity": 5, "entry_price": 498.00, "exit_price": 479.60,
        "entry_date": _date(22), "exit_date": _date(19), "hold_days": 3,
        "pnl": -92.00, "pnl_pct": -3.69,
        "entry_rsi": 61.4, "entry_vix": 28.9,
        "signal_score": 0.48, "momentum_score": 0.43,
        "reasoning": "Pre-earnings long. Expected strong Q4 ad revenue beat. RSI mid-range, defined risk.",
        "thesis_text": "Pre-earnings long on ad revenue strength expectations.",
        "outcome_notes": "Missed on Reality Labs losses. Guidance light. Cut at open.",
    },

    # ── SMCI — Technology (high-risk) ─────────────────────────────────────────
    {
        "ticker": "SMCI", "side": "BUY", "sector": "Technology",
        "quantity": 10, "entry_price": 72.40, "exit_price": 82.10,
        "entry_date": _date(70), "exit_date": _date(63), "hold_days": 7,
        "pnl": 97.00, "pnl_pct": 13.40,
        "entry_rsi": 28.9, "entry_vix": 21.5,
        "signal_score": 0.84, "momentum_score": 0.80,
        "reasoning": "RSI deeply oversold. AI server demand via Nvidia. Accounting concerns overblown near term. Short squeeze potential.",
        "thesis_text": "Oversold RSI with AI server demand tailwind. Short squeeze setup.",
        "outcome_notes": "Sharp oversold bounce. Exited before accounting risk re-emerged.",
    },

    # ── INTC — Technology (value/recovery) ───────────────────────────────────
    {
        "ticker": "INTC", "side": "BUY", "sector": "Technology",
        "quantity": 30, "entry_price": 21.80, "exit_price": 20.40,
        "entry_date": _date(55), "exit_date": _date(50), "hold_days": 5,
        "pnl": -42.00, "pnl_pct": -6.42,
        "entry_rsi": 36.2, "entry_vix": 26.0,
        "signal_score": 0.40, "momentum_score": 0.35,
        "reasoning": "Value play on depressed Intel. Foundry business potential. RSI low. Contrarian setup.",
        "thesis_text": "Value contrarian play. Intel foundry business option. Low RSI entry.",
        "outcome_notes": "Continued to deteriorate. Foundry delays confirmed. Clear sector loser vs AMD/NVDA.",
    },

    # ── AAPL (1-day scalp) ───────────────────────────────────────────────────
    {
        "ticker": "AAPL", "side": "BUY", "sector": "Technology",
        "quantity": 20, "entry_price": 179.80, "exit_price": 183.10,
        "entry_date": _date(18), "exit_date": _date(17), "hold_days": 1,
        "pnl": 66.00, "pnl_pct": 1.84,
        "entry_rsi": 43.2, "entry_vix": 17.5,
        "signal_score": 0.60, "momentum_score": 0.62,
        "reasoning": "VWAP bounce intraday. Low VIX environment. Quick scalp on support hold. Tight stop.",
        "thesis_text": "Intraday VWAP bounce with low volatility environment. Short-term scalp.",
        "outcome_notes": "Clean 1-day scalp. VWAP held as support as expected.",
    },

    # ── NVDA (post-split small lot) ──────────────────────────────────────────
    {
        "ticker": "NVDA", "side": "BUY", "sector": "Technology",
        "quantity": 20, "entry_price": 118.40, "exit_price": 131.20,
        "entry_date": _date(25), "exit_date": _date(18), "hold_days": 7,
        "pnl": 256.00, "pnl_pct": 10.81,
        "entry_rsi": 30.1, "entry_vix": 20.8,
        "signal_score": 0.86, "momentum_score": 0.85,
        "reasoning": "Post-split NVDA at RSI 30 on AI spending pause fears. Blackwell revenue ramp not priced in. Highest conviction buy of the month.",
        "thesis_text": "Post-split oversold RSI. Blackwell revenue ramp materially underestimated by market.",
        "outcome_notes": "Blackwell demand confirmed by Microsoft and Google capex announcements. Strong move.",
    },

    # ── AMZN (1-day gap fill) ────────────────────────────────────────────────
    {
        "ticker": "AMZN", "side": "BUY", "sector": "Consumer Discretionary",
        "quantity": 10, "entry_price": 186.20, "exit_price": 190.40,
        "entry_date": _date(12), "exit_date": _date(11), "hold_days": 1,
        "pnl": 42.00, "pnl_pct": 2.26,
        "entry_rsi": 45.8, "entry_vix": 18.2,
        "signal_score": 0.62, "momentum_score": 0.60,
        "reasoning": "Morning gap fill setup. Previous day close was $190. RSI neutral. Low VIX, gap closure likely.",
        "thesis_text": "Gap fill trade. Previous resistance at $190 expected to act as magnet.",
        "outcome_notes": "Gap filled by noon. Clean mechanical trade.",
    },

    # ── MSFT (3-day hold) ────────────────────────────────────────────────────
    {
        "ticker": "MSFT", "side": "BUY", "sector": "Technology",
        "quantity": 7, "entry_price": 408.60, "exit_price": 421.30,
        "entry_date": _date(15), "exit_date": _date(12), "hold_days": 3,
        "pnl": 88.90, "pnl_pct": 3.11,
        "entry_rsi": 42.5, "entry_vix": 19.4,
        "signal_score": 0.68, "momentum_score": 0.64,
        "reasoning": "Copilot enterprise adoption accelerating. RSI neutral-low at 42. EMA slope positive. Short-term hold with earnings approaching.",
        "thesis_text": "Copilot enterprise adoption driving upside with neutral RSI entry.",
        "outcome_notes": "Steady 3-day move. Exited before position size risk at earnings.",
    },
]


# ── Seeder logic ──────────────────────────────────────────────────────────────

def _make_order_id(ticker: str, entry_date: str, idx: int) -> str:
    return f"SEED-{ticker}-{entry_date}-{idx:03d}"


def seed_trades(dry_run: bool = False, clear: bool = False, verbose: bool = False) -> dict:
    """
    Insert synthetic trades into the trading_memory.db.

    Args:
        dry_run: If True, print trades without writing to DB.
        clear:   If True, delete all existing trades before seeding.
        verbose: Print each trade as it is inserted.

    Returns:
        {"inserted": int, "skipped": int, "total": int}
    """
    # Ensure tables exist
    initialize_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if clear and not dry_run:
        cur.execute("DELETE FROM trades")
        conn.commit()
        print(f"  Cleared existing trades from {DB_PATH}")

    inserted = 0
    skipped  = 0

    for idx, t in enumerate(SYNTHETIC_TRADES):
        order_id = _make_order_id(t["ticker"], t["entry_date"], idx)

        if dry_run:
            print(
                f"  [{idx+1:02d}] {t['side']:4s} {t['ticker']:5s} | "
                f"RSI={t['entry_rsi']:4.1f} | "
                f"PnL={t['pnl_pct']:+6.2f}% | "
                f"{t['hold_days']:2d}d | "
                f"{t['sector']}"
            )
            inserted += 1
            continue

        try:
            cur.execute("""
                INSERT OR IGNORE INTO trades (
                    order_id, ticker, side, sector,
                    quantity, entry_price, exit_price,
                    entry_date, exit_date, hold_days,
                    pnl, pnl_pct, status,
                    entry_rsi, entry_vix,
                    signal_score, momentum_score,
                    reasoning, thesis_text, outcome_notes,
                    created_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, 'CLOSED',
                    ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    CURRENT_TIMESTAMP
                )
            """, (
                order_id,
                t["ticker"], t["side"], t.get("sector", "Unknown"),
                t["quantity"], t["entry_price"], t["exit_price"],
                t["entry_date"], t["exit_date"], t["hold_days"],
                t["pnl"], t["pnl_pct"],
                t["entry_rsi"], t.get("entry_vix"),
                t.get("signal_score"), t.get("momentum_score"),
                t.get("reasoning"), t.get("thesis_text"), t.get("outcome_notes"),
            ))

            if cur.rowcount == 1:
                inserted += 1
                if verbose:
                    print(
                        f"  ✓ [{idx+1:02d}] {t['side']:4s} {t['ticker']:5s} | "
                        f"RSI={t['entry_rsi']:4.1f} | "
                        f"PnL={t['pnl_pct']:+6.2f}% | "
                        f"{t['hold_days']:2d}d"
                    )
            else:
                skipped += 1
                if verbose:
                    print(f"  – [{idx+1:02d}] {t['ticker']} already exists, skipped")

        except Exception as exc:
            print(f"  ✗ [{idx+1:02d}] {t['ticker']} error: {exc}", file=sys.stderr)
            skipped += 1

    if not dry_run:
        conn.commit()

    conn.close()

    return {"inserted": inserted, "skipped": skipped, "total": len(SYNTHETIC_TRADES)}


# ── Summary stats ─────────────────────────────────────────────────────────────

def print_summary() -> None:
    """Print a breakdown of what's now in the DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as n FROM trades WHERE status='CLOSED'")
    total = cur.fetchone()["n"]

    cur.execute("""
        SELECT ticker, COUNT(*) as n,
               ROUND(AVG(pnl_pct), 2) as avg_pnl,
               ROUND(AVG(entry_rsi), 1) as avg_rsi,
               SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN pnl_pct <= 0 THEN 1 ELSE 0 END) as losses
        FROM trades WHERE status='CLOSED'
        GROUP BY ticker ORDER BY ticker
    """)
    rows = cur.fetchall()

    cur.execute("""
        SELECT
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as total_wins,
            SUM(CASE WHEN pnl_pct <= 0 THEN 1 ELSE 0 END) as total_losses,
            ROUND(AVG(pnl_pct), 2) as avg_pnl,
            ROUND(AVG(entry_rsi), 1) as avg_rsi,
            ROUND(MIN(entry_rsi), 1) as min_rsi,
            ROUND(MAX(entry_rsi), 1) as max_rsi
        FROM trades WHERE status='CLOSED'
    """)
    agg = cur.fetchone()
    conn.close()

    print(f"\n  {'Ticker':<8} {'Trades':>6} {'Wins':>5} {'Losses':>7} {'Avg RSI':>8} {'Avg PnL%':>9}")
    print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*7} {'-'*8} {'-'*9}")
    for r in rows:
        print(
            f"  {r['ticker']:<8} {r['n']:>6} {r['wins']:>5} {r['losses']:>7} "
            f"{r['avg_rsi']:>8} {r['avg_pnl']:>+9.2f}%"
        )
    print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*7} {'-'*8} {'-'*9}")
    print(
        f"  {'TOTAL':<8} {total:>6} {agg['total_wins']:>5} {agg['total_losses']:>7} "
        f"{agg['avg_rsi']:>8} {agg['avg_pnl']:>+9.2f}%"
    )
    print(f"\n  RSI range: {agg['min_rsi']} – {agg['max_rsi']}")
    win_rate = round(agg["total_wins"] / total * 100) if total else 0
    print(f"  Win rate:  {win_rate}%")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed synthetic closed trades into trading_memory.db for vector DB testing."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview trades without writing to DB."
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="Delete all existing trades before seeding (use with caution)."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print each trade as it is inserted."
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Stock Copilot — Synthetic Trade Seeder")
    print("=" * 60)
    print(f"\n  DB path : {DB_PATH}")
    print(f"  Trades  : {len(SYNTHETIC_TRADES)}")
    print(f"  Mode    : {'DRY RUN' if args.dry_run else 'WRITE'}")
    if args.clear and not args.dry_run:
        print("  WARNING : --clear will delete existing trades")
    print()

    if args.dry_run:
        print("Preview (not written):")
    else:
        print("Inserting trades...")

    result = seed_trades(
        dry_run=args.dry_run,
        clear=args.clear,
        verbose=args.verbose or args.dry_run,
    )

    if not args.dry_run:
        print(f"\n  Inserted : {result['inserted']}")
        print(f"  Skipped  : {result['skipped']} (already existed)")
        print(f"  Total    : {result['total']}")
        print("\nDB summary after seeding:")
        print_summary()
        print(f"\n  Next step: python scripts/setup_vector_db.py")
