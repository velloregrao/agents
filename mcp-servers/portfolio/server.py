import sys
import os
from pathlib import Path

# Point to the existing stock agent source
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from mcp.server.fastmcp import FastMCP
from stock_agent.alpaca_tools import (
    get_account_balance,
    get_positions,
    place_order,
    place_limit_order,
    get_order_history,
    cancel_order,
    close_position,
)

mcp = FastMCP("portfolio")


@mcp.tool()
def portfolio_balance() -> dict:
    """Get current Alpaca paper trading account balance, cash, buying power and portfolio value."""
    return get_account_balance()


@mcp.tool()
def portfolio_positions() -> dict:
    """Get all current open positions in the Alpaca paper trading account with P&L."""
    return get_positions()


@mcp.tool()
def order_history(limit: int = 10) -> dict:
    """Get recent order history from the Alpaca paper trading account."""
    return get_order_history()


@mcp.tool()
def buy_stock(ticker: str, quantity: int) -> dict:
    """Place a market buy order for a stock in the Alpaca paper trading account."""
    return place_order(ticker, quantity, "BUY")


@mcp.tool()
def sell_stock(ticker: str, quantity: int) -> dict:
    """Place a market sell order for a stock in the Alpaca paper trading account."""
    return place_order(ticker, quantity, "SELL")


@mcp.tool()
def close_stock_position(ticker: str) -> dict:
    """Close an entire position for a stock in the Alpaca paper trading account."""
    return close_position(ticker)


if __name__ == "__main__":
    mcp.run()
