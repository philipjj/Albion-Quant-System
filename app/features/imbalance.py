"""
Order Book Imbalance feature.
Calculates the directional pressure based on bid and ask volumes.
"""

def calculate_imbalance(bid_volume: float, ask_volume: float) -> float:
    """
    Calculates the order book imbalance.
    I = (V_bid - V_ask) / (V_bid + V_ask)
    
    Returns a value between -1 and 1.
    1 means purely buying pressure.
    -1 means purely selling pressure.
    """
    total_volume = bid_volume + ask_volume
    if total_volume == 0:
        return 0.0
    return (bid_volume - ask_volume) / total_volume
