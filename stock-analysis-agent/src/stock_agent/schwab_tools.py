"""
Schwab API tools for paper trading agent.
Wraps schwab-py client for use as Claude tool calls.
"""

import os
import json
from dotenv import load_dotenv
import schwab

load_dotenv()

TOKEN_PATH = "/Users/velloregrao/Projects/agents/stock-analysis-agent/schwab_token.json"
PAPER_ACCOUNT = "68910787"  # CASH account with balance
PAPER_ACCOUNT_HASH = "B83E5A3A7B130E89A82EDCD95C10DE138CA10E14DEE2E861957570300E0AE99B"


def _get_client():
    """Return authenticated Schwab client."""
    return schwab.auth.client_from_token_file(
        token_path=TOKEN_PATH,
        api_key=os.getenv("SCHWAB_APP_KEY"),
        app_secret=os.getenv("SCHWAB_APP_SECRET"),
    )


def _get_account_number() -> str:
    """Auto-detect the account with highest balance."""
    global PAPER_ACCOUNT
    if PAPER_ACCOUNT:
        return PAPER_ACCOUNT

    client = _get_client()
    accounts = client.get_accounts().json()

    # Pick account with highest liquidation value
    best_account = None
    best_value = -1
    for account in accounts:
        sec = account.get("securitiesAccount", {})
        value = sec.get("currentBalances", {}).get("liquidationValue", 0)
        if value > best_value:
            best_value = value
            best_account = sec["accountNumber"]

    PAPER_ACCOUNT = best_account or accounts[0]["securitiesAccount"]["accountNumber"]
    return PAPER_ACCOUNT


def get_account_balance() -> dict:
    """
    Get current account balance and buying power.
    Returns cash balance, buying power and liquidation value.
    """
    try:
        client = _get_client()
        account_number = _get_account_number()
        accounts = client.get_accounts().json()

        # Find the matching account
        for account in accounts:
            sec = account.get("securitiesAccount", {})
            if sec.get("accountNumber") == account_number:
                balances = sec.get("currentBalances", {})
                return {
                    "account_number": account_number,
                    "account_type": sec.get("type"),
                    "cash_balance": balances.get("cashBalance", 0),
                    "buying_power": balances.get("buyingPower",
                                   balances.get("cashAvailableForTrading", 0)),
                    "liquidation_value": balances.get("liquidationValue", 0),
                    "available_funds": balances.get("availableFunds",
                                      balances.get("cashAvailableForTrading", 0)),
                    "cash_available_for_trading": balances.get("cashAvailableForTrading", 0),
                }

        return {"error": f"Account {account_number} not found"}
    except Exception as e:
        return {"error": str(e)}


def get_positions() -> dict:
    """
    Get all current positions in the account.
    Returns list of holdings with quantity, cost basis and market value.
    """
    try:
        client = _get_client()
        account_number = _get_account_number()
        accounts = client.get_accounts(
            fields=[client.Account.Fields.POSITIONS]
        ).json()

        sec = {}
        for account in accounts:
            s = account.get("securitiesAccount", {})
            if s.get("accountNumber") == account_number:
                sec = s
                break

        positions = sec.get("positions", [])

        holdings = []
        for pos in positions:
            instrument = pos.get("instrument", {})
            holdings.append({
                "ticker": instrument.get("symbol"),
                "asset_type": instrument.get("assetType"),
                "quantity": pos.get("longQuantity", 0),
                "average_cost": pos.get("averagePrice", 0),
                "market_value": pos.get("marketValue", 0),
                "unrealized_pnl": pos.get("unrealizedPL", 0),
                "unrealized_pnl_pct": pos.get("unrealizedPLPercent", 0),
            })

        return {
            "account_number": account_number,
            "positions": holdings,
            "total_positions": len(holdings),
        }
    except Exception as e:
        return {"error": str(e)}


def place_order(ticker: str, quantity: int, side: str, order_type: str = "MARKET") -> dict:
    """
    Place a paper trade order.

    Args:
        ticker:     Stock symbol e.g. AAPL
        quantity:   Number of shares
        side:       BUY or SELL
        order_type: MARKET or LIMIT
    """
    try:
        client = _get_client()
        account_number = _get_account_number()

        ticker = ticker.upper()
        side = side.upper()

        # Build order using schwab-py order builder
        if side == "BUY":
            if order_type == "MARKET":
                order = schwab.orders.equities.equity_buy_market(ticker, quantity)
            else:
                return {"error": "LIMIT orders require a price — use place_limit_order()"}
        elif side == "SELL":
            if order_type == "MARKET":
                order = schwab.orders.equities.equity_sell_market(ticker, quantity)
            else:
                return {"error": "LIMIT orders require a price — use place_limit_order()"}
        else:
            return {"error": f"Invalid side: {side}. Use BUY or SELL."}

        response = client.place_order(PAPER_ACCOUNT_HASH, order)

        # Extract order ID from response headers
        order_id = None
        if hasattr(response, "headers"):
            location = response.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else None

        return {
            "status": "ORDER_PLACED" if response.status_code in (200, 201) else "ORDER_FAILED",
            "ticker": ticker,
            "quantity": quantity,
            "side": side,
            "order_type": order_type,
            "order_id": order_id,
            "http_status": response.status_code,
        }
    except Exception as e:
        return {"error": str(e)}


