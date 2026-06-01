"""
Slippage calculation and modeling.
"""


def estimate_market_impact(trade_volume: float, daily_volume: float) -> float:
    """
    Estimates the percentage slippage for a market order of size `trade_volume`.
    Uses the square-root law of market impact.
    """
    if daily_volume <= 0 or trade_volume <= 0:
        return 0.0

    participation = trade_volume / max(daily_volume, 1.0)

    # Square root model: let's assume 10% daily volume participation causes ~5% slippage
    # 0.05 = c * sqrt(0.1) => c = 0.158
    c = 0.158
    slippage_pct = c * (participation**0.5)

    return min(slippage_pct, 1.0)


def calculate_safe_trade_limit(daily_volume: int, max_slippage_pct: float = 0.03) -> int:
    """
    Returns the maximum number of items to trade to stay under a given slippage threshold (e.g. 3%).
    """
    c = 0.158
    if daily_volume <= 0:
        return 1

    safe_vol = int(daily_volume * ((max_slippage_pct / c) ** 2))
    return max(safe_vol, 1)


def calculate_slippage(base_price: float, executed_price: float) -> float:
    """
    Calculates slippage as a percentage between an expected base price and actual executed price.
    """
    if base_price == 0:
        return 0.0
    return abs(executed_price - base_price) / base_price
