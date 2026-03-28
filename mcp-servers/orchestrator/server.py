"""
mcp-servers/orchestrator/server.py

MCP server exposing Phase 6–9 orchestrator capabilities.

Tools:
    earnings_analysis      — upcoming earnings thesis for one or more tickers
    mtf_analysis           — multi-timeframe (15m/daily/weekly) signal analysis
    mtf_analysis_batch     — MTF analysis across a list of tickers
    optimize_portfolio     — generate a rebalancing plan vs target allocation
    target_allocation      — view the current target allocation config
    sync_trade_journal     — close resolved Alpaca positions in the trade journal
    weekly_trading_digest  — run reflection and return lessons + performance digest

All tools import directly from the orchestrator Python modules — no HTTP round-trip
to the FastAPI server required. This means the MCP server works standalone as long
as the environment variables (ANTHROPIC_API_KEY, ALPACA_API_KEY, etc.) are set.

Usage (Claude Desktop config):
    {
      "mcpServers": {
        "orchestrator": {
          "command": "python",
          "args": ["/path/to/agents/mcp-servers/orchestrator/server.py"]
        }
      }
    }
"""

import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# server.py is at:  agents/mcp-servers/orchestrator/server.py
# agents root is 3 levels up
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT))                               # for orchestrator.*
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))  # for stock_agent.*

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from mcp.server.fastmcp import FastMCP

# ── Lazy imports — each tool imports its own deps on first call so the server
#    starts instantly even if some optional deps are missing.

mcp = FastMCP("orchestrator")

_MCP_USER = "mcp"   # synthetic user_id for all MCP-originated requests


# ── Tool 1: Earnings analysis ──────────────────────────────────────────────────

@mcp.tool()
def earnings_analysis(tickers: list[str], days_ahead: int = 7) -> dict:
    """
    Get upcoming earnings dates, analyst estimates, and a pre-earnings thesis
    for one or more stock tickers.

    Returns a list of earnings alerts — each with earnings date, EPS estimate,
    revenue estimate, analyst rating, and a Sonnet-generated investment thesis.

    Args:
        tickers:    List of stock symbols e.g. ["AAPL", "NVDA"]
        days_ahead: How many calendar days to look ahead (default 7)
    """
    from orchestrator.earnings_agent import scan_user_earnings
    alerts = scan_user_earnings(_MCP_USER, [t.upper() for t in tickers], days_ahead)
    if not alerts:
        return {
            "count":   0,
            "message": f"No earnings events in the next {days_ahead} days for: {', '.join(tickers)}",
            "alerts":  [],
        }
    return {
        "count":  len(alerts),
        "alerts": [
            {
                "ticker":           a.ticker,
                "earnings_date":    a.earnings_date,
                "days_until":       a.days_until,
                "eps_estimate":     a.eps_estimate,
                "eps_range":        f"{a.eps_low} – {a.eps_high}" if a.eps_low and a.eps_high else None,
                "revenue_estimate": a.revenue_estimate,
                "analyst_rating":   a.analyst_rating,
                "analyst_target":   a.analyst_target,
                "sentiment":        a.sentiment,
                "summary":          a.summary,
                "thesis":           a.thesis,
            }
            for a in alerts
        ],
    }


# ── Tool 2: MTF analysis (single ticker) ──────────────────────────────────────

@mcp.tool()
def mtf_analysis(ticker: str) -> dict:
    """
    Multi-timeframe technical analysis for a single stock ticker.

    Runs the same RSI/EMA/SMA scoring across three timeframes simultaneously:
      - 15-minute (intraday momentum)
      - Daily (medium-term trend)
      - Weekly (macro trend)

    A signal fires when 2 or more timeframes align bullish or bearish.
    Returns structured scores for each timeframe plus an overall alignment verdict
    and a narrative explanation when a signal fires.

    Args:
        ticker: Stock symbol e.g. "AAPL"
    """
    from orchestrator.mtf_agent import analyze_ticker_mtf, format_mtf_markdown
    result = analyze_ticker_mtf(ticker.upper())
    return {
        "ticker":         result.ticker,
        "price":          result.price,
        "alignment":      result.alignment,
        "aligned_count":  result.aligned_count,
        "alignment_type": result.alignment_type,
        "signal_fired":   result.signal_fired,
        "narrative":      result.narrative,
        "summary":        result.summary,
        "timeframes": [
            {
                "name":      tf.name,
                "label":     tf.label,
                "direction": tf.direction,
                "score":     tf.score,
                "rsi":       tf.rsi,
                "error":     tf.error,
            }
            for tf in result.timeframes
        ],
        "markdown": format_mtf_markdown(result),
    }


# ── Tool 3: MTF analysis (batch) ──────────────────────────────────────────────

