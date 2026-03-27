import sys
import os
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from mcp.server.fastmcp import FastMCP
from stock_agent.memory import (
    initialize_db,
    store_trade,
    get_open_trades,
    get_recent_trades,
    get_lessons,
    get_performance_summary,
)

# Ensure DB is initialized
initialize_db()

mcp = FastMCP("memory")

@mcp.tool()
def open_trades() -> dict:
    """Get all currently open paper trades being tracked in memory."""
    return get_open_trades()

@mcp.tool()
def recent_trades(limit: int = 10) -> dict:
    """Get recent closed and open trades from memory with P&L and reasoning."""
    return get_recent_trades(limit=limit)

@mcp.tool()
def trading_lessons(ticker: str = None, sector: str = None) -> dict:
    """
    Get lessons learned from past trades. Optionally filter by ticker or sector.
    These lessons inform future trading decisions.
    """
    return get_lessons(ticker=ticker, sector=sector)

@mcp.tool()
def performance_summary() -> dict:
    """
    Get overall trading performance: total trades, win rate,
    total P&L, average return, and best/worst trades.
    """
    return get_performance_summary()

@mcp.tool()
def record_trade(
    order_id: str,
    ticker: str,
    side: str,
    quantity: float,
    entry_price: float,
    entry_rsi: float = None,
    sector: str = None,
    reasoning: str = None
) -> dict:
    """
    Record a new paper trade in memory after it has been placed.
    Side must be BUY or SELL.
    """
    return store_trade(
        order_id=order_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        entry_rsi=entry_rsi,
        entry_vix=None,
        sector=sector,
        reasoning=reasoning
    )

if __name__ == "__main__":
    mcp.run()
