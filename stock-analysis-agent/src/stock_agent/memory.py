"""
SQLite memory store for the learning trading agent.
Stores trade history, outcomes and learned lessons.
"""

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "/Users/velloregrao/Projects/agents/stock-analysis-agent/trading_memory.db")


def _get_connection() -> sqlite3.Connection:
    """Return SQLite connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db():
    """Create tables if they don't exist."""
    conn = _get_connection()
    cursor = conn.cursor()

    # Trade log — every paper trade placed
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL,
            exit_price REAL,
            entry_date TEXT NOT NULL,
            exit_date TEXT,
            hold_days INTEGER,
            pnl REAL,
            pnl_pct REAL,
            status TEXT DEFAULT 'OPEN',
            entry_rsi REAL,
            entry_vix REAL,
            sector TEXT,
            reasoning TEXT,
            outcome_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Lessons — extracted from trade reflection
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            supporting_trades INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Reflection log — record of each reflection session
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trades_analyzed INTEGER,
            lessons_extracted INTEGER,
            summary TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Token usage — every Claude API call
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_type TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print(f"Memory store initialized at {DB_PATH}")


def store_trade(
    order_id: str,
    ticker: str,
    side: str,
    quantity: float,
    entry_price: float,
    entry_rsi: float = None,
    entry_vix: float = None,
    sector: str = None,
    reasoning: str = None,
) -> dict:
    """
    Store a new trade when it's placed.

    Args:
        order_id:   Alpaca order ID
        ticker:     Stock symbol
        side:       BUY or SELL
        quantity:   Number of shares
        entry_price: Price at entry
        entry_rsi:  RSI at time of entry
        entry_vix:  VIX at time of entry
        sector:     Stock sector
        reasoning:  Claude's reasoning for the trade
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO trades
            (order_id, ticker, side, quantity, entry_price, entry_date,
             entry_rsi, entry_vix, sector, reasoning, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (
            order_id, ticker.upper(), side.upper(), quantity,
            entry_price, datetime.now().isoformat(),
            entry_rsi, entry_vix, sector, reasoning
        ))
        conn.commit()
        conn.close()
        return {"status": "stored", "order_id": order_id, "ticker": ticker}
    except Exception as e:
        return {"error": str(e)}


def close_trade(
    order_id: str,
    exit_price: float,
    outcome_notes: str = None,
) -> dict:
    """
    Record the outcome when a trade is closed.

    Args:
        order_id:      Alpaca order ID
        exit_price:    Price at exit
        outcome_notes: Optional notes about why it was closed
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        # Get the open trade
        cursor.execute("SELECT * FROM trades WHERE order_id = ?", (order_id,))
        trade = cursor.fetchone()

        if not trade:
            return {"error": f"Trade {order_id} not found"}

        entry_price = trade["entry_price"]
        quantity = trade["quantity"]
        entry_date = datetime.fromisoformat(trade["entry_date"])
        exit_date = datetime.now()
        hold_days = (exit_date - entry_date).days

        # Calculate P&L
        if trade["side"] == "BUY":
            pnl = (exit_price - entry_price) * quantity
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl = (entry_price - exit_price) * quantity
            pnl_pct = (entry_price - exit_price) / entry_price * 100

        cursor.execute("""
            UPDATE trades SET
                exit_price = ?,
                exit_date = ?,
                hold_days = ?,
                pnl = ?,
                pnl_pct = ?,
                status = 'CLOSED',
                outcome_notes = ?
            WHERE order_id = ?
        """, (
            exit_price, exit_date.isoformat(),
            hold_days, round(pnl, 2), round(pnl_pct, 2),
            outcome_notes, order_id
        ))

        conn.commit()
        conn.close()

        return {
            "status": "closed",
            "order_id": order_id,
            "ticker": trade["ticker"],
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "hold_days": hold_days,
        }
    except Exception as e:
        return {"error": str(e)}