@mcp.tool()
def mtf_analysis_batch(tickers: list[str]) -> list[dict]:
    """
    Multi-timeframe technical analysis for a list of stock tickers.

    Runs all tickers in parallel and returns one result per ticker.
    Only returns tickers where a signal fired (2/3 or 3/3 timeframes aligned)
    unless return_all is True.

    Use this to scan a watchlist for aligned signals across multiple names.

    Args:
        tickers: List of stock symbols e.g. ["AAPL", "NVDA", "MSFT"]
    """
    from orchestrator.mtf_agent import analyze_tickers_mtf, format_mtf_markdown
    results = analyze_tickers_mtf([t.upper() for t in tickers])
    return [
        {
            "ticker":         r.ticker,
            "price":          r.price,
            "alignment":      r.alignment,
            "aligned_count":  r.aligned_count,
            "alignment_type": r.alignment_type,
            "signal_fired":   r.signal_fired,
            "narrative":      r.narrative,
            "summary":        r.summary,
            "markdown":       format_mtf_markdown(r),
        }
        for r in results
    ]


# ── Tool 4: Portfolio optimizer ────────────────────────────────────────────────

@mcp.tool()
def optimize_portfolio() -> dict:
    """
    Generate a portfolio rebalancing plan against the target allocation config.

    Computes which positions are over- or under-allocated relative to the targets
    in config/target_allocation.yaml, runs every proposal through the risk gate,
    refines buys for available cash, and generates a Sonnet rationale.

    IMPORTANT: This tool generates a plan and queues it for Teams approval —
    it does NOT execute any trades. All trades require explicit human approval
    via the Teams bot before execution.

    Returns the plan details including plan_id, proposed trades, blocked trades,
    and the rationale. The plan_id can be used to reference the plan later.
    """
    from orchestrator.portfolio_optimizer import build_rebalance_plan, format_plan_markdown
    try:
        plan = build_rebalance_plan(_MCP_USER)
        return {
            "plan_id":          plan.plan_id,
            "equity":           plan.equity,
            "cash":             plan.cash,
            "total_sell_value": plan.total_sell_value,
            "total_buy_value":  plan.total_buy_value,
            "net_cash_change":  plan.net_cash_change,
            "rationale":        plan.rationale,
            "trades_count":     len(plan.trades),
            "blocked_count":    len(plan.blocked),
            "trades": [
                {
                    "ticker":       t.ticker,
                    "side":         t.side,
                    "shares":       t.adjusted_qty,
                    "value":        t.trade_value,
                    "current_pct":  round(t.current_pct * 100, 1),
                    "target_pct":   round(t.target_pct  * 100, 1),
                    "drift_pct":    round(t.drift_pct   * 100, 1),
                    "risk_verdict": t.risk_verdict,
                }
                for t in plan.trades
            ],
            "blocked": [
                {"ticker": b.ticker, "side": b.side, "reason": b.risk_note}
                for b in plan.blocked
            ],
            "markdown":   format_plan_markdown(plan),
            "note":       "Plan queued for Teams approval. No trades will execute until approved.",
        }
    except ValueError as e:
        return {"error": str(e), "trades": [], "blocked": []}


# ── Tool 5: Target allocation config ──────────────────────────────────────────

@mcp.tool()
def target_allocation() -> dict:
    """
    View the current target portfolio allocation from config/target_allocation.yaml.

    Shows the desired percentage for each position, total allocated percentage,
    remaining cash percentage, and optimizer settings (min trade value, cash buffer).

    Use this before running optimize_portfolio to understand what trades will be proposed.
    """
    from orchestrator.portfolio_optimizer import load_target_allocation
    cfg    = load_target_allocation()
    allocs = cfg.get("allocations", {})
    total  = sum(allocs.values())
    return {
        "allocations": {
            ticker: {
                "target_pct":         round(pct * 100, 1),
                "target_pct_decimal": pct,
            }
            for ticker, pct in allocs.items()
        },
        "total_allocated_pct":  round(total * 100, 1),
        "cash_remainder_pct":   round((1.0 - total) * 100, 1),
        "settings":             cfg.get("settings", {}),
    }


# ── Tool 6: Journal sync ───────────────────────────────────────────────────────

@mcp.tool()
def sync_trade_journal() -> dict:
    """
    Sync the trade journal with current Alpaca positions.

    Compares open trades in the local journal DB against live Alpaca positions.
    Any trade whose ticker is no longer held is automatically closed with the
    current market price as the exit price estimate.

    Run this after closing positions in Alpaca to keep the journal current
    before running a reflection or viewing performance stats.

    Returns a count of trades closed, skipped (no price data), and errors.
    """
    from orchestrator.journal_agent import sync_closed_trades
    result = sync_closed_trades()
    return {
        "synced":  result["synced"],
        "skipped": result["skipped"],
        "errors":  result["errors"],
        "details": result["details"],
        "message": (
            f"Closed {result['synced']} trade(s)."
            if result["synced"] > 0
            else "No new positions to close — journal is up to date."
        ),
    }


# ── Tool 7: Weekly trading digest ─────────────────────────────────────────────

@mcp.tool()
def weekly_trading_digest() -> dict:
    """
    Generate a weekly trading reflection and return extracted lessons.

    Analyzes the last 20 closed trades using Claude Sonnet to extract specific,
    measurable, falsifiable trading rules. Returns new lessons not already in
    the lessons library, plus overall performance stats for the period.

    Requires at least 3 closed trades. Run sync_trade_journal first to ensure
    all closed positions are recorded before reflecting.

    Returns status ('completed' or 'skipped'), lessons list, summary, and
    full performance statistics.
    """
    from orchestrator.journal_agent import build_weekly_digest
    return build_weekly_digest()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
