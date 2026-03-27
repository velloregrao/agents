import sys
import os
import requests
from datetime import datetime, timedelta

sys.path.insert(0, "/Users/velloregrao/Projects/agents/stock-analysis-agent/src")

from dotenv import load_dotenv

load_dotenv("/Users/velloregrao/Projects/agents/stock-analysis-agent/.env")

import yfinance as yf
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("news")

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")


@mcp.tool()
def stock_news(ticker: str, limit: int = 5) -> dict:
    """
    Get the latest news articles for a stock ticker from Yahoo Finance.
    Returns title, publisher, link and publish time for each article.
    """
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        articles = []
        for item in news[:limit]:
            content = item.get("content", {})
            articles.append(
                {
                    "title": content.get("title", "No title"),
                    "publisher": content.get("provider", {}).get(
                        "displayName", "Unknown"
                    ),
                    "link": content.get("canonicalUrl", {}).get("url", ""),
                    "published": content.get("pubDate", ""),
                    "summary": content.get("summary", ""),
                }
            )
        return {"ticker": ticker, "article_count": len(articles), "articles": articles}
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def market_sentiment(ticker: str, company_name: str = "") -> dict:
    """
    Search Brave for recent news and sentiment about a stock.
    Returns top results with titles and descriptions to gauge market mood.
    """
    try:
        query = f"{ticker} {company_name} stock news sentiment 2026"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        }
        params = {"q": query, "count": 5, "freshness": "pw"}  # past week
        response = requests.get(
            "https://api.search.brave.com/res/v1/news/search",
            headers=headers,
            params=params,
            timeout=10,
        )
        data = response.json()
        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "source": item.get("source", ""),
                    "age": item.get("age", ""),
                    "url": item.get("url", ""),
                }
            )
        return {
            "ticker": ticker,
            "query": query,
            "result_count": len(results),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@mcp.tool()
def analyst_sentiment(ticker: str) -> dict:
    """
    Get analyst recommendations, price targets and upgrade/downgrade
    history for a stock from Yahoo Finance.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        recommendations = None
        try:
            rec = stock.recommendations
            if rec is not None and not rec.empty:
                latest = rec.tail(5)
                recommendations = latest.to_dict(orient="records")
        except Exception:
            recommendations = None

        return {
            "ticker": ticker,
            "analyst_count": info.get("numberOfAnalystOpinions"),
            "recommendation": info.get("recommendationKey", "N/A"),
            "target_mean_price": info.get("targetMeanPrice"),
            "target_high_price": info.get("targetHighPrice"),
            "target_low_price": info.get("targetLowPrice"),
            "current_price": info.get("currentPrice"),
            "upside_to_target": (
                round(
                    (
                        (info.get("targetMeanPrice", 0) - info.get("currentPrice", 0))
                        / info.get("currentPrice", 1)
                    )
                    * 100,
                    2,
                )
                if info.get("targetMeanPrice") and info.get("currentPrice")
                else None
            ),
            "recent_recommendations": recommendations,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


if __name__ == "__main__":
    mcp.run()
