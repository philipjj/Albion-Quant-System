"""
VWAP (Volume Weighted Average Price) engine.
Calculates realistic execution prices based on market depth and slippage.
"""

from typing import Dict, List

from app.execution.slippage import estimate_market_impact


def calculate_vwap_from_orderbook(orders: list[dict], target_volume: float) -> float:
    """
    Calculates VWAP for a target volume by walking the order book.
    Each order should have 'price' and 'amount'/'volume'.
    Returns the average execution price.
    """
    total_cost = 0.0
    filled_volume = 0.0

    for order in orders:
        if filled_volume >= target_volume:
            break

        remaining = target_volume - filled_volume
        vol = order.get("amount", order.get("volume", 0))
        fill = min(vol, remaining)

        total_cost += fill * order["price"]
        filled_volume += fill

    if filled_volume == 0:
        return 0.0

    return total_cost / filled_volume


def estimate_vwap(
    base_price: float, trade_volume: float, daily_volume: float, is_buy: bool
) -> float:
    """
    Estimates VWAP when full orderbook data is unavailable.
    Applies an estimated market impact (slippage) to the best price.
    is_buy = True: we are buying from the market (lifts best ask).
    is_buy = False: we are selling to the market (hits best bid).
    """
    if trade_volume <= 0 or base_price <= 0:
        return base_price

    slippage_pct = estimate_market_impact(trade_volume, daily_volume)

    if is_buy:
        # Buying pushes our average price UP (we pay more)
        return base_price * (1.0 + slippage_pct)
    else:
        # Selling pushes our average price DOWN (we receive less)
        return base_price * (1.0 - slippage_pct)
