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
from stock_agent.agent import run_analysis
from stock_agent.trading_agent import run_trading_agent, monitor_positions
from stock_agent.reflection import reflect
from stock_agent.research import run_research_orchestrator
from stock_agent.alpaca_tools import get_account_balance, get_positions
from stock_agent.memory import get_performance_summary

# ── Model constants ────────────────────────────────────────────────────────────

HAIKU  = "claude-haiku-4-5-20251001"   # routing, classification, formatting
SONNET = "claude-sonnet-4-6"           # analysis, risk narrative, trade thesis

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Haiku intent classifier ────────────────────────────────────────────────────

_VALID_INTENTS = frozenset({
    "analyze", "research", "trade", "portfolio",
    "reflect", "monitor", "help", "unknown",
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
  help      → greeting, or asking what the bot can do
  unknown   → message does not match any category

Ticker extraction rules:
  - Extract real stock symbols only (1–5 uppercase letters, e.g. AAPL, NVDA, MSFT)
  - Never extract common English words as tickers
  - Infer symbols from company names: Apple→AAPL, Nvidia→NVDA, Microsoft→MSFT, Tesla→TSLA

Disambiguation:
  - analyze vs research: research implies a recommendation or decision is needed
  - trade vs analyze: trade implies the user wants orders placed, not just information

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
    "RUN", "CHECK", "MY",
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

def _dispatch(intent: str, tickers: list[str], raw_text: str, user_id: str) -> str:
    """
    Route a classified intent to the correct agent pipeline.

    user_id is accepted and threaded through for Phase 4 multi-tenancy.
    Pipeline functions currently ignore it — Phase 4 adds per-user DB scoping.

    Phase 3 will insert risk_agent.evaluate_proposal() here before any
    trade execution reaches run_trading_agent().
    """
    if intent == "help":
        return (
            "## 🤖 Stock Trading Agent\n\n"
            "**Commands:**\n"
            "- **Analyze AAPL** — Quick stock analysis\n"
            "- **Research NVDA** — Deep multi-agent research (news + technicals + memory)\n"
            "- **Trade AAPL MSFT TSLA** — Run trading agent on watchlist\n"
            "- **Portfolio** — Show positions and balance\n"
            "- **Reflect** — Extract lessons from trade history\n"
            "- **Monitor** — Review open positions for exits\n\n"
            "*Powered by Claude + Alpaca paper trading*"
        )

    if intent == "analyze" and tickers:
        return run_analysis(tickers[0])

    if intent == "research" and tickers:
        request = raw_text or f"Research {tickers[0]} and give me a detailed buy/hold/sell recommendation"
        return run_research_orchestrator(tickers[0], request)

    if intent == "trade" and tickers:
        # Phase 3: risk_agent.evaluate_proposal() will gate this call
        return run_trading_agent(tickers, raw_text or None)

    if intent == "portfolio":
        return _format_portfolio()

    if intent == "reflect":
        result = reflect(min_trades=1)
        if result.get("status") == "skipped":
            return f"⚠️ {result['reason']}"
        lines = [
            "## 🧠 Reflection Complete\n",
            f"**Trades Analyzed:** {result.get('trades_analyzed')}",
            f"**Lessons Extracted:** {result.get('lessons_extracted')}\n",
            "### New Lessons",
        ]
        for i, lesson in enumerate(result.get("lessons", []), 1):
            lines.append(f"{i}. {lesson}")
        lines.append(f"\n### Summary\n{result.get('summary', '')}")
        return "\n".join(lines)

    if intent == "monitor":
        return monitor_positions()

    return (
        "I didn't understand that. Try:\n"
        "- **Analyze AAPL**\n"
        "- **Trade AAPL MSFT**\n"
        "- **Portfolio**\n"
        "- **Reflect**\n"
        "- **Monitor**"
    )


# ── Public entry point ─────────────────────────────────────────────────────────

def route(msg: AgentMessage) -> AgentResponse:
    """
    Main entry point for all channel adapters.

    1. Classify intent with Claude Haiku (falls back to regex on failure)
    2. Dispatch to the correct agent pipeline
    3. Return a normalised AgentResponse

    Args:
        msg: Normalised AgentMessage from any channel adapter.

    Returns:
        AgentResponse with intent, formatted text, and approval metadata.
    """
    intent, tickers = _classify(msg.text)
    text = _dispatch(intent, tickers, msg.text, msg.user_id)
    return AgentResponse(intent=intent, text=text)
