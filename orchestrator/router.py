"""
orchestrator/router.py

Central router for the agent platform.

Responsibilities:
  1. Classify user intent using Claude Haiku (fast, cheap model)
  2. Fall back to regex classification if Haiku is unavailable
  3. Dispatch to the correct agent pipeline
  4. Thread user_id through to pipeline entry points (Phase 4 multi-tenancy)
  5. Return a normalised AgentResponse

Model tiering (from CLAUDE.md):
  HAIKU  — routing, classification, lesson filtering   (~40-60% cost reduction)
  SONNET — analysis, research, trading, risk narrative

Phase 3 will insert risk_agent.evaluate_proposal() into _dispatch()
before any trade execution.
"""

import os
import re
import sys
import json
import anthropic
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# Allow importing stock_agent package from orchestrator/
_AGENTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from orchestrator.contracts import AgentMessage, AgentResponse
from orchestrator.risk_agent import evaluate_proposal, Verdict
from orchestrator.approval_manager import store_pending
from stock_agent.agent import run_analysis
from stock_agent.trading_agent import run_trading_agent, monitor_positions
from stock_agent.reflection import reflect
from stock_agent.research import run_research_orchestrator
from stock_agent.alpaca_tools import get_account_balance, get_positions
from stock_agent.tools import get_current_price
from stock_agent.memory import get_performance_summary
from stock_agent.watchlist import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
)

# ── Model constants ────────────────────────────────────────────────────────────

HAIKU  = "claude-haiku-4-5-20251001"   # routing, classification, formatting
SONNET = "claude-sonnet-4-6"           # analysis, risk narrative, trade thesis

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Haiku intent classifier ────────────────────────────────────────────────────

_VALID_INTENTS = frozenset({
    "analyze", "research", "trade", "portfolio",
    "reflect", "monitor", "help", "unknown",
    "watch", "unwatch", "watchlist", "earnings", "mtf", "optimize", "digest",
})

_CLASSIFIER_SYSTEM = """You are an intent classifier for a stock trading assistant.

Classify the user message into exactly one intent and extract any stock ticker symbols.

Intents:
  analyze   → user wants technical or fundamental analysis of a stock
  research  → user wants deep research with a buy/hold/sell recommendation
  trade     → user wants to execute trades or run a trading strategy on stocks
  portfolio → user wants to see positions, balance, P&L, or performance stats
  reflect   → user wants to review lessons learned from past trades
  monitor   → user wants to review open positions for potential exits
  watch     → user wants to add one or more tickers to their watchlist
  unwatch   → user wants to remove one or more tickers from their watchlist
  watchlist → user wants to see their current watchlist
  earnings  → user wants upcoming earnings dates, estimates, or pre-earnings thesis for a stock
  mtf       → user wants multi-timeframe (15m/daily/weekly) technical analysis of a stock
  optimize  → user wants to rebalance or optimize their portfolio against a target allocation
  digest    → user wants the weekly trading digest, journal summary, or lessons learned
  help      → greeting, or asking what the bot can do
  unknown   → message does not match any category

Ticker extraction rules:
  - Extract real stock symbols only (1–5 uppercase letters, e.g. AAPL, NVDA, MSFT)
  - Never extract common English words as tickers
  - Infer symbols from company names: Apple→AAPL, Nvidia→NVDA, Microsoft→MSFT, Tesla→TSLA

Disambiguation:
  - analyze vs research: research implies a recommendation or decision is needed
  - trade vs analyze: trade implies the user wants orders placed, not just information
  - mtf vs analyze: mtf is explicitly multi-timeframe (15m + daily + weekly); use analyze for single-timeframe
  - optimize vs portfolio: portfolio is read-only; optimize implies generating a rebalancing plan

Respond with valid JSON only — no explanation, no markdown fences:
{"intent": "analyze", "tickers": ["AAPL"]}"""


