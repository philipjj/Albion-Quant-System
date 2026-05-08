"""
Matching Engine.
Simulates order matching against market depth.
"""
from typing import Dict

def match_order(order_type: str, size: float, price: float, snapshot: Dict[str, any]) -> Dict[str, any]:
    """
    Simulates matching an order against a market snapshot.
    Supports both top-of-book (ask_price/volume) and full depth (asks/bids lists).
    Returns the executed size, average price, and remaining size.
    """
    remaining_size = size
    total_executed = 0.0
    total_value = 0.0
    
    if order_type == "buy":
        # Check if we have depth data
        if "asks" in snapshot:
            for level in snapshot["asks"]:
                p, v = level[0], level[1]
                if price >= p and remaining_size > 0:
                    exec_size = min(remaining_size, v)
                    total_executed += exec_size
                    total_value += exec_size * p
                    remaining_size -= exec_size
                else:
                    break
        else:
            # Fallback to top of book
            market_price = snapshot.get('ask_price', 0)
            market_volume = snapshot.get('ask_volume', 0)
            if market_price > 0 and price >= market_price:
                exec_size = min(remaining_size, market_volume)
                total_executed += exec_size
                total_value += exec_size * market_price
                remaining_size -= exec_size
                
    elif order_type == "sell":
        # Check if we have depth data
        if "bids" in snapshot:
            for level in snapshot["bids"]:
                p, v = level[0], level[1]
                if price <= p and remaining_size > 0:
                    exec_size = min(remaining_size, v)
                    total_executed += exec_size
                    total_value += exec_size * p
                    remaining_size -= exec_size
                else:
                    break
        else:
            # Fallback to top of book
            market_price = snapshot.get('bid_price', 0)
            market_volume = snapshot.get('bid_volume', 0)
            if market_price > 0 and price <= market_price:
                exec_size = min(remaining_size, market_volume)
                total_executed += exec_size
                total_value += exec_size * market_price
                remaining_size -= exec_size
                
    avg_price = total_value / total_executed if total_executed > 0 else 0.0
    
    return {
        "executed_size": total_executed,
        "avg_price": avg_price,
        "remaining_size": remaining_size
    }
