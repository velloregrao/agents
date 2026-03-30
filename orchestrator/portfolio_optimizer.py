"""
orchestrator/portfolio_optimizer.py

Portfolio optimizer agent (Phase 8).

Pattern: iterative refinement + generator-critic

Flow:
    1. Load target allocation from config/target_allocation.yaml
    2. Fetch current positions + equity from Alpaca
    3. Generator: compute trade proposals for each drifting position
           over-allocated  → SELL to bring back to target %
           under-allocated → BUY  to bring up to target %
           missing target  → BUY  to open position
    4. Critic (risk_agent): validate each proposal through evaluate_proposal()
           BLOCK  → remove from plan
           RESIZE → adjust qty in plan
           APPROVED/ESCALATE → keep (ESCALATE flagged for human attention)
    5. Refinement pass: recalculate buy quantities after sell resizes
           (freed cash may change what's affordable)
    6. Sonnet: generate 3-4 sentence rationale explaining the plan
    7. Persist plan → queue Teams rebalance card for approval
    8. Execution (after user approves via Teams card):
           sells first (to free cash), then buys
           each trade re-validated through risk gate at execution time

Public API:
    build_rebalance_plan(user_id) -> RebalancePlan
    execute_rebalance_plan(plan_id) -> dict
    load_target_allocation() -> dict
"""

import json
import math
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

import anthropic

from stock_agent.alpaca_tools import get_account_balance, get_positions, get_open_orders, place_order
from stock_agent.tools import get_current_price
from orchestrator.risk_agent import evaluate_proposal, Verdict
from orchestrator.alert_manager import (
    store_rebalance_plan,
    queue_rebalance_alert,
    get_rebalance_plan,
    mark_rebalance_executed,
)

# ── Config ────────────────────────────────────────────────────────────────────

_CONFIG_PATH = _AGENTS_ROOT / "config" / "target_allocation.yaml"
SONNET       = "claude-sonnet-4-6"

# ── Contracts ─────────────────────────────────────────────────────────────────

@dataclass
class TradeProposal:
    """
    One proposed rebalancing trade before and after risk-critic review.

    Fields:
        ticker         Stock symbol
        side           "buy" | "sell"
        proposed_qty   Shares computed from allocation drift
        adjusted_qty   Shares after risk critic (may be lower; 0 = blocked)
        current_price  Price at plan-build time
        trade_value    adjusted_qty * current_price
        current_pct    Current position as % of equity (0.0–1.0)
        target_pct     Target allocation % from config (0.0–1.0)
        drift_pct      current_pct - target_pct (negative = under-allocated)
        risk_verdict   "APPROVED" | "RESIZE" | "BLOCK" | "ESCALATE"
        risk_note      Short human-readable note from risk critic
    """
    ticker:        str
    side:          str
    proposed_qty:  int
    adjusted_qty:  int
    current_price: float
    trade_value:   float
    current_pct:   float
    target_pct:    float
    drift_pct:     float
    risk_verdict:  str
    risk_note:     str


@dataclass
class RebalancePlan:
    """
    Complete rebalancing plan ready for Teams card and execution.

    Fields:
        plan_id           UUID stored in DB; embedded in the Teams card buttons
        user_id           Who requested the plan
        equity            Total account equity at plan-build time
        cash              Available buying power at plan-build time
        trades            Executable trades (APPROVED / RESIZE / ESCALATE)
        blocked           Trades the risk critic blocked (informational only)
        total_sell_value  Sum of adjusted sell trade values
        total_buy_value   Sum of adjusted buy trade values
        net_cash_change   total_sell_value - total_buy_value
        rationale         Sonnet-generated 3-4 sentence explanation
        target_allocation Snapshot of the YAML config used
        created_at        ISO timestamp
    """
    plan_id:           str
    user_id:           str
    equity:            float
    cash:              float
    trades:            list[TradeProposal]
    blocked:           list[TradeProposal]
    total_sell_value:  float
    total_buy_value:   float
    net_cash_change:   float
    rationale:         str
    target_allocation: dict
    created_at:        str


# ── Config loader ─────────────────────────────────────────────────────────────