def _classify(text: str) -> tuple[str, list[str]]:
    """
    Use Claude Haiku to classify intent and extract ticker symbols.
    Falls back to regex on any failure (API error, invalid JSON, unknown intent).
    """
    if not text.strip():
        return "unknown", []

    try:
        response = _client.messages.create(
            model=HAIKU,
            max_tokens=100,
            system=_CLASSIFIER_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if Haiku wraps its output
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed  = json.loads(raw)
        intent  = parsed.get("intent", "unknown")
        tickers = [t.upper() for t in parsed.get("tickers", []) if isinstance(t, str)]

        if intent not in _VALID_INTENTS:
            return _parse_intent_fallback(text)

        return intent, tickers

    except Exception:
        # Haiku unavailable or returned unparseable output — degrade gracefully
        return _parse_intent_fallback(text)


# ── Regex fallback classifier ──────────────────────────────────────────────────
# Used when Haiku is unavailable. Identical logic to the original teamsBot.ts
# parseIntent() function, ported to Python in Phase 1.

_SKIP_WORDS = frozenset({
    "ANALYZE", "ANALYSIS", "STOCK", "SHARE", "PRICE", "GET", "SHOW",
    "TELL", "WHAT", "HOW", "IS", "THE", "FOR", "ME", "TRADE", "TRADES",
    "BUY", "SELL", "PORTFOLIO", "PERFORMANCE", "REFLECT", "REFLECTION",
    "MONITOR", "POSITIONS", "HELP", "HI", "HELLO", "AND", "ON", "A",
    "RUN", "CHECK", "MY", "WATCH", "UNWATCH", "TRACK", "FOLLOW",
    "WATCHLIST", "REMOVE", "ADD", "STOP", "EARNINGS", "WHEN", "REPORT",
    "UPCOMING", "REPORTS", "DOES", "MTF", "MULTI", "TIMEFRAME",
    "OPTIMIZE", "REBALANCE", "ALLOCATION", "DIGEST", "JOURNAL", "WEEKLY",
})


def _parse_intent_fallback(text: str) -> tuple[str, list[str]]:
    """Regex-based fallback classifier used when Haiku is unavailable."""
    upper   = text.upper()
    words   = re.sub(r"[^A-Z\s]", "", upper).split()
    tickers = [w for w in words if 1 <= len(w) <= 5 and w not in _SKIP_WORDS]

    if re.match(r"^(hi|hello|hey|help)$", text.strip(), re.IGNORECASE):
        return "help", []
    if re.search(r"monitor|check\s+positions|review\s+positions", text, re.IGNORECASE):
        return "monitor", []
    if re.search(r"portfolio|positions|holdings", text, re.IGNORECASE):
        return "portfolio", tickers
    if re.search(r"performance|stats|statistics|pnl|profit", text, re.IGNORECASE):
        return "portfolio", tickers
    if re.search(r"reflect|reflection|lessons|learn", text, re.IGNORECASE):
        return "reflect", []
    if re.search(r"mtf|multi.?timeframe|multi.?tf|all.?timeframe", text, re.IGNORECASE):
        return "mtf", tickers
    if re.search(r"optimize|optimise|rebalance|re.?balance|allocation|target.*alloc", text, re.IGNORECASE):
        return "optimize", []
    if re.search(r"digest|journal|weekly.*summary|lessons.*learned|trading.*summary", text, re.IGNORECASE):
        return "digest", []
    if re.search(r"earnings|when.*report|upcoming.*earn|earn.*date|report.*date", text, re.IGNORECASE):
        return "earnings", tickers
    if re.search(r"unwatch|stop\s+watch|stop\s+track|remove.*watch", text, re.IGNORECASE) and tickers:
        return "unwatch", tickers
    if re.search(r"watchlist|what.*watch|show.*watch|my.*watch", text, re.IGNORECASE):
        return "watchlist", []
    if re.search(r"\bwatch\b|\btrack\b|\bfollow\b", text, re.IGNORECASE) and tickers:
        return "watch", tickers
    if re.search(r"research|deep.?dive|full.?analysis|recommend", text, re.IGNORECASE) and tickers:
        return "research", tickers
    if re.search(r"trade|buy|sell|invest|run\s+agent", text, re.IGNORECASE) and tickers:
        return "trade", tickers
    if tickers:
        return "analyze", tickers
    return "unknown", []


# ── Portfolio formatter ────────────────────────────────────────────────────────

def _format_portfolio() -> str:
    """Fetch Alpaca account data and return a markdown-formatted portfolio summary."""
    balance  = get_account_balance()
    pos_data = get_positions()
    perf     = get_performance_summary()

    if balance.get("error"):
        return f"❌ Alpaca API error: {balance['error']}"

    def fmt(n) -> str:
        try:
            return f"{float(n):,.2f}"
        except (TypeError, ValueError):
            return "N/A"

    positions = pos_data.get("positions", [])

    lines = [
        "## 📊 Portfolio Status\n",
        f"**Cash:** ${fmt(balance.get('cash'))}  "
        f"**Portfolio Value:** ${fmt(balance.get('portfolio_value'))}  "
        f"**Buying Power:** ${fmt(balance.get('buying_power'))}\n",
    ]

    if positions:
        lines.append("### Open Positions")
        for p in positions:
            pnl     = float(p.get("unrealized_pnl") or 0)
            pnl_pct = float(p.get("unrealized_pnl_pct") or 0)
            emoji   = "📈" if pnl >= 0 else "📉"
            sign    = "+" if pnl >= 0 else ""
            lines.append(
                f"- **{p['ticker']}**: {p['quantity']} shares "
                f"@ ${fmt(p.get('entry_price'))} | "
                f"Current: ${fmt(p.get('current_price'))} | "
                f"{emoji} {sign}${pnl:.2f} ({pnl_pct:.1f}%)"
            )
    else:
        lines.append("### No open positions")

    if perf.get("total_trades", 0) > 0:
        lines += [
            "\n### Performance",
            f"- **Total Trades:** {perf['total_trades']}",
            f"- **Win Rate:** {perf.get('win_rate')}%",
            f"- **Total P&L:** ${perf.get('total_pnl')}",
            f"- **Avg Return:** {perf.get('avg_return_pct')}%",
        ]

    return "\n".join(lines)


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def _dispatch_full(
    intent: str, tickers: list[str], raw_text: str, user_id: str
) -> tuple[str, bool, dict | None]:
    """
    Route a classified intent to the correct agent pipeline.

    Returns:
        (text, requires_approval, approval_context)

        requires_approval is True when a trade ticker triggered ESCALATE.
        approval_context carries the escalation details for the Teams
        Adaptive Card renderer in the channel adapter.

    user_id is threaded through for Phase 4 multi-tenancy (currently unused).
    """
    import math

    if intent == "help":
        return (
            "## 🤖 Stock Trading Agent\n\n"
            "**Commands:**\n"
            "- **Analyze AAPL** — Quick stock analysis\n"
            "- **Research NVDA** — Deep multi-agent research (news + technicals + memory)\n"
            "- **Trade AAPL MSFT TSLA** — Run trading agent on watchlist\n"
            "- **Portfolio** — Show positions and balance\n"
            "- **Reflect** — Extract lessons from trade history\n"
            "- **Monitor** — Review open positions for exits\n"
            "- **Watch AAPL NVDA** — Add tickers to proactive watchlist\n"
            "- **Earnings AAPL** — Pre-earnings thesis and estimates\n"
            "- **MTF AAPL** — Multi-timeframe analysis (15m + daily + weekly)\n"
            "- **Optimize** — Generate a portfolio rebalancing plan (requires approval)\n\n"
            "*Powered by Claude + Alpaca paper trading*"
        ), False, None

    if intent == "watch":
        if not tickers:
            return (
                "Please tell me which tickers to watch. "
                "Example: **Watch AAPL NVDA MSFT**"
            ), False, None
        added = add_to_watchlist(user_id, tickers)
        watchlist = get_watchlist(user_id)
        ticker_list = " · ".join(watchlist) if watchlist else "—"
        return (
            f"👁 **Watchlist updated** — added: {', '.join(added)}\n\n"
            f"**Your watchlist ({len(watchlist)} tickers):** {ticker_list}\n\n"
            f"*The monitor scans every 15 min during market hours (9:30–16:00 ET). "
            f"Type **Watchlist** to review or **Monitor** to scan positions now.*"
        ), False, None

    if intent == "unwatch":
        if not tickers:
            return (
                "Please tell me which tickers to remove. "
                "Example: **Unwatch AAPL**"
            ), False, None
        removed = remove_from_watchlist(user_id, tickers)
        watchlist = get_watchlist(user_id)
        if not removed:
            return (
                f"⚠️ None of those tickers were on your watchlist: "
                f"{', '.join(tickers)}"
            ), False, None
        ticker_list = " · ".join(watchlist) if watchlist else "—"
        return (
            f"✅ **Removed from watchlist:** {', '.join(removed)}\n\n"
            f"**Your watchlist ({len(watchlist)} tickers):** {ticker_list}"
        ), False, None

    if intent == "watchlist":
        watchlist = get_watchlist(user_id)
        if not watchlist:
            return (
                "📋 **Your watchlist is empty.**\n\n"
                "Add tickers with: **Watch AAPL NVDA MSFT**"
            ), False, None
        lines = [f"## 👁 Your Watchlist ({len(watchlist)} tickers)\n"]
        for ticker in watchlist:
            lines.append(f"- **{ticker}**")
        lines.append(
            "\n*Scanned every 15 min during market hours (9:30–16:00 ET). "
            "You'll be alerted when a signal fires and clears the risk gate.*"
        )
        return "\n".join(lines), False, None

    if intent == "earnings":
        from orchestrator.earnings_agent import scan_user_earnings
        scan_tickers = tickers if tickers else get_watchlist(user_id)
        if not scan_tickers:
            return (
                "📋 No tickers specified and your watchlist is empty.\n\n"
                "Try: **Earnings AAPL** or add tickers with **Watch AAPL NVDA**"
            ), False, None
        alerts = scan_user_earnings(user_id, scan_tickers)
        if not alerts:
            ticker_str = ", ".join(scan_tickers)
            return (
                f"📅 No earnings events in the next 7 days for: **{ticker_str}**\n\n"
                f"*Check back closer to the next reporting season.*"
            ), False, None
        lines = [f"## 📅 Upcoming Earnings ({len(alerts)} event(s))\n"]
        for a in alerts:
            eps_str = f"${a.eps_estimate:.2f}" if a.eps_estimate is not None else "N/A"
            rev_str = f"${a.revenue_estimate / 1e9:.1f}B" if a.revenue_estimate else "N/A"
            emoji   = "🟢" if a.sentiment == "bullish" else "🔴" if a.sentiment == "bearish" else "🟡"
            lines += [
                f"### {a.ticker} — {a.earnings_date} ({a.days_until}d away)",
                f"{emoji} **{a.sentiment.upper()}**  |  EPS Est: {eps_str}  |  Rev Est: {rev_str}",
                f"> {a.summary}",
                "",
                a.thesis,
                "",
            ]
        return "\n".join(lines), False, None

    if intent == "optimize":
        from orchestrator.portfolio_optimizer import build_rebalance_plan, format_plan_markdown
        try:
            plan = build_rebalance_plan(user_id)
            text = format_plan_markdown(plan)
            approval_context = {
                "alert_type":       "rebalance",
                "plan_id":          plan.plan_id,
                "equity":           plan.equity,
                "cash":             plan.cash,
                "trades":           [
                    {
                        "ticker":       t.ticker,
                        "side":         t.side,
                        "adjusted_qty": t.adjusted_qty,
                        "trade_value":  t.trade_value,
                        "current_pct":  t.current_pct,
                        "target_pct":   t.target_pct,
                        "drift_pct":    t.drift_pct,
                        "risk_verdict": t.risk_verdict,
                    }
                    for t in plan.trades
                ],
                "blocked":          [
                    {"ticker": b.ticker, "side": b.side, "risk_note": b.risk_note}
                    for b in plan.blocked
                ],
                "total_sell_value": plan.total_sell_value,
                "total_buy_value":  plan.total_buy_value,
                "net_cash_change":  plan.net_cash_change,
                "rationale":        plan.rationale,
            }
            return text, True, approval_context
        except ValueError as exc:
            return f"ℹ️ {exc}", False, None
        except Exception as exc:
            return f"❌ Optimizer error: {exc}", False, None

    if intent == "digest":
        from orchestrator.journal_agent import build_weekly_digest
        try:
            digest = build_weekly_digest()
            if digest.get("status") == "skipped":
                trades_available = digest.get("trades_analyzed", 0)
                return (
                    f"ℹ️ Not enough closed trades for a full digest "
                    f"(need 3, have {trades_available}). "
                    f"Close some positions first or check back after market hours."
                ), False, None
            return (
                f"📖 **Weekly Trading Digest — {digest.get('week_of', 'This Week')}**\n\n"
                f"{digest.get('summary', '')}"
            ), False, None
        except Exception as exc:
            return f"❌ Digest error: {exc}", False, None

    if intent == "mtf":
        from orchestrator.mtf_agent import analyze_ticker_mtf, analyze_tickers_mtf, format_mtf_markdown
        scan_tickers = tickers if tickers else get_watchlist(user_id)
        if not scan_tickers:
            return (
                "Please specify a ticker for MTF analysis. Example: **MTF AAPL**\n\n"
                "Or add tickers to your watchlist first with **Watch AAPL NVDA**."
            ), False, None
        if len(scan_tickers) == 1:
            result  = analyze_ticker_mtf(scan_tickers[0])
            results = [result]
        else:
            results = analyze_tickers_mtf(scan_tickers)
        return "\n\n---\n\n".join(format_mtf_markdown(r) for r in results), False, None

    if intent == "analyze" and tickers:
        return run_analysis(tickers[0]), False, None

    if intent == "research" and tickers:
        request = raw_text or f"Research {tickers[0]} and give me a detailed buy/hold/sell recommendation"
        return run_research_orchestrator(tickers[0], request), False, None

    if intent == "trade" and tickers:
        # ── Phase 3 risk gate ─────────────────────────────────────────────────
        # Fetch account once for the whole batch
        account = get_account_balance()
        equity  = account.get("equity", 0) if not account.get("error") else 0

        blocked:   list[tuple[str, object]] = []
        escalated: list[tuple[str, object]] = []
        approved:  list[tuple[str, int]]    = []

        for t in tickers:
            price_data    = get_current_price(t)
            current_price = price_data.get("current_price", 0)

            # 5% position sizing → proposed qty (at least 1 share)
            proposed_qty = max(
                math.floor(equity * 0.05 / current_price) if current_price > 0 else 1,
                1,
            )

            result = evaluate_proposal(t, proposed_qty, "buy")

            if result.verdict in (Verdict.APPROVED, Verdict.RESIZE):
                approved.append((t, result.adjusted_qty))
            elif result.verdict == Verdict.BLOCK:
                blocked.append((t, result))
            elif result.verdict == Verdict.ESCALATE:
                escalated.append((t, result))

        lines: list[str] = []

        for t, r in blocked:
            lines.append(f"🚫 **{t} BLOCKED** — {r.narrative}")

        escalation_context = None
        for t, r in escalated:
            # Persist the proposal so POST /agent/approve can resume it
            approval_id = store_pending(
                ticker    = t,
                side      = "buy",
                qty       = r.adjusted_qty,
                reason    = r.reason,
                narrative = r.narrative,
                user_id   = user_id,
            )
            lines.append(f"⚠️ **{t} ESCALATED** — Human approval required\n{r.narrative}")
            escalation_context = {
                "approval_id": approval_id,
                "ticker":      t,
                "side":        "buy",
                "qty":         r.adjusted_qty,
                "reason":      r.reason,
                "narrative":   r.narrative,
            }

        if approved:
            approved_tickers = [t for t, _ in approved]
            lines.append(run_trading_agent(approved_tickers, raw_text or None))

        if not lines:
            lines.append("No trades were executed.")

        requires_approval = len(escalated) > 0
        return "\n\n".join(lines), requires_approval, escalation_context

    if intent == "portfolio":
        return _format_portfolio(), False, None

    if intent == "reflect":
        result = reflect(min_trades=1)
        if result.get("status") == "skipped":
            return f"⚠️ {result['reason']}", False, None
        lines = [
            "## 🧠 Reflection Complete\n",
            f"**Trades Analyzed:** {result.get('trades_analyzed')}",
            f"**Lessons Extracted:** {result.get('lessons_extracted')}\n",
            "### New Lessons",
        ]
        for i, lesson in enumerate(result.get("lessons", []), 1):
            lines.append(f"{i}. {lesson}")
        lines.append(f"\n### Summary\n{result.get('summary', '')}")
        return "\n".join(lines), False, None

    if intent == "monitor":
        return monitor_positions(), False, None

    return (
        "I didn't understand that. Try:\n"
        "- **Analyze AAPL**\n"
        "- **Trade AAPL MSFT**\n"
        "- **Portfolio**\n"
        "- **Reflect**\n"
        "- **Monitor**"
    ), False, None


# ── Public entry point ─────────────────────────────────────────────────────────

def route(msg: AgentMessage) -> AgentResponse:
    """
    Main entry point for all channel adapters.

    1. Classify intent with Claude Haiku (falls back to regex on failure)
    2. Dispatch to the correct agent pipeline (trade intent passes through
       risk_agent.evaluate_proposal() before reaching run_trading_agent)
    3. Return a normalised AgentResponse

    Args:
        msg: Normalised AgentMessage from any channel adapter.

    Returns:
        AgentResponse with intent, formatted text, and approval metadata.
        requires_approval is True when any ticker triggered an ESCALATE verdict.
    """
    intent, tickers = _classify(msg.text)
    text, requires_approval, approval_context = _dispatch_full(
        intent, tickers, msg.text, msg.user_id
    )
    return AgentResponse(
        intent=intent,
        text=text,
        requires_approval=requires_approval,
        approval_context=approval_context,
    )
