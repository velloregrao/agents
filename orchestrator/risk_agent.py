"""
orchestrator/risk_agent.py

Generator-critic risk gate — runs before every trade execution.

Entry point:
    evaluate_proposal(ticker, proposed_qty, side) -> RiskResult

Four rules (evaluated in order):
    1. Daily loss circuit breaker  — BLOCK  if portfolio down > RISK_DAILY_LOSS_HALT
    2. Position size limit         — RESIZE if new position > RISK_MAX_POSITION_PCT of equity
    3. Sector concentration        — ESCALATE if one sector > RISK_MAX_SECTOR_CONC_PCT of equity
    4. Correlation guard           — ESCALATE if proposed ticker correlated with a held stock

Verdicts:
    APPROVED  → execute with adjusted_qty (may equal proposed_qty)
    RESIZE    → qty auto-reduced to fit position limit; execute with adjusted_qty
    BLOCK     → do not execute; log reason; no Teams card needed
    ESCALATE  → post Teams Adaptive Card; await human approval

Config (all overridable via environment variables):
    RISK_MAX_POSITION_PCT     default 0.05   (5 % of equity per position)
    RISK_MAX_SECTOR_CONC_PCT  default 0.25   (25 % of equity per sector)
    RISK_DAILY_LOSS_HALT      default -0.02  (halt if down 2 % today)
"""

import os
import math
import anthropic
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

import sys
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from stock_agent.alpaca_tools import get_account_balance, get_positions, get_open_orders
from stock_agent.tools import get_stock_info, get_current_price

# ── Model constants ────────────────────────────────────────────────────────────

SONNET = "claude-sonnet-4-6"   # narrative generation — reasoning task
_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Config ────────────────────────────────────────────────────────────────────

RISK_MAX_POSITION_PCT  = float(os.getenv("RISK_MAX_POSITION_PCT",  "0.05"))
RISK_MAX_SECTOR_CONC_PCT = float(os.getenv("RISK_MAX_SECTOR_CONC_PCT", "0.25"))
RISK_DAILY_LOSS_HALT   = float(os.getenv("RISK_DAILY_LOSS_HALT",   "-0.02"))

# ── Known correlated pairs ─────────────────────────────────────────────────────
# If the proposed ticker and a held ticker appear in the same pair, escalate.
# Extend this set as the portfolio grows.

_CORRELATED_PAIRS: list[frozenset[str]] = [
    frozenset({"NVDA", "AMD"}),
    frozenset({"AAPL", "MSFT"}),
    frozenset({"GOOGL", "META"}),
    frozenset({"JPM",  "BAC"}),
    frozenset({"XOM",  "CVX"}),
    frozenset({"AMZN", "SHOP"}),
    frozenset({"TSLA", "RIVN"}),
    frozenset({"V",    "MA"}),
]

# ── Contracts ─────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    APPROVED  = "APPROVED"
    RESIZE    = "RESIZE"
    BLOCK     = "BLOCK"
    ESCALATE  = "ESCALATE"


@dataclass
class RiskResult:
    """
    Result returned by evaluate_proposal().

    Fields:
        verdict       One of Verdict.{APPROVED,RESIZE,BLOCK,ESCALATE}
        adjusted_qty  Quantity to execute (may be lower than proposed after RESIZE)
        reason        Short machine-readable reason code, e.g. "daily_loss_halt"
        narrative     Human-readable Sonnet-generated explanation (populated for
                      BLOCK and ESCALATE; empty string for APPROVED/RESIZE)
        rule          Which rule triggered (1-4), or 0 if APPROVED
    """
    verdict:      Verdict
    adjusted_qty: int
    reason:       str
    narrative:    str = ""
    rule:         int = 0


# ── Narrative generator ────────────────────────────────────────────────────────

