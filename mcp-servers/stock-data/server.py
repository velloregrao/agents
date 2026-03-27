import sys
import os
from pathlib import Path

# Point to the existing stock agent source
_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_AGENTS_ROOT / "stock-analysis-agent" / "src"))

from dotenv import load_dotenv
load_dotenv(_AGENTS_ROOT / "stock-analysis-agent" / ".env")

from mcp.server.fastmcp import FastMCP
from stock_agent.tools import (
    get_stock_info,
    get_current_price,
    get_technical_indicators,
    get_fundamentals,
)

# Create the MCP server
mcp = FastMCP("stock-data")


@mcp.tool()
def stock_info(ticker: str) -> dict:
    """Get company overview, sector, market cap and basic info for a stock ticker."""
    return get_stock_info(ticker)


@mcp.tool()
def current_price(ticker: str) -> dict:
    """Get the current live price, volume, and intraday change for a stock ticker."""
    return get_current_price(ticker)


@mcp.tool()
def technical_indicators(ticker: str, period: str = "6mo") -> dict:
    """
    Get technical indicators for a stock: RSI, MACD, Bollinger Bands,
    moving averages (SMA20, SMA50), and volume analysis.
    Period options: 1mo, 3mo, 6mo, 1y, 2y
    """
    return get_technical_indicators(ticker, period)


@mcp.tool()
def fundamentals(ticker: str) -> dict:
    """
    Get fundamental analysis for a stock: P/E ratio, revenue, earnings growth,
    profit margins, debt/equity, analyst ratings and price targets.
    """
    return get_fundamentals(ticker)


if __name__ == "__main__":
    mcp.run()
