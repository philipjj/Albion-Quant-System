"""
Liquidity Regime Detector.
Detects whether the market is in a liquid or illiquid state.
"""
from typing import List

def detect_liquidity_regime(
    volumes: List[float],
    threshold: float
) -> str:
    """
    Detects the liquidity regime.
    Returns 'liquid' or 'illiquid'.
    """
    if not volumes:
        return "illiquid"
        
    avg_volume = sum(volumes) / len(volumes)
    
    if avg_volume >= threshold:
        return "liquid"
    else:
        return "illiquid"
