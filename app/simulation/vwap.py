"""
VWAP (Volume Weighted Average Price) calculation.
"""
from typing import List, Dict

def calculate_vwap(trades: List[Dict[str, float]]) -> float:
    """
    Calculates the Volume Weighted Average Price (VWAP).
    Formula: sum(price * volume) / sum(volume)
    """
    if not trades:
        return 0.0
        
    total_value = sum(trade["price"] * trade["volume"] for trade in trades)
    total_volume = sum(trade["volume"] for trade in trades)
    
    if total_volume == 0:
        return 0.0
        
    return total_value / total_volume