def load_target_allocation() -> dict:
    """
    Load target allocation and settings from config/target_allocation.yaml.
    Returns a dict with keys 'allocations' and 'settings'.
    Falls back to safe defaults if the file is missing or unparseable.
    """
    defaults = {
        "allocations": {},
        "settings": {
            "min_trade_value":  50.0,
            "cash_buffer_pct":  0.05,
            "reduce_untracked": False,
        },
    }
    try:
        import yaml  # PyYAML — already in requirements via alpaca dependencies
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        if not isinstance(cfg, dict):
            return defaults
        cfg.setdefault("allocations", {})
        cfg.setdefault("settings",    defaults["settings"])
        for k, v in defaults["settings"].items():
            cfg["settings"].setdefault(k, v)
        return cfg
    except FileNotFoundError:
        print(f"[optimizer] config not found at {_CONFIG_PATH} — using empty allocation", file=sys.stderr)
        return defaults
    except Exception as exc:
        print(f"[optimizer] config load error: {exc} — using defaults", file=sys.stderr)
        return defaults


# ── Generator: compute raw trade proposals ────────────────────────────────────

def _compute_proposals(
    positions:         list[dict],
    equity:            float,
    target_allocation: dict[str, float],
    settings:          dict,
    pending_buys:      dict[str, float] | None = None,
) -> list[TradeProposal]:
    """
    Compute the raw list of trade proposals from allocation drift.

    Sells are computed first so the refinement pass can determine available
    cash for buys.  Within each side, proposals are sorted by abs(drift_pct)
    descending so the biggest drifts are addressed first.

    pending_buys: ticker → qty already queued in open (unfilled) buy orders.
    These shares are counted as if already held so a second Optimize call
    while orders are pending doesn't double-buy the same position.
    """
    if equity <= 0:
        return []

    min_trade_value  = float(settings.get("min_trade_value",  50.0))
    reduce_untracked = bool(settings.get("reduce_untracked",  False))
    pending_buys     = pending_buys or {}

    # Build current allocation map: ticker → {market_value, current_pct, qty, price}
    current: dict[str, dict] = {}
    for pos in positions:
        ticker = pos["ticker"].upper()
        current[ticker] = {
            "market_value": float(pos.get("market_value", 0)),
            "current_pct":  float(pos.get("market_value", 0)) / equity,
            "qty":          float(pos.get("quantity", 0)),
            "price":        float(pos.get("current_price", 0)),
        }

    # Merge pending buy orders into current allocation so drift is computed
    # against (filled positions + in-flight orders).  Uses the filled price
    # if available, otherwise falls back to get_current_price().
    for ticker, pending_qty in pending_buys.items():
        ticker = ticker.upper()
        if pending_qty <= 0:
            continue
        if ticker in current:
            # Position exists — add pending shares at current price
            price         = current[ticker]["price"]
            extra_value   = pending_qty * price
            new_qty       = current[ticker]["qty"] + pending_qty
            new_mv        = current[ticker]["market_value"] + extra_value
            current[ticker]["qty"]          = new_qty
            current[ticker]["market_value"] = new_mv
            current[ticker]["current_pct"]  = new_mv / equity
        else:
            # No filled position yet — fetch price to estimate value
            try:
                from stock_agent.tools import get_current_price
                pd    = get_current_price(ticker)
                price = float(pd.get("current_price") or 0)
            except Exception:
                price = 0.0
            if price > 0:
                mv = pending_qty * price
                current[ticker] = {
                    "market_value": mv,
                    "current_pct":  mv / equity,
                    "qty":          pending_qty,
                    "price":        price,
                }

    proposals: list[TradeProposal] = []

    # Sells: over-allocated positions + optionally untracked positions
    for ticker, info in current.items():
        in_target = ticker in target_allocation
        target_pct = target_allocation.get(ticker, 0.0)
        drift_pct  = info["current_pct"] - target_pct

        should_sell = (in_target and drift_pct > 0) or (not in_target and reduce_untracked)
        if not should_sell:
            continue

        sell_value = drift_pct * equity if in_target else info["market_value"]
        if sell_value < min_trade_value:
            continue

        price = info["price"]
        if price <= 0:
            continue
        qty = math.floor(sell_value / price)
        if qty < 1:
            continue

        proposals.append(TradeProposal(
            ticker=ticker, side="sell",
            proposed_qty=qty, adjusted_qty=qty,
            current_price=price,
            trade_value=qty * price,
            current_pct=info["current_pct"],
            target_pct=target_pct,
            drift_pct=drift_pct,
            risk_verdict="pending", risk_note="",
        ))

    # Buys: under-allocated or new target positions
    for ticker, target_pct in target_allocation.items():
        info       = current.get(ticker, {"market_value": 0.0, "current_pct": 0.0, "price": 0.0})
        drift_pct  = info["current_pct"] - target_pct
        if drift_pct >= 0:
            continue  # at or above target

        buy_value = abs(drift_pct) * equity
        if buy_value < min_trade_value:
            continue

        # Fetch current price if not in positions
        price = info["price"]
        if price <= 0:
            try:
                pd = get_current_price(ticker)
                price = float(pd.get("current_price") or 0)
            except Exception:
                pass
        if price <= 0:
            continue

        qty = math.floor(buy_value / price)
        if qty < 1:
            continue

        proposals.append(TradeProposal(
            ticker=ticker, side="buy",
            proposed_qty=qty, adjusted_qty=qty,
            current_price=price,
            trade_value=qty * price,
            current_pct=info["current_pct"],
            target_pct=target_pct,
            drift_pct=drift_pct,
            risk_verdict="pending", risk_note="",
        ))

    # Sort: sells descending by drift_pct, buys ascending by drift_pct (most under-allocated first)
    sells = sorted([p for p in proposals if p.side == "sell"], key=lambda p: p.drift_pct, reverse=True)
    buys  = sorted([p for p in proposals if p.side == "buy"],  key=lambda p: p.drift_pct)
    return sells + buys


