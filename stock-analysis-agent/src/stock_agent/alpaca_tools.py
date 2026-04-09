"""
Alpaca paper trading tools for the stock analysis agent.
Uses alpaca-py SDK to place and manage paper trades.
"""

import os
import json
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus

load_dotenv()


def _get_client() -> TradingClient:
    """Return authenticated Alpaca paper trading client."""
    return TradingClient(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_API_SECRET"),
        paper=True
    )


def get_account_balance() -> dict:
    """
    Get current paper trading account balance and buying power.
    """
    try:
        client = _get_client()
        account = client.get_account()
        return {
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "equity": float(account.equity),
            "last_equity": float(account.last_equity),
            "pnl_today": float(account.equity) - float(account.last_equity),
            "pnl_today_pct": round(
                (float(account.equity) - float(account.last_equity))
                / float(account.last_equity) * 100, 3
            ) if float(account.last_equity) > 0 else 0,
        }
    except Exception as e:
        return {"error": str(e)}


def get_positions() -> dict:
    """
    Get all current open positions in the paper account.
    """
    try:
        client = _get_client()
        positions = client.get_all_positions()

        holdings = []
        for pos in positions:
            holdings.append({
                "ticker": pos.symbol,
                "quantity": float(pos.qty),
                "side": pos.side.value,
                "entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "unrealized_pnl": float(pos.unrealized_pl),
                "unrealized_pnl_pct": float(pos.unrealized_plpc) * 100,
                "cost_basis": float(pos.cost_basis),
            })

        return {
            "positions": holdings,
            "total_positions": len(holdings),
        }
    except Exception as e:
        return {"error": str(e)}


def place_order(ticker: str, quantity: int, side: str) -> dict:
    """
    Place a market order on the paper trading account.

    Args:
        ticker:   Stock symbol e.g. AAPL
        quantity: Number of shares
        side:     BUY or SELL
    """
    try:
        client = _get_client()
        ticker = ticker.upper()
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL

        request = MarketOrderRequest(
            symbol=ticker,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY
        )

        order = client.submit_order(request)

        return {
            "status": "ORDER_PLACED",
            "order_id": str(order.id),
            "ticker": ticker,
            "quantity": quantity,
            "side": side.upper(),
            "order_type": "MARKET",
            "order_status": order.status.value,
            "submitted_at": str(order.submitted_at),
        }
    except Exception as e:
        return {"error": str(e)}


def place_limit_order(ticker: str, quantity: int, side: str, price: float) -> dict:
    """
    Place a limit order on the paper trading account.

    Args:
        ticker:   Stock symbol e.g. AAPL
        quantity: Number of shares
        side:     BUY or SELL
        price:    Limit price
    """
    try:
        client = _get_client()
        ticker = ticker.upper()
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL

        request = LimitOrderRequest(
            symbol=ticker,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=round(price, 2)
        )

        order = client.submit_order(request)

        return {
            "status": "ORDER_PLACED",
            "order_id": str(order.id),
            "ticker": ticker,
            "quantity": quantity,
            "side": side.upper(),
            "order_type": "LIMIT",
            "limit_price": price,
            "order_status": order.status.value,
            "submitted_at": str(order.submitted_at),
        }
    except Exception as e:
        return {"error": str(e)}


def get_open_orders() -> dict:
    """
    Get all open (pending / not yet filled) orders from the paper account.

    Used by the risk agent to detect after-hours positions that haven't
    settled into the positions list yet.  Returns tickers in the same
    format as get_positions() so callers can merge the two lists.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        client = _get_client()

        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders  = client.get_orders(request)

        open_orders = []
        for order in orders:
            if order.side == OrderSide.BUY:
                open_orders.append({
                    "ticker":   order.symbol,
                    "quantity": float(order.qty),
                    "side":     order.side.value,
                    "status":   order.status.value,
                })

        return {"open_orders": open_orders, "total_open": len(open_orders)}
    except Exception as e:
        return {"error": str(e), "open_orders": [], "total_open": 0}


def get_order_history(max_results: int = 10) -> dict:
    """
    Get recent order history from the paper account.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        client = _get_client()

        request = GetOrdersRequest(limit=max_results)
        orders = client.get_orders(request)

        history = []
        for order in orders:
            history.append({
                "order_id": str(order.id),
                "ticker": order.symbol,
                "side": order.side.value,
                "quantity": float(order.qty),
                "filled_quantity": float(order.filled_qty) if order.filled_qty else 0,
                "order_type": order.order_type.value,
                "status": order.status.value,
                "limit_price": float(order.limit_price) if order.limit_price else None,
                "filled_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "submitted_at": str(order.submitted_at),
                "filled_at": str(order.filled_at) if order.filled_at else None,
            })

        return {
            "orders": history,
            "total_orders": len(history),
        }
    except Exception as e:
        return {"error": str(e)}


def cancel_order(order_id: str) -> dict:
    """
    Cancel an open order.

    Args:
        order_id: The order ID to cancel
    """
    try:
        client = _get_client()
        client.cancel_order_by_id(order_id)
        return {
            "status": "ORDER_CANCELLED",
            "order_id": order_id,
        }
    except Exception as e:
        return {"error": str(e)}


def cancel_all_orders() -> dict:
    """
    Cancel all open orders on the paper account.
    Returns a summary of how many were cancelled and any failures.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        client = _get_client()

        open_orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        if not open_orders:
            return {"cancelled": 0, "failed": 0, "message": "No open orders to cancel."}

        cancelled, failed = 0, []
        for order in open_orders:
            try:
                client.cancel_order_by_id(order.id)
                cancelled += 1
            except Exception as e:
                failed.append({"order_id": str(order.id), "ticker": order.symbol, "error": str(e)})

        return {
            "cancelled": cancelled,
            "failed":    len(failed),
            "failures":  failed,
            "message":   f"Cancelled {cancelled} order(s)." + (
                f" {len(failed)} failed." if failed else ""
            ),
        }
    except Exception as e:
        return {"error": str(e), "cancelled": 0, "failed": 0}


def close_position(ticker: str) -> dict:
    """
    Close an entire position for a ticker.

    Args:
        ticker: Stock symbol to close e.g. AAPL
    """
    try:
        client = _get_client()
        order = client.close_position(ticker.upper())
        return {
            "status": "POSITION_CLOSED",
            "ticker": ticker.upper(),
            "order_id": str(order.id),
            "order_status": order.status.value,
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    print("=== Account Balance ===")
    print(json.dumps(get_account_balance(), indent=2))

    print("\n=== Positions ===")
    print(json.dumps(get_positions(), indent=2))

    print("\n=== Order History (last 5) ===")
    print(json.dumps(get_order_history(5), indent=2))
