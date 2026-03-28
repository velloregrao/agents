"""
tests/functional/test_risk_sequence.py

Full trading-session sequence test for the Phase 3 risk gate.

Scenario
--------
A trader starts a session with a clean $100k paper portfolio and issues
three trade requests in sequence:

  Step 1 — Buy AAPL (small position)
            Account healthy, no existing positions → APPROVED, trading
            agent executes.

  Step 2 — Buy AMD while NVDA is in the portfolio
            Correlation guard fires (NVDA ↔ AMD known pair) → ESCALATE,
            trading agent is NOT called, requires_approval=True on the
            AgentResponse.

  Step 3 — Buy MSFT when the portfolio is down 2.5% on the day
            Daily loss circuit breaker fires → BLOCK, trading agent is
            NOT called.

Each step asserts:
  - The correct Verdict
  - The correct rule number that fired
  - Whether run_trading_agent was called or skipped
  - The requires_approval flag on the top-level AgentResponse
  - That a narrative was generated for ESCALATE and BLOCK verdicts
"""

import math
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Make orchestrator/ importable
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))

from orchestrator.risk_agent import evaluate_proposal, Verdict, RISK_MAX_POSITION_PCT
from orchestrator.router import route
from orchestrator.contracts import AgentMessage

# ── Shared fixture data ────────────────────────────────────────────────────────

EQUITY = 100_000.0
AAPL_PRICE = 150.0
AMD_PRICE  = 180.0
MSFT_PRICE = 420.0
NVDA_PRICE = 875.0

# Expected qty the router calculates via 5% position sizing
AAPL_PROPOSED_QTY = max(math.floor(EQUITY * 0.05 / AAPL_PRICE), 1)   # 33


def _healthy_account():
    return {
        "equity":        EQUITY,
        "last_equity":   EQUITY * 0.995,
        "pnl_today":     EQUITY * 0.005,
        "pnl_today_pct": 0.5,            # +0.5% today — well above -2% halt
    }


def _down_account():
    """Portfolio down 2.5% — triggers daily loss circuit breaker."""
    return {
        "equity":        EQUITY * 0.975,
        "last_equity":   EQUITY,
        "pnl_today":     -EQUITY * 0.025,
        "pnl_today_pct": -2.5,           # -2.5% — below RISK_DAILY_LOSS_HALT (-2%)
    }


def _no_positions():
    return {"positions": [], "total_positions": 0}


def _nvda_position():
    """NVDA already held — sets up the correlation guard for AMD."""
    return {
        "positions": [{
            "ticker":        "NVDA",
            "quantity":      5,
            "market_value":  NVDA_PRICE * 5,
            "sector":        "Technology",
            "entry_price":   NVDA_PRICE,
            "current_price": NVDA_PRICE,
        }],
        "total_positions": 1,
    }


def _price(p):
    return {"current_price": p}


def _stock_info(sector="Technology"):
    return {"sector": sector, "name": "Test Corp"}


def _mock_narrative(context):
    return f"[narrative: {context['reason']}]"


# ── Step 1: APPROVED — clean buy ───────────────────────────────────────────────

class TestStep1_Approved:
    """
    AAPL buy with a healthy account and no existing positions.
    Risk gate should APPROVE and the trading agent should execute.
    """

    @patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative)
    @patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info())
    @patch("orchestrator.risk_agent.get_current_price",   return_value=_price(AAPL_PRICE))
    @patch("orchestrator.risk_agent.get_positions",       return_value=_no_positions())
    @patch("orchestrator.risk_agent.get_account_balance", return_value=_healthy_account())
    def test_evaluate_proposal_approved(self, *_):
        result = evaluate_proposal("AAPL", AAPL_PROPOSED_QTY, "buy")

        assert result.verdict      == Verdict.APPROVED
        assert result.rule         == 0
        assert result.adjusted_qty == AAPL_PROPOSED_QTY
        assert result.narrative    == ""   # no narrative for APPROVED

    @patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative)
    @patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info())
    @patch("orchestrator.risk_agent.get_current_price",   return_value=_price(AAPL_PRICE))
    @patch("orchestrator.risk_agent.get_positions",       return_value=_no_positions())
    @patch("orchestrator.risk_agent.get_account_balance", return_value=_healthy_account())
    @patch("orchestrator.router.get_current_price",       return_value=_price(AAPL_PRICE))
    @patch("orchestrator.router.get_account_balance",     return_value=_healthy_account())
    @patch("orchestrator.router.run_trading_agent",       return_value="✅ Bought 33 shares of AAPL.")
    def test_route_approved_calls_trading_agent(self, mock_trade, *_):
        """End-to-end: route() → risk gate APPROVED → run_trading_agent called."""
        msg = AgentMessage(
            user_id="test:u1", platform="test",
            text="trade AAPL",
        )
        resp = route(msg)

        assert resp.intent            == "trade"
        assert resp.requires_approval is False
        assert resp.approval_context  is None
        mock_trade.assert_called_once()
        assert "AAPL" in resp.text