def get_open_trades() -> dict:
    """Get all currently open trades."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM trades WHERE status = 'OPEN'
            ORDER BY entry_date DESC
        """)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return {"open_trades": trades, "total": len(trades)}
    except Exception as e:
        return {"error": str(e)}


def get_recent_trades(limit: int = 20) -> dict:
    """Get recent closed trades for reflection."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM trades WHERE status = 'CLOSED'
            ORDER BY exit_date DESC LIMIT ?
        """, (limit,))
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return {"trades": trades, "total": len(trades)}
    except Exception as e:
        return {"error": str(e)}


def get_lessons() -> dict:
    """Get all learned lessons ordered by confidence."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM lessons
            ORDER BY confidence DESC, supporting_trades DESC
        """)
        lessons = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return {"lessons": lessons, "total": len(lessons)}
    except Exception as e:
        return {"error": str(e)}


def store_lessons(lessons: list[str], reflection_summary: str = None) -> dict:
    """
    Store lessons extracted from reflection.

    Args:
        lessons:            List of lesson strings
        reflection_summary: Overall summary of the reflection
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        for lesson in lessons:
            # Check if similar lesson exists
            cursor.execute("""
                SELECT id, supporting_trades FROM lessons
                WHERE lesson = ?
            """, (lesson,))
            existing = cursor.fetchone()

            if existing:
                # Reinforce existing lesson
                cursor.execute("""
                    UPDATE lessons SET
                        supporting_trades = supporting_trades + 1,
                        confidence = MIN(0.95, confidence + 0.05),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (existing["id"],))
            else:
                # Add new lesson
                cursor.execute("""
                    INSERT INTO lessons (lesson, confidence, supporting_trades)
                    VALUES (?, 0.5, 1)
                """, (lesson,))

        # Log the reflection session
        cursor.execute("""
            INSERT INTO reflections (trades_analyzed, lessons_extracted, summary)
            VALUES (?, ?, ?)
        """, (0, len(lessons), reflection_summary))

        conn.commit()
        conn.close()
        return {"status": "stored", "lessons_stored": len(lessons)}
    except Exception as e:
        return {"error": str(e)}


def get_performance_summary() -> dict:
    """Get overall trading performance statistics."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                ROUND(AVG(pnl_pct), 2) as avg_return_pct,
                ROUND(SUM(pnl), 2) as total_pnl,
                ROUND(AVG(hold_days), 1) as avg_hold_days,
                ROUND(MAX(pnl_pct), 2) as best_trade_pct,
                ROUND(MIN(pnl_pct), 2) as worst_trade_pct
            FROM trades WHERE status = 'CLOSED'
        """)
        stats = dict(cursor.fetchone())

        if stats["total_trades"] > 0:
            stats["win_rate"] = round(
                stats["winning_trades"] / stats["total_trades"] * 100, 1
            )
        else:
            stats["win_rate"] = 0

        conn.close()
        return stats
    except Exception as e:
        return {"error": str(e)}


