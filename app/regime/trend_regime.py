"""
Trend Regime Detector.
Detects whether the market is trending or ranging.
"""
from typing import List

def detect_trend_regime(prices: List[float]) -> str:
    """
    Detects the trend regime using the Efficiency Ratio (ER).
    ER = net_change / total_path_length
    
    Returns 'trending' or 'ranging'.
    """
    if len(prices) < 3:
        return "ranging"
        
    net_change = abs(prices[-1] - prices[0])
    
    total_path_length = sum(
        abs(prices[i] - prices[i-1])
        for i in range(1, len(prices))
    )
    
    if total_path_length == 0:
        return "ranging"
        
    efficiency_ratio = net_change / total_path_length
    
    # Threshold: 0.6 is a common choice for efficiency ratio
    if efficiency_ratio >= 0.6:
        return "trending"
    else:
        return "ranging"
