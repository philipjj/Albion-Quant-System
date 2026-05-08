"""
Liquidity features.
Calculates market depth score and spread stability.
"""

def calculate_market_depth_score(bid_volume: float, ask_volume: float) -> float:
    """
    Calculates a simple market depth score based on total volume.
    Higher volume means deeper market.
    """
    return bid_volume + ask_volume

def calculate_spread_stability(spreads: list[float]) -> float:
    """
    Calculates spread stability.
    Lower variance in spreads means higher stability.
    Returns 1 / (1 + variance).
    """
    if len(spreads) < 2:
        return 1.0
        
    mean = sum(spreads) / len(spreads)
    variance = sum((x - mean) ** 2 for x in spreads) / len(spreads)
    
    return 1.0 / (1.0 + variance)