# ── Critic: risk-gate each proposal ──────────────────────────────────────────

def _apply_risk_critic(proposals: list[TradeProposal]) -> tuple[list[TradeProposal], list[TradeProposal]]:
    """
    Run each proposal through evaluate_proposal().

    Sells are always approved (risk_agent allows all sells).
    Buys go through all 4 risk rules.

    Returns (executable_trades, blocked_trades).
    BLOCK verdicts go to blocked list; all others stay executable.
    """
    executable: list[TradeProposal] = []
    blocked:    list[TradeProposal] = []

    for proposal in proposals:
        try:
            result = evaluate_proposal(proposal.ticker, proposal.proposed_qty, proposal.side)
            proposal.risk_verdict = result.verdict.value
            proposal.risk_note    = result.narrative or result.reason

            if result.verdict == Verdict.BLOCK:
                proposal.adjusted_qty = 0
                proposal.trade_value  = 0.0
                blocked.append(proposal)
            else:
                proposal.adjusted_qty = result.adjusted_qty
                proposal.trade_value  = proposal.adjusted_qty * proposal.current_price
                executable.append(proposal)

        except Exception as exc:
            print(f"[optimizer] risk check failed for {proposal.ticker}: {exc}", file=sys.stderr)
            proposal.risk_verdict = "ERROR"
            proposal.risk_note    = str(exc)
            proposal.adjusted_qty = 0
            blocked.append(proposal)

    return executable, blocked


# ── Refinement: adjust buys for available cash ───────────────────────────────

def _refine_buys_for_cash(
    trades:          list[TradeProposal],
    available_cash:  float,
    cash_buffer_pct: float,
    equity:          float,
) -> list[TradeProposal]:
    """
    Cap buy quantities so total buy value doesn't exceed spendable cash.

    Spendable cash = available_cash + sell proceeds - cash_buffer
    Sells are processed first; each sell frees cash.  Buys are then
    granted in priority order until cash runs out.
    """
    sell_proceeds = sum(p.trade_value for p in trades if p.side == "sell")
    cash_reserve  = equity * cash_buffer_pct
    spendable     = available_cash + sell_proceeds - cash_reserve

    refined: list[TradeProposal] = []
    buys    = [p for p in trades if p.side == "buy"]

    for buy in buys:
        if spendable <= 0:
            buy.adjusted_qty = 0
            buy.trade_value  = 0.0
            buy.risk_note   += " (insufficient cash after cash buffer)"
        elif buy.trade_value > spendable:
            affordable_qty  = math.floor(spendable / buy.current_price)
            if affordable_qty < 1:
                buy.adjusted_qty = 0
                buy.trade_value  = 0.0
                buy.risk_note   += " (insufficient cash)"
            else:
                buy.adjusted_qty = affordable_qty
                buy.trade_value  = affordable_qty * buy.current_price
                buy.risk_note   += f" (qty reduced from {buy.proposed_qty} due to cash)"
                spendable       -= buy.trade_value
        else:
            spendable -= buy.trade_value
        refined.append(buy)

    return refined


# ── Sonnet rationale ──────────────────────────────────────────────────────────