def get_order_history(max_results: int = 10) -> dict:
    """
    Get recent order history for the account.
    Returns list of recent orders with status and fill details.
    """
    try:
        from datetime import datetime, timedelta
        client = _get_client()
        account_number = _get_account_number()

        # Get orders from last 30 days
        from_date = datetime.now() - timedelta(days=30)
        response = client.get_orders_for_account(
            PAPER_ACCOUNT_HASH,
            from_entered_datetime=from_date,
            max_results=max_results,
        ).json()

        orders = []
        if isinstance(response, list):
            for order in response:
                if not isinstance(order, dict):
                    continue
                leg = order.get("orderLegCollection", [{}])
                leg = leg[0] if leg else {}
                instrument = leg.get("instrument", {}) if isinstance(leg, dict) else {}
                orders.append({
                    "order_id": order.get("orderId"),
                    "ticker": instrument.get("symbol"),
                    "side": leg.get("instruction"),
                    "quantity": order.get("quantity"),
                    "filled_quantity": order.get("filledQuantity"),
                    "order_type": order.get("orderType"),
                    "status": order.get("status"),
                    "price": order.get("price"),
                    "entered_time": order.get("enteredTime"),
                    "close_time": order.get("closeTime"),
                })

        return {
            "account_number": account_number,
            "orders": orders,
            "total_orders": len(orders),
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
        account_number = _get_account_number()
        response = client.cancel_order(PAPER_ACCOUNT_HASH, order_id)

        return {
            "status": "ORDER_CANCELLED",
            "order_id": order_id,
            "http_status": response.status_code,
        }
    except Exception as e:
        return {"error": str(e)}


def place_limit_order(ticker: str, quantity: int, side: str, price: float, extended_hours: bool = True) -> dict:
    """
    Place a limit order, optionally during extended hours.

    Args:
        ticker:         Stock symbol e.g. AAPL
        quantity:       Number of shares
        side:           BUY or SELL
        price:          Limit price
        extended_hours: Allow extended hours trading (default True)
    """
    try:
        client = _get_client()
        ticker = ticker.upper()
        side = side.upper()

        session = schwab.orders.equities.Session.SEAMLESS if extended_hours else schwab.orders.equities.Session.NORMAL

        price_str = str(round(price, 2))
        if side == "BUY":
            order = schwab.orders.equities.equity_buy_limit(ticker, quantity, price_str).set_session(session)
        elif side == "SELL":
            order = schwab.orders.equities.equity_sell_limit(ticker, quantity, price_str).set_session(session)
        else:
            return {"error": f"Invalid side: {side}. Use BUY or SELL."}

        response = client.place_order(PAPER_ACCOUNT_HASH, order)

        order_id = None
        if hasattr(response, "headers"):
            location = response.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else None

        return {
            "status": "ORDER_PLACED" if response.status_code in (200, 201) else "ORDER_FAILED",
            "ticker": ticker,
            "quantity": quantity,
            "side": side,
            "order_type": "LIMIT",
            "price": price,
            "extended_hours": extended_hours,
            "order_id": order_id,
            "http_status": response.status_code,
        }
    except Exception as e:
        return {"error": str(e)}


def get_quote(ticker: str) -> dict:
    """
    Get real-time quote for a ticker from Schwab.

    Args:
        ticker: Stock symbol e.g. AAPL
    """
    try:
        client = _get_client()
        response = client.get_quote(ticker).json()
        quote = response.get(ticker, {}).get("quote", {})

        return {
            "ticker": ticker,
            "last_price": quote.get("lastPrice"),
            "bid": quote.get("bidPrice"),
            "ask": quote.get("askPrice"),
            "volume": quote.get("totalVolume"),
            "open": quote.get("openPrice"),
            "high": quote.get("highPrice"),
            "low": quote.get("lowPrice"),
            "close": quote.get("closePrice"),
            "change": quote.get("netChange"),
            "change_pct": quote.get("netPercentChangeInDouble"),
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    # Quick test
    print("=== Account Balance ===")
    print(json.dumps(get_account_balance(), indent=2))

    print("\n=== Positions ===")
    print(json.dumps(get_positions(), indent=2))

    print("\n=== AAPL Quote ===")
    print(json.dumps(get_quote("AAPL"), indent=2))

    print("\n=== Order History ===")
    print(json.dumps(get_order_history(5), indent=2))