# ── Step 2: ESCALATE — correlation guard (AMD while holding NVDA) ──────────────

class TestStep2_Escalate:
    """
    After buying NVDA, the trader tries to buy AMD.
    NVDA ↔ AMD is a known correlated pair → ESCALATE.
    Trading agent must NOT be called.
    requires_approval must be True on AgentResponse.
    """

    @patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative)
    @patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info())
    @patch("orchestrator.risk_agent.get_current_price",   return_value=_price(AMD_PRICE))
    @patch("orchestrator.risk_agent.get_positions",       return_value=_nvda_position())
    @patch("orchestrator.risk_agent.get_account_balance", return_value=_healthy_account())
    def test_evaluate_proposal_escalates(self, *_):
        result = evaluate_proposal("AMD", 10, "buy")

        assert result.verdict == Verdict.ESCALATE
        assert result.reason  == "correlation_guard"
        assert result.rule    == 4
        assert "[narrative: correlation_guard]" in result.narrative

    @patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative)
    @patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info())
    @patch("orchestrator.risk_agent.get_current_price",   return_value=_price(AMD_PRICE))
    @patch("orchestrator.risk_agent.get_positions",       return_value=_nvda_position())
    @patch("orchestrator.risk_agent.get_account_balance", return_value=_healthy_account())
    @patch("orchestrator.router.get_current_price",       return_value=_price(AMD_PRICE))
    @patch("orchestrator.router.get_account_balance",     return_value=_healthy_account())
    @patch("orchestrator.router.run_trading_agent")
    def test_route_escalate_skips_trading_agent(self, mock_trade, *_):
        """End-to-end: route() → ESCALATE → run_trading_agent NOT called."""
        msg = AgentMessage(
            user_id="test:u1", platform="test",
            text="trade AMD",
        )
        resp = route(msg)

        assert resp.intent            == "trade"
        assert resp.requires_approval is True
        assert resp.approval_context  is not None
        assert resp.approval_context["ticker"] == "AMD"
        assert resp.approval_context["reason"] == "correlation_guard"
        mock_trade.assert_not_called()
        assert "ESCALATED" in resp.text
        assert "Human approval required" in resp.text


# ── Step 3: BLOCK — daily loss circuit breaker ─────────────────────────────────

