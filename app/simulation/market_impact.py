"""
Market Impact Model.
Calculates price impact of a trade.
"""
import math

def calculate_impact(trade_volume: float, daily_volume: float) -> float:
    """
    Calculates expected price impact.
    Impact is typically proportional to the square root of the fraction of daily volume.
    """
    if daily_volume == 0:
        return 1.0  # Max impact if no daily volume
        
    fraction = trade_volume / daily_volume
    
    # Square root law for market impact (with an arbitrary scaling factor of 0.1)
    return 0.1 * math.sqrt(fraction)