def _generate_rationale(
    plan_trades: list[TradeProposal],
    blocked:     list[TradeProposal],
    equity:      float,
    target:      dict[str, float],
) -> str:
    """
    Ask Sonnet to write a 3-4 sentence rationale for the rebalancing plan.
    Falls back to a deterministic stub on any error.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    trade_lines = "\n".join(
        f"  {p.side.upper()} {p.adjusted_qty} {p.ticker} @ ${p.current_price:.2f} "
        f"(drift: {p.drift_pct*100:+.1f}%, risk: {p.risk_verdict})"
        for p in plan_trades
    )
    blocked_line = (
        f"\nBlocked by risk gate: {', '.join(p.ticker for p in blocked)}"
        if blocked else ""
    )

    prompt = (
        f"You are a portfolio manager. Write a 3-4 sentence rationale for this "
        f"rebalancing plan. Total equity: ${equity:,.0f}.\n\n"
        f"Proposed trades:\n{trade_lines}{blocked_line}\n\n"
        f"Target allocations: {json.dumps({k: f'{v*100:.0f}%' for k, v in target.items()})}\n\n"
        f"Be specific about which positions are over/under-allocated and why this "
        f"rebalancing makes sense. Use plain language. No markdown, no bullet points."
    )

    try:
        response = client.messages.create(
            model=SONNET,
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        print(f"[optimizer] rationale generation failed: {exc}", file=sys.stderr)
        sells = [p for p in plan_trades if p.side == "sell"]
        buys  = [p for p in plan_trades if p.side == "buy"]
        parts = []
        if sells:
            parts.append(f"Sell {', '.join(p.ticker for p in sells)} (over-allocated)")
        if buys:
            parts.append(f"Buy {', '.join(p.ticker for p in buys)} (under-allocated)")
        return " | ".join(parts) if parts else "No rebalancing trades required."


# ── Public entry points ───────────────────────────────────────────────────────

def build_rebalance_plan(user_id: str) -> RebalancePlan:
    """
    Build a complete rebalancing plan for the user.

    Generator → critic → refinement → rationale → persist → return.
    Never executes trades — plan requires Teams approval.
    """
    # ── Fetch portfolio state ──────────────────────────────────────────────────
    account   = get_account_balance()
    pos_data  = get_positions()
    ord_data  = get_open_orders()

    if account.get("error"):
        raise RuntimeError(f"Cannot fetch account: {account['error']}")

    equity    = float(account.get("equity",        0))
    cash      = float(account.get("buying_power",  0))
    positions = pos_data.get("positions", [])

    # Build pending buys map: ticker → total unfilled buy qty
    # Prevents double-buying when orders are accepted but not yet filled
    pending_buys: dict[str, float] = {}
    for o in ord_data.get("open_orders", []):
        t = o["ticker"].upper()
        pending_buys[t] = pending_buys.get(t, 0.0) + float(o["quantity"])

    if pending_buys:
        print(
            f"[optimizer] {len(pending_buys)} ticker(s) have pending buy orders "
            f"— treating as filled for drift calculation: {list(pending_buys.keys())}",
            file=sys.stderr,
        )

    # ── Load config ────────────────────────────────────────────────────────────
    cfg               = load_target_allocation()
    target_allocation = {k.upper(): float(v) for k, v in cfg["allocations"].items()}
    settings          = cfg["settings"]

    if not target_allocation:
        raise ValueError(
            "Target allocation is empty. Edit config/target_allocation.yaml to add positions."
        )

    # ── Generator: compute raw proposals ─────────────────────────────────────
    proposals = _compute_proposals(positions, equity, target_allocation, settings, pending_buys)

    if not proposals:
        raise ValueError(
            "Portfolio is already within tolerance of target allocation — no trades needed."
        )

    # ── Critic: risk-gate all proposals ──────────────────────────────────────
    executable, blocked = _apply_risk_critic(proposals)

    # ── Refinement: cap buys for available cash ───────────────────────────────
    cash_buffer_pct  = float(settings.get("cash_buffer_pct", 0.05))
    sells            = [p for p in executable if p.side == "sell"]
    unrefined_buys   = [p for p in executable if p.side == "buy"]
    refined_buys     = _refine_buys_for_cash(unrefined_buys, cash, cash_buffer_pct, equity)

    # Drop zero-qty buys after cash refinement into blocked
    final_trades:   list[TradeProposal] = sells.copy()
    for buy in refined_buys:
        if buy.adjusted_qty > 0:
            final_trades.append(buy)
        else:
            buy.risk_verdict = "BLOCK"
            blocked.append(buy)

    # ── Sonnet rationale ──────────────────────────────────────────────────────
    rationale = _generate_rationale(final_trades, blocked, equity, target_allocation)

    # ── Aggregate values ──────────────────────────────────────────────────────
    total_sell = sum(p.trade_value for p in final_trades if p.side == "sell")
    total_buy  = sum(p.trade_value for p in final_trades if p.side == "buy")

    plan = RebalancePlan(
        plan_id=str(uuid.uuid4()),
        user_id=user_id,
        equity=equity,
        cash=cash,
        trades=final_trades,
        blocked=blocked,
        total_sell_value=round(total_sell, 2),
        total_buy_value=round(total_buy, 2),
        net_cash_change=round(total_sell - total_buy, 2),
        rationale=rationale,
        target_allocation=target_allocation,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # ── Persist plan ──────────────────────────────────────────────────────────
    store_rebalance_plan(plan)
    queue_rebalance_alert(user_id, plan)

    return plan


def execute_rebalance_plan(plan_id: str) -> dict:
    """
    Execute an approved rebalancing plan.

    Fetches the plan from DB, places sells first (to free cash), then buys.
    Each trade goes through place_order() directly — they already passed the
    risk gate at plan-build time, but prices may have moved so each order
    is still submitted as a market order with the exchange as the safety net.

    Returns a summary dict with executed / failed trade counts.
    """
    plan_data = get_rebalance_plan(plan_id)
    if not plan_data:
        raise ValueError(f"Rebalance plan {plan_id} not found or already executed.")

    trades = [TradeProposal(**t) for t in plan_data["trades"]]

    executed: list[str] = []
    failed:   list[str] = []

    # Sells first — frees up buying power
    for trade in sorted(trades, key=lambda t: 0 if t.side == "sell" else 1):
        if trade.adjusted_qty < 1:
            continue
        result = place_order(trade.ticker, trade.adjusted_qty, trade.side)
        if result.get("error"):
            print(f"[optimizer] execute failed {trade.ticker}: {result['error']}", file=sys.stderr)
            failed.append(f"{trade.ticker} ({result['error'][:40]})")
        else:
            executed.append(f"{trade.side.upper()} {trade.adjusted_qty} {trade.ticker}")

    mark_rebalance_executed(plan_id)

    return {
        "plan_id":   plan_id,
        "executed":  executed,
        "failed":    failed,
        "summary":   f"{len(executed)} trade(s) executed, {len(failed)} failed.",
    }


def format_plan_markdown(plan: RebalancePlan) -> str:
    """
    Format a RebalancePlan as Teams-ready markdown for the text preview
    sent alongside the approval card.
    """
    lines = [
        f"## 📊 Portfolio Rebalancing Plan",
        f"**Equity: ${plan.equity:,.0f}** | "
        f"**{len(plan.trades)} trade(s)** | "
        f"Net cash: ${plan.net_cash_change:+,.0f}",
        "",
        "| Ticker | Action | Shares | Value | Current % | Target % |",
        "|--------|--------|--------|-------|-----------|----------|",
    ]

    for t in plan.trades:
        verdict_badge = {"APPROVED": "✅", "RESIZE": "🔄", "ESCALATE": "⚠️"}.get(t.risk_verdict, "")
        lines.append(
            f"| {t.ticker} | {t.side.upper()} {verdict_badge} | {t.adjusted_qty} "
            f"| ${t.trade_value:,.0f} "
            f"| {t.current_pct*100:.1f}% | {t.target_pct*100:.1f}% |"
        )

    if plan.blocked:
        lines += ["", f"*⛔ Blocked by risk gate: {', '.join(p.ticker for p in plan.blocked)}*"]

    lines += ["", f"> {plan.rationale}"]
    return "\n".join(lines)


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys
    user = _sys.argv[1] if len(_sys.argv) > 1 else "test_user"
    print(f"Building rebalance plan for {user}...\n")
    try:
        plan = build_rebalance_plan(user)
        print(format_plan_markdown(plan))
        print(f"\nplan_id: {plan.plan_id}")
        print(f"trades:  {len(plan.trades)}  blocked: {len(plan.blocked)}")
    except ValueError as e:
        print(f"ℹ️  {e}")
    except Exception as e:
        print(f"❌ {e}")
