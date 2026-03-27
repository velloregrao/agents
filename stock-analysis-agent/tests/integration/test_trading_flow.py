"""
Integration tests — hit real APIs (Claude, Alpaca, yfinance).
Skipped by default. Run with: pytest --integration
Requires real credentials in environment.
"""

import pytest


@pytest.mark.integration
def test_health_endpoint_live():
    from fastapi.testclient import TestClient
    from stock_agent.api import app
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.integration
def test_analyze_aapl_live():
    """Full analyze call — hits yfinance + Claude API."""
    from fastapi.testclient import TestClient
    from stock_agent.api import app
    response = TestClient(app).post("/analyze", json={"ticker": "AAPL"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert len(result) > 100
    # Claude should mention the ticker somewhere in the analysis
    assert "AAPL" in result or "Apple" in result


@pytest.mark.integration
def test_portfolio_live():
    """Hits real Alpaca paper trading API."""
    from fastapi.testclient import TestClient
    from stock_agent.api import app
    response = TestClient(app).get("/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "balance" in data
    # Real account should have buying_power
    assert data["balance"].get("buying_power") is not None
