"""
Unit tests for orchestrator/risk_agent.py

All Alpaca and market-data calls are mocked so tests run offline.
Each test exercises one verdict path.
"""

import math
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Make orchestrator/ importable from the test runner
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))

from orchestrator.risk_agent import (
    evaluate_proposal,
    Verdict,
    RISK_MAX_POSITION_PCT,
    RISK_MAX_SECTOR_CONC_PCT,
    RISK_DAILY_LOSS_HALT,
)

# ── Shared mock helpers ────────────────────────────────────────────────────────

def _account(equity=100_000, pnl_today_pct=0.5):
    """Healthy account with small positive P&L."""
    return {
        "equity":        equity,
        "last_equity":   equity - equity * pnl_today_pct / 100,
        "pnl_today":     equity * pnl_today_pct / 100,
        "pnl_today_pct": pnl_today_pct,
    }

def _price(p=150.0):
    return {"current_price": p, "ticker": "AAPL"}

def _positions(holdings=None):
    return {"positions": holdings or [], "total_positions": len(holdings or [])}

def _stock_info(sector="Technology"):
    return {"sector": sector, "name": "Test Corp"}

def _no_narrative(context):
    return f"Risk narrative for {context['reason']}"


# ── Test 1: APPROVED — small position, healthy portfolio ──────────────────────

@patch("orchestrator.risk_agent._generate_narrative", side_effect=_no_narrative)
@patch("orchestrator.risk_agent.get_stock_info",    return_value=_stock_info())
@patch("orchestrator.risk_agent.get_current_price", return_value=_price(150.0))
@patch("orchestrator.risk_agent.get_positions",     return_value=_positions())
@patch("orchestrator.risk_agent.get_account_balance", return_value=_account())
def test_approved(mock_bal, mock_pos, mock_price, mock_info, mock_narr):
    """10 shares @ $150 = $1,500 = 1.5% of $100k equity — well under 5% limit."""
    result = evaluate_proposal("AAPL", 10, "buy")
    assert result.verdict      == Verdict.APPROVED
    assert result.adjusted_qty == 10
    assert result.rule         == 0


# ── Test 2: RESIZE — position too large, auto-reduced ─────────────────────────

@patch("orchestrator.risk_agent._generate_narrative", side_effect=_no_narrative)
@patch("orchestrator.risk_agent.get_stock_info",    return_value=_stock_info())
@patch("orchestrator.risk_agent.get_current_price", return_value=_price(150.0))
@patch("orchestrator.risk_agent.get_positions",     return_value=_positions())
@patch("orchestrator.risk_agent.get_account_balance", return_value=_account())
def test_resize(mock_bal, mock_pos, mock_price, mock_info, mock_narr):
    """500 shares @ $150 = $75,000 = 75% of equity — must be resized to 5%."""
    result = evaluate_proposal("AAPL", 500, "buy")
    assert result.verdict == Verdict.RESIZE
    assert result.rule    == 2
    # Adjusted qty must fit within 5% of equity
    max_allowed = math.floor(100_000 * RISK_MAX_POSITION_PCT / 150.0)
    assert result.adjusted_qty == max_allowed
    assert result.adjusted_qty * 150.0 <= 100_000 * RISK_MAX_POSITION_PCT


# ── Test 3: BLOCK — daily loss circuit breaker ────────────────────────────────

@patch("orchestrator.risk_agent._generate_narrative", side_effect=_no_narrative)
@patch("orchestrator.risk_agent.get_stock_info",    return_value=_stock_info())
@patch("orchestrator.risk_agent.get_current_price", return_value=_price(150.0))
@patch("orchestrator.risk_agent.get_positions",     return_value=_positions())
@patch("orchestrator.risk_agent.get_account_balance",
       return_value=_account(equity=100_000, pnl_today_pct=-2.5))
def test_block_daily_loss(mock_bal, mock_pos, mock_price, mock_info, mock_narr):
    """Portfolio down 2.5% today — exceeds -2% halt threshold → BLOCK."""
    result = evaluate_proposal("AAPL", 10, "buy")
    assert result.verdict      == Verdict.BLOCK
    assert result.reason       == "daily_loss_halt"
    assert result.rule         == 1
    assert result.adjusted_qty == 0


# ── Test 4: ESCALATE — sector concentration ───────────────────────────────────

@patch("orchestrator.risk_agent._generate_narrative", side_effect=_no_narrative)
@patch("orchestrator.risk_agent.get_stock_info",    return_value=_stock_info("Technology"))
@patch("orchestrator.risk_agent.get_current_price", return_value=_price(150.0))
@patch("orchestrator.risk_agent.get_positions", return_value=_positions([
    # Already hold $22,000 in Technology sector (22% of $100k equity)
    {"ticker": "MSFT", "market_value": 22_000, "sector": "Technology"},
]))
@patch("orchestrator.risk_agent.get_account_balance", return_value=_account())
def test_escalate_sector_concentration(mock_bal, mock_pos, mock_price, mock_info, mock_narr):
    """
    Existing Technology exposure $22k (22%).
    Adding 30 shares AAPL @ $150 = $4,500 → total $26,500 = 26.5% > 25% limit.
    """
    result = evaluate_proposal("AAPL", 30, "buy")
    assert result.verdict == Verdict.ESCALATE
    assert result.reason  == "sector_concentration"
    assert result.rule    == 3


# ── Test 5: ESCALATE — correlation guard ──────────────────────────────────────

@patch("orchestrator.risk_agent._generate_narrative", side_effect=_no_narrative)
@patch("orchestrator.risk_agent.get_stock_info",    return_value=_stock_info("Technology"))
@patch("orchestrator.risk_agent.get_current_price", return_value=_price(900.0))
@patch("orchestrator.risk_agent.get_positions", return_value=_positions([
    {"ticker": "NVDA", "market_value": 3_000, "sector": "Technology"},
]))
@patch("orchestrator.risk_agent.get_account_balance", return_value=_account())
def test_escalate_correlation_guard(mock_bal, mock_pos, mock_price, mock_info, mock_narr):
    """Proposing AMD while holding NVDA — known correlated pair → ESCALATE."""
    result = evaluate_proposal("AMD", 5, "buy")
    assert result.verdict == Verdict.ESCALATE
    assert result.reason  == "correlation_guard"
    assert result.rule    == 4


# ── Test 6: SELL always approved ──────────────────────────────────────────────

@patch("orchestrator.risk_agent.get_account_balance")
@patch("orchestrator.risk_agent.get_positions")
@patch("orchestrator.risk_agent.get_current_price")
@patch("orchestrator.risk_agent.get_stock_info")
def test_sell_always_approved(mock_info, mock_price, mock_pos, mock_bal):
    """SELL orders bypass all rules — closing a position reduces risk."""
    result = evaluate_proposal("AAPL", 10, "sell")
    assert result.verdict      == Verdict.APPROVED
    assert result.reason       == "sell_always_approved"
    assert result.adjusted_qty == 10
    # No market data calls should have been made
    mock_bal.assert_not_called()
    mock_pos.assert_not_called()
    mock_price.assert_not_called()
    mock_info.assert_not_called()
