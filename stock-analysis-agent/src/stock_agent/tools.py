"""Stock data tools backed by yfinance."""

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf


def get_stock_info(ticker: str) -> dict:
    """Fetch company overview, sector, market cap, and key ratios."""
    stock = yf.Ticker(ticker)
    info = stock.info
    return {
        "ticker": ticker.upper(),
        "name": info.get("longName", "N/A"),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "country": info.get("country", "N/A"),
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "employees": info.get("fullTimeEmployees"),
        "description": (info.get("longBusinessSummary", "") or "")[:500],
        "website": info.get("website", "N/A"),
        "exchange": info.get("exchange", "N/A"),
        "currency": info.get("currency", "USD"),
    }


def get_current_price(ticker: str) -> dict:
    """Fetch real-time/last price and intraday movement."""
    stock = yf.Ticker(ticker)
    info = stock.info
    hist = stock.history(period="2d")

    current = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

    change = None
    change_pct = None
    if current and prev_close:
        change = round(current - prev_close, 4)
        change_pct = round((change / prev_close) * 100, 2)

    return {
        "ticker": ticker.upper(),
        "current_price": current,
        "previous_close": prev_close,
        "change": change,
        "change_pct": change_pct,
        "day_high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
        "day_low": info.get("dayLow") or info.get("regularMarketDayLow"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "volume": info.get("volume") or info.get("regularMarketVolume"),
        "avg_volume": info.get("averageVolume"),
        "market_state": info.get("marketState", "N/A"),
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def get_price_history(ticker: str, period: str = "6mo") -> dict:
    """
    Fetch OHLCV history.
    period options: 1mo, 3mo, 6mo, 1y, 2y, 5y
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)

    if hist.empty:
        return {"error": f"No history found for {ticker}"}

    # Summarize key price points
    prices = hist["Close"].dropna()
    volumes = hist["Volume"].dropna()

    return {
        "ticker": ticker.upper(),
        "period": period,
        "start_date": hist.index[0].strftime("%Y-%m-%d"),
        "end_date": hist.index[-1].strftime("%Y-%m-%d"),
        "start_price": round(float(prices.iloc[0]), 4),
        "end_price": round(float(prices.iloc[-1]), 4),
        "period_return_pct": round(
            ((prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0]) * 100, 2
        ),
        "period_high": round(float(prices.max()), 4),
        "period_low": round(float(prices.min()), 4),
        "avg_price": round(float(prices.mean()), 4),
        "price_std": round(float(prices.std()), 4),
        "avg_volume": round(float(volumes.mean()), 0),
        "trading_days": len(hist),
    }


def get_technical_indicators(ticker: str, period: str = "6mo") -> dict:
    """
    Calculate SMA, EMA, RSI, MACD, and Bollinger Bands.
    """
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period)

    if hist.empty or len(hist) < 20:
        return {"error": f"Insufficient data for technical analysis of {ticker}"}

    close = hist["Close"].dropna()
    current_price = float(close.iloc[-1])

    # Simple Moving Averages
    sma_20 = round(float(close.rolling(20).mean().iloc[-1]), 4)
    sma_50 = round(float(close.rolling(50).mean().iloc[-1]), 4) if len(close) >= 50 else None
    sma_200 = round(float(close.rolling(200).mean().iloc[-1]), 4) if len(close) >= 200 else None

    # Exponential Moving Averages
    ema_12 = round(float(close.ewm(span=12, adjust=False).mean().iloc[-1]), 4)
    ema_26 = round(float(close.ewm(span=26, adjust=False).mean().iloc[-1]), 4)

    # MACD
    macd_line = round(ema_12 - ema_26, 4)
    macd_signal = round(
        float(
            pd.Series([ema_12 - ema_26])
            .ewm(span=9, adjust=False)
            .mean()
            .iloc[-1]
        ),
        4,
    )

    # RSI (14-period)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = round(float(100 - (100 / (1 + rs.iloc[-1]))), 2)

    # Bollinger Bands (20-period, 2 std)
    bb_middle = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = round(float((bb_middle + 2 * bb_std).iloc[-1]), 4)
    bb_lower = round(float((bb_middle - 2 * bb_std).iloc[-1]), 4)
    bb_middle_val = round(float(bb_middle.iloc[-1]), 4)

    # Trend signals
    signals = []
    if sma_50 and current_price > sma_50:
        signals.append("Price above 50-SMA (bullish)")
    elif sma_50:
        signals.append("Price below 50-SMA (bearish)")
    if rsi > 70:
        signals.append(f"RSI {rsi} — overbought territory")
    elif rsi < 30:
        signals.append(f"RSI {rsi} — oversold territory")
    else:
        signals.append(f"RSI {rsi} — neutral")
    if macd_line > macd_signal:
        signals.append("MACD above signal line (bullish momentum)")
    else:
        signals.append("MACD below signal line (bearish momentum)")
    if current_price > bb_upper:
        signals.append("Price above upper Bollinger Band (potential reversal)")
    elif current_price < bb_lower:
        signals.append("Price below lower Bollinger Band (potential reversal)")

    return {
        "ticker": ticker.upper(),
        "current_price": round(current_price, 4),
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "rsi_14": rsi,
        "bollinger_upper": bb_upper,
        "bollinger_middle": bb_middle_val,
        "bollinger_lower": bb_lower,
        "signals": signals,
    }


def get_fundamentals(ticker: str) -> dict:
    """Fetch valuation ratios, earnings, and financial health metrics."""
    stock = yf.Ticker(ticker)
    info = stock.info

    return {
        "ticker": ticker.upper(),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "ev_to_revenue": info.get("enterpriseToRevenue"),
        "eps_ttm": info.get("trailingEps"),
        "eps_forward": info.get("forwardEps"),
        "revenue_ttm": info.get("totalRevenue"),
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "profit_margin": info.get("profitMargins"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "free_cash_flow": info.get("freeCashflow"),
        "dividend_yield": info.get("dividendYield"),
        "payout_ratio": info.get("payoutRatio"),
        "beta": info.get("beta"),
        "analyst_target_price": info.get("targetMeanPrice"),
        "analyst_recommendation": info.get("recommendationKey"),
        "analyst_count": info.get("numberOfAnalystOpinions"),
    }


# Tool definitions for the Claude API
TOOL_DEFINITIONS = [
    {
        "name": "get_stock_info",
        "description": (
            "Fetch company overview including name, sector, industry, market cap, "
            "number of employees, and business description for a given ticker symbol."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol, e.g. AAPL, MSFT, TSLA",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_current_price",
        "description": (
            "Fetch the current/last price, day change, 52-week high/low, volume, "
            "and market state for a given ticker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "Fetch historical OHLCV price data and compute summary stats "
            "(start/end price, period return, high/low, avg volume) for a given period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "period": {
                    "type": "string",
                    "description": "History period: 1mo, 3mo, 6mo, 1y, 2y, 5y",
                    "enum": ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": (
            "Calculate technical indicators: SMA (20, 50, 200), EMA (12, 26), "
            "MACD, RSI (14), and Bollinger Bands. Returns signal interpretations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "period": {
                    "type": "string",
                    "description": "History period for calculation: 6mo, 1y, 2y",
                    "enum": ["3mo", "6mo", "1y", "2y"],
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_fundamentals",
        "description": (
            "Fetch fundamental valuation ratios (P/E, P/B, PEG, EV/EBITDA), "
            "profitability margins, balance sheet health (D/E, current ratio), "
            "dividend info, beta, and analyst recommendations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"}
            },
            "required": ["ticker"],
        },
    },
]

# Map tool names to functions
TOOL_FUNCTIONS = {
    "get_stock_info": get_stock_info,
    "get_current_price": get_current_price,
    "get_price_history": get_price_history,
    "get_technical_indicators": get_technical_indicators,
    "get_fundamentals": get_fundamentals,
}


def execute_tool(name: str, tool_input: dict) -> str:
    """Execute a tool by name and return JSON-serialized result."""
    fn = TOOL_FUNCTIONS.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**tool_input)
        return json.dumps(result, default=str, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
