"""
VWAP (Volume Weighted Average Price) engine.
"""

def calculate_vwap(orders: list[dict], target_volume: float) -> float:
    """
    Calculates VWAP for a target volume by walking the order book.
    Each order should have 'price' and 'volume'.
    Returns the average execution price.
    """
    total_cost = 0.0
    filled_volume = 0.0
    
    # Sort orders by price (buy orders descending, sell orders ascending)
    # Assuming orders passed are already relevant for the operation
    
    for order in orders:
        if filled_volume >= target_volume:
            break
            
        remaining = target_volume - filled_volume
        fill = min(order['volume'], remaining)
        
        total_cost += fill * order['price']
        filled_volume += fill
        
    if filled_volume == 0:
        return 0.0
        
    return total_cost / filled_volume

def calculate_slippage(base_price: float, executed_price: float) -> float:
    """
    Calculates slippage as a percentage.
    """
    if base_price == 0:
        return 0.0
    return abs(executed_price - base_price) / base_price
