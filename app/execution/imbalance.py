"""
Order book imbalance calculation.
"""

def calculate_imbalance(v_bid: float, v_ask: float) -> float:
    """
    Calculates order book imbalance.
    Formula: I = (V_bid - V_ask) / (V_bid + V_ask)
    Range: [-1, 1]
    """
    denominator = v_bid + v_ask
    if denominator == 0:
        return 0.0
    return (v_bid - v_ask) / denominator
