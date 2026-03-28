"""
tests/unit/test_portfolio_optimizer.py

Unit tests for orchestrator/portfolio_optimizer.py (Phase 8).

All Alpaca API calls, Claude API calls, and file I/O are mocked — fully offline.

Coverage:
  - load_target_allocation() falls back to defaults when file is missing
  - load_target_allocation() parses valid YAML and merges settings defaults
  - _compute_proposals() generates SELL for over-allocated positions
  - _compute_proposals() generates BUY for under-allocated positions
  - _compute_proposals() generates BUY for positions not yet held
  - _compute_proposals() skips positions below min_trade_value
  - _compute_proposals() returns empty list when portfolio already in tolerance
  - _apply_risk_critic() keeps APPROVED proposals executable
  - _apply_risk_critic() moves BLOCK proposals to blocked list
  - _apply_risk_critic() adjusts qty on RESIZE verdict
  - _refine_buys_for_cash() caps buy quantities when insufficient cash
  - _refine_buys_for_cash() keeps buys that fit within available cash
  - _refine_buys_for_cash() zeros out buy when even 1 share can't be afforded
  - build_rebalance_plan() raises ValueError when target allocation is empty
  - build_rebalance_plan() raises ValueError when portfolio already in tolerance
  - build_rebalance_plan() returns RebalancePlan with correct fields
  - format_plan_markdown() includes tickers and sides
  - format_plan_markdown() includes blocked list when present
"""

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from orchestrator.portfolio_optimizer import (
    TradeProposal,
    RebalancePlan,
    load_target_allocation,
    _compute_proposals,
    _apply_risk_critic,
    _refine_buys_for_cash,
    format_plan_markdown,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_positions(overrides: dict | None = None) -> list[dict]:
    """Return a default list of positions with optional field overrides."""
    defaults = [
        {"ticker": "AAPL", "market_value": 15_000.0, "quantity": 75.0,  "current_price": 200.0},
        {"ticker": "NVDA", "market_value":  8_000.0, "quantity": 16.0,  "current_price": 500.0},
    ]
    if overrides:
        for pos in defaults:
            if pos["ticker"] in overrides:
                pos.update(overrides[pos["ticker"]])
    return defaults


def _make_target() -> dict[str, float]:
    return {
        "AAPL":  0.10,   # 10% target
        "NVDA":  0.12,   # 12% target
        "MSFT":  0.08,   # 8%  target — not yet held
    }


def _make_settings() -> dict:
    return {
        "min_trade_value":  50.0,
        "cash_buffer_pct":  0.05,
        "reduce_untracked": False,
    }


def _make_proposal(
    ticker="AAPL",
    side="sell",
    qty=5,
    price=200.0,
    current_pct=0.15,
    target_pct=0.10,
    verdict="pending",
) -> TradeProposal:
    drift = current_pct - target_pct
    return TradeProposal(
        ticker=ticker, side=side,
        proposed_qty=qty, adjusted_qty=qty,
        current_price=price, trade_value=qty * price,
        current_pct=current_pct, target_pct=target_pct,
        drift_pct=drift, risk_verdict=verdict, risk_note="",
    )


# ── load_target_allocation ─────────────────────────────────────────────────────

class TestLoadTargetAllocation:

    def test_returns_defaults_when_file_missing(self):
        with patch("orchestrator.portfolio_optimizer.open", side_effect=FileNotFoundError):
            cfg = load_target_allocation()
        assert cfg["allocations"] == {}
        assert cfg["settings"]["min_trade_value"] == 50.0
        assert cfg["settings"]["cash_buffer_pct"] == 0.05
        assert cfg["settings"]["reduce_untracked"] is False

    def test_parses_valid_yaml(self):
        yaml_content = """
allocations:
  AAPL: 0.15
  NVDA: 0.12
settings:
  min_trade_value: 100.0
  cash_buffer_pct: 0.03
  reduce_untracked: true
"""
        import yaml
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("orchestrator.portfolio_optimizer._CONFIG_PATH"):
                cfg = load_target_allocation()
        assert cfg["allocations"]["AAPL"] == pytest.approx(0.15)
        assert cfg["allocations"]["NVDA"] == pytest.approx(0.12)
        assert cfg["settings"]["min_trade_value"] == pytest.approx(100.0)
        assert cfg["settings"]["reduce_untracked"] is True

    def test_merges_missing_settings_keys_with_defaults(self):
        yaml_content = "allocations:\n  AAPL: 0.15\nsettings:\n  min_trade_value: 75.0\n"
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("orchestrator.portfolio_optimizer._CONFIG_PATH"):
                cfg = load_target_allocation()
        # cash_buffer_pct not in yaml — should fall back to default
        assert cfg["settings"]["cash_buffer_pct"] == pytest.approx(0.05)
        # min_trade_value was specified
        assert cfg["settings"]["min_trade_value"] == pytest.approx(75.0)

    def test_returns_defaults_on_parse_error(self):
        with patch("builtins.open", mock_open(read_data="!!invalid: [yaml")):
            with patch("orchestrator.portfolio_optimizer._CONFIG_PATH"):
                cfg = load_target_allocation()
        assert isinstance(cfg["allocations"], dict)


# ── _compute_proposals ─────────────────────────────────────────────────────────

class TestComputeProposals:

    def test_sell_generated_for_over_allocated(self):
        # AAPL at 15% but target is 10% → sell
        equity    = 100_000.0
        positions = [{"ticker": "AAPL", "market_value": 15_000.0, "quantity": 75.0, "current_price": 200.0}]
        target    = {"AAPL": 0.10}
        settings  = _make_settings()

        proposals = _compute_proposals(positions, equity, target, settings)
        sells = [p for p in proposals if p.side == "sell"]
        assert len(sells) == 1
        assert sells[0].ticker == "AAPL"
        assert sells[0].adjusted_qty >= 1

    def test_buy_generated_for_under_allocated(self):
        # NVDA at 8% but target is 12% → buy
        equity    = 100_000.0
        positions = [{"ticker": "NVDA", "market_value": 8_000.0, "quantity": 16.0, "current_price": 500.0}]
        target    = {"NVDA": 0.12}
        settings  = _make_settings()

        proposals = _compute_proposals(positions, equity, target, settings)
        buys = [p for p in proposals if p.side == "buy"]
        assert len(buys) == 1
        assert buys[0].ticker == "NVDA"
        assert buys[0].adjusted_qty >= 1

    @patch("orchestrator.portfolio_optimizer.get_current_price")
    def test_buy_generated_for_new_position(self, mock_price):
        # MSFT not in positions at all, target 8%
        mock_price.return_value = {"current_price": 400.0}
        equity    = 100_000.0
        positions = []
        target    = {"MSFT": 0.08}
        settings  = _make_settings()

        proposals = _compute_proposals(positions, equity, target, settings)
        buys = [p for p in proposals if p.side == "buy"]
        assert len(buys) == 1
        assert buys[0].ticker == "MSFT"

    def test_skips_position_below_min_trade_value(self):
        # Drift of 0.001% on a 10k portfolio = $10, below $50 min
        equity    = 10_000.0
        positions = [{"ticker": "AAPL", "market_value": 1_010.0, "quantity": 5.0, "current_price": 202.0}]
        target    = {"AAPL": 0.10}  # target = $1,000 — drift = $10
        settings  = {"min_trade_value": 50.0, "cash_buffer_pct": 0.05, "reduce_untracked": False}

        proposals = _compute_proposals(positions, equity, target, settings)
        assert proposals == []

    def test_returns_empty_when_already_at_target(self):
        equity    = 100_000.0
        positions = [{"ticker": "AAPL", "market_value": 10_000.0, "quantity": 50.0, "current_price": 200.0}]
        target    = {"AAPL": 0.10}
        settings  = _make_settings()

        proposals = _compute_proposals(positions, equity, target, settings)
        assert proposals == []

    def test_sells_come_before_buys(self):
        equity = 100_000.0
        positions = [
            {"ticker": "AAPL", "market_value": 15_000.0, "quantity": 75.0, "current_price": 200.0},
            {"ticker": "NVDA", "market_value":  8_000.0, "quantity": 16.0, "current_price": 500.0},
        ]
        target   = {"AAPL": 0.10, "NVDA": 0.12}
        settings = _make_settings()

        proposals = _compute_proposals(positions, equity, target, settings)
        if len(proposals) >= 2:
            sides = [p.side for p in proposals]
            # All sells should appear before all buys
            last_sell_idx = max((i for i, s in enumerate(sides) if s == "sell"), default=-1)
            first_buy_idx = min((i for i, s in enumerate(sides) if s == "buy"), default=999)
            assert last_sell_idx < first_buy_idx


# ── _apply_risk_critic ─────────────────────────────────────────────────────────

class TestApplyRiskCritic:

    def _mock_risk_result(self, verdict_str: str, adjusted_qty: int = 5):
        from orchestrator.risk_agent import Verdict
        verdict_map = {
            "APPROVED":  Verdict.APPROVED,
            "RESIZE":    Verdict.RESIZE,
            "BLOCK":     Verdict.BLOCK,
            "ESCALATE":  Verdict.ESCALATE,
        }
        result = MagicMock()
        result.verdict      = verdict_map[verdict_str]
        result.adjusted_qty = adjusted_qty
        result.reason       = f"{verdict_str} reason"
        result.narrative    = f"{verdict_str} narrative"
        return result

    def test_approved_stays_executable(self):
        proposal = _make_proposal(side="buy", qty=10)
        mock_result = self._mock_risk_result("APPROVED", adjusted_qty=10)

        with patch("orchestrator.portfolio_optimizer.evaluate_proposal", return_value=mock_result):
            executable, blocked = _apply_risk_critic([proposal])

        assert len(executable) == 1
        assert len(blocked)    == 0
        assert executable[0].risk_verdict == "APPROVED"

    def test_block_moves_to_blocked(self):
        proposal = _make_proposal(side="buy", qty=10)
        mock_result = self._mock_risk_result("BLOCK", adjusted_qty=0)

        with patch("orchestrator.portfolio_optimizer.evaluate_proposal", return_value=mock_result):
            executable, blocked = _apply_risk_critic([proposal])

        assert len(executable) == 0
        assert len(blocked)    == 1
        assert blocked[0].risk_verdict  == "BLOCK"
        assert blocked[0].adjusted_qty  == 0

    def test_resize_adjusts_qty(self):
        proposal = _make_proposal(side="buy", qty=20)
        mock_result = self._mock_risk_result("RESIZE", adjusted_qty=10)

        with patch("orchestrator.portfolio_optimizer.evaluate_proposal", return_value=mock_result):
            executable, blocked = _apply_risk_critic([proposal])

        assert len(executable) == 1
        assert executable[0].adjusted_qty == 10
        assert executable[0].risk_verdict == "RESIZE"

    def test_escalate_stays_executable(self):
        proposal = _make_proposal(side="buy", qty=5)
        mock_result = self._mock_risk_result("ESCALATE", adjusted_qty=5)

        with patch("orchestrator.portfolio_optimizer.evaluate_proposal", return_value=mock_result):
            executable, blocked = _apply_risk_critic([proposal])

        assert len(executable) == 1
        assert executable[0].risk_verdict == "ESCALATE"

    def test_exception_goes_to_blocked(self):
        proposal = _make_proposal(side="buy", qty=5)

        with patch("orchestrator.portfolio_optimizer.evaluate_proposal", side_effect=RuntimeError("network")):
            executable, blocked = _apply_risk_critic([proposal])

        assert len(executable) == 0
        assert len(blocked)    == 1
        assert blocked[0].risk_verdict == "ERROR"

    def test_mixed_batch(self):
        proposals = [
            _make_proposal("AAPL", "sell", 5),
            _make_proposal("NVDA", "buy",  3),
            _make_proposal("MSFT", "buy",  2),
        ]
        approved = self._mock_risk_result("APPROVED", adjusted_qty=5)
        block    = self._mock_risk_result("BLOCK",    adjusted_qty=0)
        resize   = self._mock_risk_result("RESIZE",   adjusted_qty=1)

        with patch(
            "orchestrator.portfolio_optimizer.evaluate_proposal",
            side_effect=[approved, block, resize],
        ):
            executable, blocked = _apply_risk_critic(proposals)

        assert len(executable) == 2  # AAPL sell + MSFT resize
        assert len(blocked)    == 1  # NVDA blocked
        assert blocked[0].ticker == "NVDA"


# ── _refine_buys_for_cash ──────────────────────────────────────────────────────

class TestRefineBuysForCash:

    def _buy(self, ticker: str, qty: int, price: float) -> TradeProposal:
        return _make_proposal(ticker=ticker, side="buy", qty=qty, price=price)

    def test_buy_fits_in_cash(self):
        buy = self._buy("AAPL", 5, 200.0)   # $1,000
        trades = [buy]
        result = _refine_buys_for_cash(trades, available_cash=2000.0, cash_buffer_pct=0.0, equity=10_000.0)
        assert result[0].adjusted_qty == 5
        assert result[0].trade_value  == pytest.approx(1000.0)

    def test_buy_gets_reduced_when_over_cash(self):
        buy = self._buy("AAPL", 10, 200.0)  # $2,000 but only $1,500 spendable
        trades = [buy]
        result = _refine_buys_for_cash(trades, available_cash=1500.0, cash_buffer_pct=0.0, equity=10_000.0)
        assert result[0].adjusted_qty == 7   # floor(1500 / 200)
        assert result[0].trade_value  == pytest.approx(7 * 200.0)

    def test_buy_zeroed_when_no_cash(self):
        buy = self._buy("AAPL", 5, 200.0)
        # cash 300, buffer = 5% * 10,000 = 500 → spendable = 300 - 500 = -200
        trades = [buy]
        result = _refine_buys_for_cash(trades, available_cash=300.0, cash_buffer_pct=0.05, equity=10_000.0)
        assert result[0].adjusted_qty == 0
        assert result[0].trade_value  == pytest.approx(0.0)

    def test_sell_proceeds_added_to_spendable(self):
        sell = _make_proposal("AAPL", "sell", 5, 200.0, current_pct=0.15, target_pct=0.10)
        buy  = self._buy("NVDA", 2, 500.0)   # $1,000 buy
        trades = [sell, buy]
        # cash 0, sell proceeds = 1,000, buffer 0 → spendable = 1,000
        result = _refine_buys_for_cash(trades, available_cash=0.0, cash_buffer_pct=0.0, equity=10_000.0)
        assert result[0].adjusted_qty == 2    # 1,000 / 500 = 2 shares

    def test_multiple_buys_share_available_cash(self):
        buy1 = self._buy("AAPL", 3, 200.0)   # $600
        buy2 = self._buy("NVDA", 2, 500.0)   # $1,000 but only $400 left after buy1
        trades = [buy1, buy2]
        # spendable = $1,000 total
        result = _refine_buys_for_cash(trades, available_cash=1000.0, cash_buffer_pct=0.0, equity=20_000.0)
        assert result[0].adjusted_qty == 3    # buy1 fits fully ($600)
        # After buy1, spendable = 400 → floor(400 / 500) = 0 → buy2 zeroed
        assert result[1].adjusted_qty == 0


# ── build_rebalance_plan ───────────────────────────────────────────────────────

class TestBuildRebalancePlan:

    def _mock_account(self):
        return {"equity": 100_000.0, "buying_power": 5_000.0, "error": None}

    def _mock_positions(self):
        return {
            "positions": [
                {"ticker": "AAPL", "market_value": 15_000.0, "quantity": 75.0, "current_price": 200.0},
            ]
        }

    def _mock_allocation_yaml(self):
        return {
            "allocations": {"AAPL": 0.10},
            "settings":    {"min_trade_value": 50.0, "cash_buffer_pct": 0.05, "reduce_untracked": False},
        }

    def _mock_risk_approved(self, ticker, qty, side):
        from orchestrator.risk_agent import Verdict
        r = MagicMock()
        r.verdict      = Verdict.APPROVED
        r.adjusted_qty = qty
        r.reason       = "ok"
        r.narrative    = ""
        return r

    @patch("orchestrator.portfolio_optimizer.store_rebalance_plan")
    @patch("orchestrator.portfolio_optimizer.queue_rebalance_alert")
    @patch("orchestrator.portfolio_optimizer.anthropic.Anthropic")
    @patch("orchestrator.portfolio_optimizer.evaluate_proposal")
    @patch("orchestrator.portfolio_optimizer.get_positions")
    @patch("orchestrator.portfolio_optimizer.get_account_balance")
    @patch("orchestrator.portfolio_optimizer.load_target_allocation")
    def test_returns_rebalance_plan(
        self, mock_load, mock_account, mock_positions,
        mock_eval, mock_anthropic, mock_queue, mock_store,
    ):
        from orchestrator.portfolio_optimizer import build_rebalance_plan
        mock_load.return_value     = self._mock_allocation_yaml()
        mock_account.return_value  = self._mock_account()
        mock_positions.return_value = self._mock_positions()
        mock_eval.side_effect      = self._mock_risk_approved
        mock_anthropic.return_value.messages.create.return_value.content = [
            MagicMock(text="Rebalancing rationale text.")
        ]

        plan = build_rebalance_plan("user:1")

        assert plan.user_id == "user:1"
        assert plan.equity  == pytest.approx(100_000.0)
        assert isinstance(plan.plan_id, str)
        assert len(plan.plan_id) == 36      # UUID format
        assert isinstance(plan.trades,  list)
        assert isinstance(plan.blocked, list)
        assert plan.rationale == "Rebalancing rationale text."
        mock_store.assert_called_once()
        mock_queue.assert_called_once()

    @patch("orchestrator.portfolio_optimizer.get_positions")
    @patch("orchestrator.portfolio_optimizer.get_account_balance")
    @patch("orchestrator.portfolio_optimizer.load_target_allocation")
    def test_raises_value_error_for_empty_allocation(
        self, mock_load, mock_account, mock_positions
    ):
        from orchestrator.portfolio_optimizer import build_rebalance_plan
        mock_load.return_value      = {"allocations": {}, "settings": _make_settings()}
        mock_account.return_value   = self._mock_account()
        mock_positions.return_value = self._mock_positions()

        with pytest.raises(ValueError, match="empty"):
            build_rebalance_plan("user:1")

    @patch("orchestrator.portfolio_optimizer.get_positions")
    @patch("orchestrator.portfolio_optimizer.get_account_balance")
    @patch("orchestrator.portfolio_optimizer.load_target_allocation")
    def test_raises_value_error_when_already_in_tolerance(
        self, mock_load, mock_account, mock_positions
    ):
        from orchestrator.portfolio_optimizer import build_rebalance_plan
        # AAPL at exactly 10% target
        mock_load.return_value = {
            "allocations": {"AAPL": 0.10},
            "settings":    {"min_trade_value": 50.0, "cash_buffer_pct": 0.05, "reduce_untracked": False},
        }
        mock_account.return_value   = {"equity": 100_000.0, "buying_power": 5_000.0, "error": None}
        mock_positions.return_value = {
            "positions": [
                {"ticker": "AAPL", "market_value": 10_000.0, "quantity": 50.0, "current_price": 200.0}
            ]
        }

        with pytest.raises(ValueError, match="tolerance"):
            build_rebalance_plan("user:1")


# ── format_plan_markdown ───────────────────────────────────────────────────────

class TestFormatPlanMarkdown:

    def _make_plan(self, trades=None, blocked=None) -> RebalancePlan:
        if trades is None:
            trades = [
                _make_proposal("AAPL", "sell", 5,  200.0, 0.15, 0.10, verdict="APPROVED"),
                _make_proposal("NVDA", "buy",  2,  500.0, 0.08, 0.12, verdict="APPROVED"),
            ]
        if blocked is None:
            blocked = []
        sell_val = sum(t.trade_value for t in trades if t.side == "sell")
        buy_val  = sum(t.trade_value for t in trades if t.side == "buy")
        return RebalancePlan(
            plan_id="test-plan-123",
            user_id="user:1",
            equity=100_000.0,
            cash=5_000.0,
            trades=trades,
            blocked=blocked,
            total_sell_value=round(sell_val, 2),
            total_buy_value=round(buy_val, 2),
            net_cash_change=round(sell_val - buy_val, 2),
            rationale="Test rationale.",
            target_allocation={"AAPL": 0.10, "NVDA": 0.12},
            created_at="2026-01-01T00:00:00+00:00",
        )

    def test_contains_ticker_names(self):
        plan = self._make_plan()
        md   = format_plan_markdown(plan)
        assert "AAPL" in md
        assert "NVDA" in md

    def test_contains_sides(self):
        plan = self._make_plan()
        md   = format_plan_markdown(plan)
        assert "SELL" in md
        assert "BUY"  in md

    def test_contains_rationale(self):
        plan = self._make_plan()
        md   = format_plan_markdown(plan)
        assert "Test rationale." in md

    def test_shows_blocked_list(self):
        blocked = [_make_proposal("MSFT", "buy", 0, 400.0, verdict="BLOCK")]
        plan    = self._make_plan(blocked=blocked)
        md      = format_plan_markdown(plan)
        assert "MSFT" in md
        assert "Blocked" in md or "blocked" in md

    def test_no_blocked_section_when_empty(self):
        plan = self._make_plan(blocked=[])
        md   = format_plan_markdown(plan)
        # Should not mention "Blocked" when there are no blocked trades
        assert "⛔" not in md

    def test_equity_in_header(self):
        plan = self._make_plan()
        md   = format_plan_markdown(plan)
        assert "100,000" in md or "100000" in md

    def test_verdict_badges_present(self):
        plan = self._make_plan()
        md   = format_plan_markdown(plan)
        assert "✅" in md  # APPROVED badge
