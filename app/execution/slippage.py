"""
Slippage calculation and modeling.
"""


def estimate_market_impact(trade_volume: float, daily_volume: float) -> float:
    """
    Estimates the percentage slippage for a market order of size `trade_volume`.
    Uses the square-root law of market impact.
    """
    if trade_volume <= 0:
        return 0.0

    effective_daily_vol = daily_volume if daily_volume > 0 else max(trade_volume * 10.0, 1000.0)
    participation = trade_volume / max(effective_daily_vol, 1.0)

    # Square root model: let's assume 10% daily volume participation causes ~5% slippage
    # 0.05 = c * sqrt(0.1) => c = 0.158
    c = 0.158
    slippage_pct = c * (participation**0.5)

    return min(slippage_pct, 1.0)


def calculate_safe_trade_limit(
    daily_volume: int, max_slippage_pct: float = 0.03, default_limit: int = 1
) -> int:
    """
    Returns the maximum number of items to trade to stay under a given slippage threshold (e.g. 3%).
    """
    c = 0.158
    if daily_volume <= 0:
        return default_limit

    safe_vol = int(daily_volume * ((max_slippage_pct / c) ** 2))
    return max(safe_vol, default_limit)


def calculate_slippage(base_price: float, executed_price: float) -> float:
    """
    Calculates slippage as a percentage between an expected base price and actual executed price.
    """
    if base_price == 0:
        return 0.0
    return abs(executed_price - base_price) / base_price


def calculate_effective_price(base_price: int, trade_volume: int, daily_volume: int, is_buy: bool) -> int:
    """
    Calculates the expected effective price after slippage.
    If is_buy=True, we are buying, so slippage INCREASES the price we pay.
    If is_buy=False, we are selling, so slippage DECREASES the price we get.
    """
    if base_price <= 0 or trade_volume <= 1:
        return base_price

    slippage_pct = estimate_market_impact(trade_volume, daily_volume)
    
    if is_buy:
        # We pay more due to slippage
        effective_price = base_price * (1.0 + slippage_pct)
    else:
        # We receive less due to slippage
        effective_price = base_price * (1.0 - slippage_pct)

    return int(effective_price)
