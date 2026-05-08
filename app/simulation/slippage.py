"""
Slippage Model.
Calculates expected slippage based on order size and market conditions.
"""

def calculate_slippage(order_size: float, market_depth: float, volatility: float) -> float:
    """
    Calculates expected slippage.
    Slippage increases with order size and volatility, and decreases with depth.
    """
    if market_depth == 0:
        return 1.0  # High slippage if no depth
        
    # Heuristic formula: size/depth adjusted by volatility
    base_slippage = order_size / market_depth
    volatility_factor = 1.0 + volatility
    
    return base_slippage * volatility_factor