def log_token_usage(
    call_type: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """
    Record token usage from a Claude API call.

    Args:
        call_type:          e.g. 'analyze', 'trade', 'reflect', 'research'
        model:              Claude model ID used
        input_tokens:       Input tokens billed
        output_tokens:      Output tokens billed
        cache_read_tokens:  Prompt cache read tokens (billed at 10% of input)
        cache_write_tokens: Prompt cache write tokens (billed at 125% of input)
    """
    try:
        conn = _get_connection()
        conn.execute("""
            INSERT INTO token_usage
            (call_type, model, input_tokens, output_tokens,
             cache_read_tokens, cache_write_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (call_type, model, input_tokens, output_tokens,
              cache_read_tokens, cache_write_tokens))
        conn.commit()
        conn.close()
    except Exception:
        pass  # Never let token logging break the main flow


def get_token_usage_summary(days: int = 30) -> dict:
    """
    Return token usage and estimated cost for the last N days.

    Pricing (per 1M tokens, Sonnet 4.6):
        Input:             $3.00
        Output:            $15.00
        Cache read:        $0.30  (10% of input)
        Cache write:       $3.75  (125% of input)
    """
    # Pricing per token
    PRICING = {
        "claude-sonnet-4-6": {
            "input":        3.00 / 1_000_000,
            "output":      15.00 / 1_000_000,
            "cache_read":   0.30 / 1_000_000,
            "cache_write":  3.75 / 1_000_000,
        },
        "claude-opus-4-6": {
            "input":        5.00 / 1_000_000,
            "output":      25.00 / 1_000_000,
            "cache_read":   0.50 / 1_000_000,
            "cache_write":  6.25 / 1_000_000,
        },
        "claude-haiku-4-5": {
            "input":        1.00 / 1_000_000,
            "output":       5.00 / 1_000_000,
            "cache_read":   0.10 / 1_000_000,
            "cache_write":  1.25 / 1_000_000,
        },
    }
    DEFAULT_PRICING = PRICING["claude-sonnet-4-6"]

    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT call_type, model,
                   SUM(input_tokens)        as input_tokens,
                   SUM(output_tokens)       as output_tokens,
                   SUM(cache_read_tokens)   as cache_read_tokens,
                   SUM(cache_write_tokens)  as cache_write_tokens,
                   COUNT(*)                 as api_calls
            FROM token_usage
            WHERE created_at >= datetime('now', ? || ' days')
            GROUP BY call_type, model
            ORDER BY call_type
        """, (f"-{days}",))

        rows = [dict(r) for r in cursor.fetchall()]

        # Totals across all rows
        cursor.execute("""
            SELECT SUM(input_tokens)       as input_tokens,
                   SUM(output_tokens)      as output_tokens,
                   SUM(cache_read_tokens)  as cache_read_tokens,
                   SUM(cache_write_tokens) as cache_write_tokens,
                   COUNT(*)                as api_calls
            FROM token_usage
            WHERE created_at >= datetime('now', ? || ' days')
        """, (f"-{days}",))
        totals = dict(cursor.fetchone())
        conn.close()

        # Calculate cost per row
        for row in rows:
            p = PRICING.get(row["model"], DEFAULT_PRICING)
            row["cost_usd"] = round(
                row["input_tokens"]       * p["input"]       +
                row["output_tokens"]      * p["output"]      +
                row["cache_read_tokens"]  * p["cache_read"]  +
                row["cache_write_tokens"] * p["cache_write"],
                4,
            )

        # Calculate total cost
        total_cost = 0.0
        for row in rows:
            total_cost += row["cost_usd"]

        return {
            "days": days,
            "by_call_type": rows,
            "totals": totals,
            "total_cost_usd": round(total_cost, 4),
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    initialize_db()

    # Test storing a trade
    result = store_trade(
        order_id="test-001",
        ticker="AAPL",
        side="BUY",
        quantity=1,
        entry_price=253.45,
        entry_rsi=28.5,
        entry_vix=18.2,
        sector="Technology",
        reasoning="RSI oversold at 28.5, strong fundamentals, bullish trend"
    )
    print("Store trade:", json.dumps(result, indent=2))

    # Test getting open trades
    print("\nOpen trades:", json.dumps(get_open_trades(), indent=2))

    # Test closing the trade
    result = close_trade(
        order_id="test-001",
        exit_price=261.20,
        outcome_notes="RSI reached 68, took profit"
    )
    print("\nClose trade:", json.dumps(result, indent=2))

    # Test performance summary
    print("\nPerformance:", json.dumps(get_performance_summary(), indent=2))

    # Test lessons
    store_lessons([
        "RSI below 30 in Technology sector has 70% win rate",
        "Avoid entries when VIX above 25",
    ], "First reflection session")
    print("\nLessons:", json.dumps(get_lessons(), indent=2))
