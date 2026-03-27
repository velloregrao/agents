"""Unit tests for memory.py — all run against an isolated temp DB."""

import pytest
from stock_agent.memory import (
    store_trade,
    close_trade,
    get_open_trades,
    get_recent_trades,
    get_performance_summary,
    store_lessons,
    get_lessons,
)


def test_store_trade_returns_success(test_db):
    result = store_trade(
        order_id="test-001",
        ticker="AAPL",
        side="BUY",
        quantity=10,
        entry_price=150.00,
    )
    assert result["status"] == "stored"
    assert result["order_id"] == "test-001"


def test_stored_trade_appears_in_open_trades(test_db):
    store_trade(order_id="test-002", ticker="MSFT", side="BUY", quantity=5, entry_price=300.00)
    result = get_open_trades()
    tickers = [t["ticker"] for t in result["open_trades"]]
    assert "MSFT" in tickers


def test_ticker_stored_uppercase(test_db):
    store_trade(order_id="test-003", ticker="tsla", side="buy", quantity=2, entry_price=200.00)
    result = get_open_trades()
    tickers = [t["ticker"] for t in result["open_trades"]]
    assert "TSLA" in tickers
    assert "tsla" not in tickers


def test_duplicate_order_id_ignored(test_db):
    store_trade(order_id="dup-001", ticker="AAPL", side="BUY", quantity=1, entry_price=150.00)
    store_trade(order_id="dup-001", ticker="AAPL", side="BUY", quantity=1, entry_price=155.00)
    result = get_open_trades()
    matching = [t for t in result["open_trades"] if t["order_id"] == "dup-001"]
    assert len(matching) == 1


def test_close_trade_calculates_pnl_correctly(test_db):
    store_trade(order_id="pnl-001", ticker="AAPL", side="BUY", quantity=10, entry_price=100.00)
    result = close_trade(order_id="pnl-001", exit_price=110.00)
    assert result["pnl"] == 100.00       # (110 - 100) * 10
    assert result["pnl_pct"] == 10.0     # 10% gain


def test_close_trade_negative_pnl(test_db):
    store_trade(order_id="loss-001", ticker="NVDA", side="BUY", quantity=5, entry_price=200.00)
    result = close_trade(order_id="loss-001", exit_price=180.00)
    assert result["pnl"] == -100.00      # (180 - 200) * 5
    assert result["pnl_pct"] == -10.0


def test_close_trade_moves_to_closed(test_db):
    store_trade(order_id="close-001", ticker="AAPL", side="BUY", quantity=1, entry_price=100.00)
    close_trade(order_id="close-001", exit_price=120.00)
    open_result = get_open_trades()
    open_ids = [t["order_id"] for t in open_result["open_trades"]]
    assert "close-001" not in open_ids
    closed_result = get_recent_trades()
    closed_ids = [t["order_id"] for t in closed_result["trades"]]
    assert "close-001" in closed_ids


def test_close_nonexistent_trade_returns_error(test_db):
    result = close_trade(order_id="nonexistent", exit_price=100.00)
    assert "error" in result


def test_performance_summary_win_rate(test_db):
    store_trade(order_id="w1", ticker="AAPL", side="BUY", quantity=1, entry_price=100.00)
    store_trade(order_id="w2", ticker="MSFT", side="BUY", quantity=1, entry_price=100.00)
    store_trade(order_id="l1", ticker="TSLA", side="BUY", quantity=1, entry_price=100.00)
    close_trade("w1", exit_price=120.00)
    close_trade("w2", exit_price=115.00)
    close_trade("l1", exit_price=90.00)
    summary = get_performance_summary()
    assert summary["total_trades"] == 3
    assert summary["win_rate"] == pytest.approx(66.7, abs=0.1)


def test_performance_summary_empty_db(test_db):
    summary = get_performance_summary()
    assert summary["total_trades"] == 0
    assert summary["win_rate"] == 0


def test_store_and_retrieve_lessons(test_db):
    store_lessons(["Buy when RSI < 30", "Avoid high VIX entries"])
    result = get_lessons()
    lesson_texts = [l["lesson"] for l in result["lessons"]]
    assert "Buy when RSI < 30" in lesson_texts
    assert "Avoid high VIX entries" in lesson_texts


def test_duplicate_lesson_increases_confidence(test_db):
    store_lessons(["RSI below 30 is bullish"])
    store_lessons(["RSI below 30 is bullish"])
    result = get_lessons()
    lesson = next(l for l in result["lessons"] if l["lesson"] == "RSI below 30 is bullish")
    assert lesson["supporting_trades"] == 2
    assert lesson["confidence"] > 0.5