def _generate_narrative(context: dict) -> str:
    """
    Use Claude Sonnet to produce a plain-English risk explanation.
    Called only for BLOCK and ESCALATE verdicts.

    context keys: ticker, side, proposed_qty, adjusted_qty, verdict,
                  reason, rule, equity, detail (rule-specific data)
    """
    prompt = f"""You are a risk manager for a stock trading portfolio.

A trade proposal has been flagged by the automated risk system.

Trade: {context['side'].upper()} {context['proposed_qty']} shares of {context['ticker']}
Verdict: {context['verdict']}
Rule triggered: Rule {context['rule']} — {context['reason']}
Portfolio equity: ${context['equity']:,.2f}
Detail: {context['detail']}

Write a clear, concise 2-3 sentence explanation of why this trade was {context['verdict'].lower()}ed.
Be specific about the numbers. Use plain language a non-technical trader would understand.
Do not use markdown. Do not start with "I"."""

    try:
        response = _client.messages.create(
            model=SONNET,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Risk check triggered ({context['reason']}): {context['detail']}"


# ── Rule 1: Daily loss circuit breaker ────────────────────────────────────────

def _check_daily_loss(account: dict) -> RiskResult | None:
    """
    BLOCK all trading if today's portfolio loss exceeds RISK_DAILY_LOSS_HALT.
    Protects against runaway losses on a bad day.
    """
    if account.get("error"):
        return None  # can't check — allow through, log elsewhere

    pnl_pct = account.get("pnl_today_pct", 0) / 100  # convert from % to decimal
    if pnl_pct <= RISK_DAILY_LOSS_HALT:
        return RiskResult(
            verdict=Verdict.BLOCK,
            adjusted_qty=0,
            reason="daily_loss_halt",
            rule=1,
        )
    return None


# ── Rule 2: Position size limit ────────────────────────────────────────────────

def _check_position_size(
    ticker: str,
    proposed_qty: int,
    current_price: float,
    equity: float,
) -> RiskResult | None:
    """
    Resize if the proposed position value exceeds RISK_MAX_POSITION_PCT of equity.
    Returns a RESIZE result with the adjusted qty, or None if within limits.
    If the max affordable qty is 0, returns BLOCK instead.
    """
    proposed_value = proposed_qty * current_price
    max_value      = equity * RISK_MAX_POSITION_PCT
    max_qty        = math.floor(max_value / current_price) if current_price > 0 else 0

    if proposed_value > max_value:
        if max_qty <= 0:
            return RiskResult(
                verdict=Verdict.BLOCK,
                adjusted_qty=0,
                reason="position_size_too_small",
                rule=2,
            )
        return RiskResult(
            verdict=Verdict.RESIZE,
            adjusted_qty=max_qty,
            reason="position_size_limit",
            rule=2,
        )
    return None


# ── Rule 3: Sector concentration ──────────────────────────────────────────────

def _check_sector_concentration(
    ticker: str,
    proposed_qty: int,
    current_price: float,
    equity: float,
    positions: list[dict],
    ticker_sector: str,
) -> RiskResult | None:
    """
    ESCALATE if adding this position would push a single GICS sector above
    RISK_MAX_SECTOR_CONC_PCT of total equity.
    """
    if not ticker_sector or ticker_sector == "N/A":
        return None  # can't check sector — allow through

    # Sum current market value in the same sector
    existing_sector_value = sum(
        p["market_value"]
        for p in positions
        if p.get("sector") == ticker_sector
    )

    proposed_value      = proposed_qty * current_price
    new_sector_value    = existing_sector_value + proposed_value
    new_sector_pct      = new_sector_value / equity if equity > 0 else 0

    if new_sector_pct > RISK_MAX_SECTOR_CONC_PCT:
        return RiskResult(
            verdict=Verdict.ESCALATE,
            adjusted_qty=proposed_qty,
            reason="sector_concentration",
            rule=3,
        )
    return None


# ── Rule 4: Correlation guard ──────────────────────────────────────────────────

def _check_correlation(ticker: str, held_tickers: list[str]) -> RiskResult | None:
    """
    ESCALATE if the proposed ticker is in a known correlated pair with any
    currently held stock. Avoids doubling up on correlated risk.
    """
    for pair in _CORRELATED_PAIRS:
        if ticker in pair:
            correlated = pair - {ticker}
            overlap = correlated & set(held_tickers)
            if overlap:
                return RiskResult(
                    verdict=Verdict.ESCALATE,
                    adjusted_qty=0,
                    reason="correlation_guard",
                    rule=4,
                )
    return None


# ── Public entry point ─────────────────────────────────────────────────────────

def evaluate_proposal(ticker: str, proposed_qty: int, side: str) -> RiskResult:
    """
    Evaluate a trade proposal against all 4 risk rules.

    Args:
        ticker:       Stock symbol, e.g. "NVDA"
        proposed_qty: Number of shares the trading agent wants to buy/sell
        side:         "buy" or "sell"

    Returns:
        RiskResult with verdict, adjusted_qty, reason, and narrative.

    Rule evaluation is skipped for SELL orders — closing positions is
    always allowed (reduces risk rather than adding it).
    """
    ticker = ticker.upper()

    # SELL orders bypass all rules — closing a position reduces risk
    if side.lower() == "sell":
        return RiskResult(
            verdict=Verdict.APPROVED,
            adjusted_qty=proposed_qty,
            reason="sell_always_approved",
        )

    # ── Fetch market data ──────────────────────────────────────────────────────
    account       = get_account_balance()
    pos_data      = get_positions()
    open_ord_data = get_open_orders()
    price_data    = get_current_price(ticker)
    stock_info    = get_stock_info(ticker)

    equity        = account.get("equity", 0) if not account.get("error") else 0
    positions     = pos_data.get("positions", [])
    current_price = price_data.get("current_price", 0)
    ticker_sector = stock_info.get("sector", "N/A")

    # Combine filled positions + pending open orders so the correlation guard
    # fires even when an after-hours buy hasn't settled into a position yet.
    open_order_tickers = [o["ticker"] for o in open_ord_data.get("open_orders", [])]
    held_tickers       = list({p["ticker"] for p in positions} | set(open_order_tickers))

    # Attach sector to each position for rule 3 (best-effort — may be missing)
    # In Phase 4 we'll persist sector in the DB; for now we enrich on the fly
    # (sector data for held positions is not fetched here to keep latency low —
    # we only compare the proposed ticker's sector against position sectors
    # if they happen to have been stored already)

    # ── Rule 1 ────────────────────────────────────────────────────────────────
    result = _check_daily_loss(account)
    if result:
        result.narrative = _generate_narrative({
            "ticker": ticker, "side": side,
            "proposed_qty": proposed_qty, "adjusted_qty": 0,
            "verdict": result.verdict, "reason": result.reason, "rule": 1,
            "equity": equity,
            "detail": (
                f"Portfolio is down {account.get('pnl_today_pct', 0):.2f}% today "
                f"(${account.get('pnl_today', 0):,.2f}). "
                f"Halt threshold: {RISK_DAILY_LOSS_HALT * 100:.1f}%."
            ),
        })
        return result

    # ── Rule 2 ────────────────────────────────────────────────────────────────
    result = _check_position_size(ticker, proposed_qty, current_price, equity)
    if result:
        if result.verdict == Verdict.RESIZE:
            # Re-run rule 2 with the adjusted qty — confirm it now passes
            recheck = _check_position_size(
                ticker, result.adjusted_qty, current_price, equity
            )
            if recheck:
                # Still over limit after resize (shouldn't happen) → BLOCK
                result.verdict = Verdict.BLOCK
                result.reason  = "resize_still_over_limit"
            result.narrative = _generate_narrative({
                "ticker": ticker, "side": side,
                "proposed_qty": proposed_qty,
                "adjusted_qty": result.adjusted_qty,
                "verdict": result.verdict, "reason": result.reason, "rule": 2,
                "equity": equity,
                "detail": (
                    f"Proposed {proposed_qty} shares @ ${current_price:.2f} = "
                    f"${proposed_qty * current_price:,.2f} "
                    f"({proposed_qty * current_price / equity * 100:.1f}% of equity). "
                    f"Max allowed: {RISK_MAX_POSITION_PCT * 100:.0f}% = "
                    f"${equity * RISK_MAX_POSITION_PCT:,.2f}. "
                    f"Adjusted to {result.adjusted_qty} shares."
                ),
            })
            return result
        else:
            # BLOCK (max_qty == 0)
            result.narrative = _generate_narrative({
                "ticker": ticker, "side": side,
                "proposed_qty": proposed_qty, "adjusted_qty": 0,
                "verdict": result.verdict, "reason": result.reason, "rule": 2,
                "equity": equity,
                "detail": (
                    f"Current price ${current_price:.2f} exceeds the entire "
                    f"position limit of ${equity * RISK_MAX_POSITION_PCT:,.2f}."
                ),
            })
            return result

    # ── Rule 3 ────────────────────────────────────────────────────────────────
    result = _check_sector_concentration(
        ticker, proposed_qty, current_price, equity, positions, ticker_sector
    )
    if result:
        existing_sector_value = sum(
            p["market_value"] for p in positions
            if p.get("sector") == ticker_sector
        )
        result.narrative = _generate_narrative({
            "ticker": ticker, "side": side,
            "proposed_qty": proposed_qty, "adjusted_qty": proposed_qty,
            "verdict": result.verdict, "reason": result.reason, "rule": 3,
            "equity": equity,
            "detail": (
                f"Sector: {ticker_sector}. "
                f"Existing {ticker_sector} exposure: ${existing_sector_value:,.2f}. "
                f"Proposed addition: ${proposed_qty * current_price:,.2f}. "
                f"Combined: {(existing_sector_value + proposed_qty * current_price) / equity * 100:.1f}% "
                f"of equity vs {RISK_MAX_SECTOR_CONC_PCT * 100:.0f}% limit."
            ),
        })
        return result

    # ── Rule 4 ────────────────────────────────────────────────────────────────
    result = _check_correlation(ticker, held_tickers)
    if result:
        correlated_held = [
            h for h in held_tickers
            if any(ticker in pair and h in pair for pair in _CORRELATED_PAIRS)
        ]
        result.adjusted_qty = proposed_qty  # preserve original qty for human review
        result.narrative = _generate_narrative({
            "ticker": ticker, "side": side,
            "proposed_qty": proposed_qty, "adjusted_qty": proposed_qty,
            "verdict": result.verdict, "reason": result.reason, "rule": 4,
            "equity": equity,
            "detail": (
                f"{ticker} is in a known correlated pair with "
                f"{', '.join(correlated_held)} which you currently hold. "
                f"Adding both amplifies directional risk."
            ),
        })
        return result

    # ── All rules passed ───────────────────────────────────────────────────────
    return RiskResult(
        verdict=Verdict.APPROVED,
        adjusted_qty=proposed_qty,
        reason="all_rules_passed",
    )


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("Testing risk_agent.evaluate_proposal()...\n")

    test_cases = [
        ("AAPL", 10, "buy"),
        ("NVDA", 1000, "buy"),   # likely resize
        ("AAPL", 1, "sell"),     # sell always approved
    ]

    for ticker, qty, side in test_cases:
        print(f"--- evaluate_proposal({ticker!r}, {qty}, {side!r}) ---")
        result = evaluate_proposal(ticker, qty, side)
        print(f"  verdict:      {result.verdict}")
        print(f"  adjusted_qty: {result.adjusted_qty}")
        print(f"  reason:       {result.reason}")
        if result.narrative:
            print(f"  narrative:    {result.narrative}")
        print()
