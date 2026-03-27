"""Unit tests for tools.py — mocks yfinance so no network calls needed."""

import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from stock_agent.tools import (
    get_stock_info,
    get_current_price,
    get_technical_indicators,
    get_fundamentals,
    execute_tool,
)


MOCK_INFO = {
    "longName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "country": "United States",
    "marketCap": 3_000_000_000_000,
    "currentPrice": 175.0,
    "previousClose": 170.0,
    "dayHigh": 177.0,
    "dayLow": 173.0,
    "fiftyTwoWeekHigh": 200.0,
    "fiftyTwoWeekLow": 130.0,
    "volume": 50_000_000,
    "averageVolume": 55_000_000,
    "trailingPE": 28.5,
    "forwardPE": 25.0,
    "beta": 1.2,
    "recommendationKey": "buy",
}


@patch("stock_agent.tools.yf.Ticker")
def test_get_stock_info_returns_expected_fields(mock_ticker):
    mock_ticker.return_value.info = MOCK_INFO
    result = get_stock_info("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["name"] == "Apple Inc."
    assert result["sector"] == "Technology"
    assert result["market_cap"] == 3_000_000_000_000


@patch("stock_agent.tools.yf.Ticker")
def test_get_stock_info_uppercases_ticker(mock_ticker):
    mock_ticker.return_value.info = MOCK_INFO
    result = get_stock_info("aapl")
    assert result["ticker"] == "AAPL"


@patch("stock_agent.tools.yf.Ticker")
def test_get_current_price_calculates_change(mock_ticker):
    mock_ticker.return_value.info = MOCK_INFO
    mock_ticker.return_value.history.return_value = pd.DataFrame()
    result = get_current_price("AAPL")
    assert result["current_price"] == 175.0
    assert result["change"] == pytest.approx(5.0, abs=0.01)
    assert result["change_pct"] == pytest.approx(2.94, abs=0.01)


@patch("stock_agent.tools.yf.Ticker")
def test_get_technical_indicators_rsi_neutral(mock_ticker):
    """Build a flat price series — RSI should land in neutral zone."""
    prices = pd.Series([100.0 + (i % 3) for i in range(60)])
    index = pd.date_range("2025-01-01", periods=60)
    hist = pd.DataFrame({"Close": prices.values}, index=index)
    mock_ticker.return_value.history.return_value = hist
    result = get_technical_indicators("AAPL", "6mo")
    assert "rsi_14" in result
    assert 0 < result["rsi_14"] < 100
    assert "signals" in result
    assert len(result["signals"]) > 0


@patch("stock_agent.tools.yf.Ticker")
def test_get_technical_indicators_insufficient_data(mock_ticker):
    hist = pd.DataFrame({"Close": [100.0] * 5})
    mock_ticker.return_value.history.return_value = hist
    result = get_technical_indicators("AAPL", "6mo")
    assert "error" in result


@patch("stock_agent.tools.yf.Ticker")
def test_get_fundamentals_returns_ratios(mock_ticker):
    mock_ticker.return_value.info = MOCK_INFO
    result = get_fundamentals("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["pe_ratio"] == 28.5
    assert result["beta"] == 1.2
    assert result["analyst_recommendation"] == "buy"


def test_execute_tool_unknown_name():
    result = execute_tool("nonexistent_tool", {})
    import json
    data = json.loads(result)
    assert "error" in data


@patch("stock_agent.tools.yf.Ticker")
def test_execute_tool_dispatches_correctly(mock_ticker):
    mock_ticker.return_value.info = MOCK_INFO
    import json
    result = execute_tool("get_stock_info", {"ticker": "AAPL"})
    data = json.loads(result)
    assert data["ticker"] == "AAPL"