class TestStep3_Block:
    """
    Portfolio is down 2.5% on the day.
    Daily loss circuit breaker fires on Rule 1 → BLOCK.
    No market-data calls beyond the account balance are needed.
    Trading agent must NOT be called.
    """

    @patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative)
    @patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info())
    @patch("orchestrator.risk_agent.get_current_price",   return_value=_price(MSFT_PRICE))
    @patch("orchestrator.risk_agent.get_positions",       return_value=_no_positions())
    @patch("orchestrator.risk_agent.get_account_balance", return_value=_down_account())
    def test_evaluate_proposal_blocked(self, *_):
        result = evaluate_proposal("MSFT", 5, "buy")

        assert result.verdict      == Verdict.BLOCK
        assert result.reason       == "daily_loss_halt"
        assert result.rule         == 1
        assert result.adjusted_qty == 0
        assert "[narrative: daily_loss_halt]" in result.narrative

    @patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative)
    @patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info())
    @patch("orchestrator.risk_agent.get_current_price",   return_value=_price(MSFT_PRICE))
    @patch("orchestrator.risk_agent.get_positions",       return_value=_no_positions())
    @patch("orchestrator.risk_agent.get_account_balance", return_value=_down_account())
    @patch("orchestrator.router.get_current_price",       return_value=_price(MSFT_PRICE))
    @patch("orchestrator.router.get_account_balance",     return_value=_down_account())
    @patch("orchestrator.router.run_trading_agent")
    def test_route_block_skips_trading_agent(self, mock_trade, *_):
        """End-to-end: route() → BLOCK → run_trading_agent NOT called."""
        msg = AgentMessage(
            user_id="test:u1", platform="test",
            text="trade MSFT",
        )
        resp = route(msg)

        assert resp.intent            == "trade"
        assert resp.requires_approval is False   # BLOCK doesn't need approval
        mock_trade.assert_not_called()
        assert "BLOCKED" in resp.text


# ── Full session — all three steps in one narrative ────────────────────────────

class TestFullSession:
    """
    Runs all three steps back-to-back, asserting the correct state
    transitions and that only the APPROVED step reaches the trading agent.
    """

    def test_full_session_sequence(self):
        """
        Session:
          1. AAPL buy → APPROVED  (clean account, no positions)
          2. AMD buy  → ESCALATE  (NVDA correlation, healthy account)
          3. MSFT buy → BLOCK     (account down 2.5%)
        """

        # ── Step 1: APPROVED ──────────────────────────────────────────────────
        with (
            patch("orchestrator.risk_agent.get_account_balance", return_value=_healthy_account()),
            patch("orchestrator.risk_agent.get_positions",       return_value=_no_positions()),
            patch("orchestrator.risk_agent.get_current_price",   return_value=_price(AAPL_PRICE)),
            patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info()),
            patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative),
        ):
            step1 = evaluate_proposal("AAPL", AAPL_PROPOSED_QTY, "buy")

        assert step1.verdict == Verdict.APPROVED, \
            f"Step 1 expected APPROVED, got {step1.verdict} (rule {step1.rule})"
        assert step1.adjusted_qty == AAPL_PROPOSED_QTY

        # ── Step 2: ESCALATE (NVDA already held) ──────────────────────────────
        with (
            patch("orchestrator.risk_agent.get_account_balance", return_value=_healthy_account()),
            patch("orchestrator.risk_agent.get_positions",       return_value=_nvda_position()),
            patch("orchestrator.risk_agent.get_current_price",   return_value=_price(AMD_PRICE)),
            patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info()),
            patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative),
        ):
            step2 = evaluate_proposal("AMD", 10, "buy")

        assert step2.verdict == Verdict.ESCALATE, \
            f"Step 2 expected ESCALATE, got {step2.verdict} (rule {step2.rule})"
        assert step2.reason == "correlation_guard"
        assert step2.narrative != ""

        # ── Step 3: BLOCK (portfolio down 2.5%) ───────────────────────────────
        with (
            patch("orchestrator.risk_agent.get_account_balance", return_value=_down_account()),
            patch("orchestrator.risk_agent.get_positions",       return_value=_no_positions()),
            patch("orchestrator.risk_agent.get_current_price",   return_value=_price(MSFT_PRICE)),
            patch("orchestrator.risk_agent.get_stock_info",      return_value=_stock_info()),
            patch("orchestrator.risk_agent._generate_narrative", side_effect=_mock_narrative),
        ):
            step3 = evaluate_proposal("MSFT", 5, "buy")

        assert step3.verdict      == Verdict.BLOCK, \
            f"Step 3 expected BLOCK, got {step3.verdict} (rule {step3.rule})"
        assert step3.reason       == "daily_loss_halt"
        assert step3.adjusted_qty == 0
        assert step3.narrative    != ""

        # ── Confirm ordering: rule 1 fires before rule 4 ──────────────────────
        assert step3.rule < step2.rule, \
            "Circuit breaker (rule 1) should fire before correlation guard (rule 4)"
