"""Functional tests for api.py — uses FastAPI TestClient, mocks all external deps."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    """TestClient with isolated DB and patched env."""
    from stock_agent.api import app
    return TestClient(app)


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "stock-agent-api"
    assert "version" in data


# ── Portfolio ─────────────────────────────────────────────────────────────────

@patch("stock_agent.api.get_account_balance", return_value={"cash": 100000, "portfolio_value": 100000, "buying_power": 100000})
@patch("stock_agent.api.get_positions", return_value={"positions": []})
@patch("stock_agent.api.get_open_trades", return_value={"open_trades": [], "total": 0})
@patch("stock_agent.api.get_performance_summary", return_value={"total_trades": 0, "win_rate": 0})
def test_portfolio_returns_expected_shape(mock_perf, mock_open, mock_pos, mock_bal, client):
    response = client.get("/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "balance" in data
    assert "positions" in data
    assert "open_trades" in data
    assert "performance" in data


# ── Analyze ───────────────────────────────────────────────────────────────────

@patch("stock_agent.api.get_stock_info", return_value={"name": "Apple Inc.", "sector": "Technology"})
@patch("stock_agent.api.get_current_price", return_value={"current_price": 175.0})
@patch("stock_agent.api.get_technical_indicators", return_value={"rsi_14": 55.0})
@patch("stock_agent.api.get_fundamentals", return_value={"pe_ratio": 28.5})
@patch("stock_agent.api._client")
def test_analyze_returns_result(mock_claude, *_):
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "Bullish on AAPL — strong fundamentals."
    mock_claude.messages.create.return_value.content = [mock_block]
    from stock_agent.api import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    response = c.post("/analyze", json={"ticker": "AAPL"})
    assert response.status_code == 200
    assert "result" in response.json()
    assert len(response.json()["result"]) > 0


@patch("stock_agent.api.get_stock_info", side_effect=Exception("yfinance timeout"))
def test_analyze_returns_500_on_error(mock_info, client):
    response = client.post("/analyze", json={"ticker": "AAPL"})
    assert response.status_code == 500
    assert "yfinance timeout" in response.json()["detail"]


def test_analyze_missing_ticker(client):
    response = client.post("/analyze", json={})
    assert response.status_code == 422  # Pydantic validation error


# ── Research ──────────────────────────────────────────────────────────────────

@patch("stock_agent.api._client")
def test_research_agentic_loop_completes(mock_claude):
    """Simulate two turns: tool call then end_turn."""
    # Turn 1: model calls get_positions
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tu_1"
    tool_block.name = "get_positions"
    tool_block.input = {}

    turn1 = MagicMock()
    turn1.stop_reason = "tool_use"
    turn1.content = [tool_block]

    # Turn 2: model returns final answer
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "📦 Current Position: None\n\nBUY AAPL — strong momentum."

    turn2 = MagicMock()
    turn2.stop_reason = "end_turn"
    turn2.content = [text_block]

    mock_claude.messages.create.side_effect = [turn1, turn2]

    with patch("stock_agent.api.get_positions", return_value={"positions": []}):
        from stock_agent.api import app
        from fastapi.testclient import TestClient
        response = TestClient(app).post("/research", json={"ticker": "AAPL"})

    assert response.status_code == 200
    assert "Current Position" in response.json()["result"]


# ── Monitor ───────────────────────────────────────────────────────────────────

@patch("stock_agent.api.monitor_positions", return_value="No action needed.")
def test_monitor_returns_result(mock_monitor, client):
    response = client.post("/monitor", json={})
    assert response.status_code == 200
    assert response.json()["result"] == "No action needed."
