"""
Momentum features.
Calculates price momentum over a window.
"""
from typing import List

def calculate_momentum(prices: List[float], window: int = 5) -> float:
    """
    Calculates simple momentum: current price - price N steps ago.
    """
    if len(prices) < window + 1:
        return 0.0
    return prices[-1] - prices[-window-1]

def calculate_roc(prices: List[float], window: int = 5) -> float:
    """
    Calculates Rate of Change: (current price - price N steps ago) / price N steps ago.
    """
    if len(prices) < window + 1:
        return 0.0
    if prices[-window-1] == 0:
        return 0.0
    return (prices[-1] - prices[-window-1]) / prices[-window-1]
