"""
Spread features.
Calculates absolute and relative spreads.
"""

def calculate_absolute_spread(best_ask: float, best_bid: float) -> float:
    """Calculates the absolute spread."""
    return best_ask - best_bid

def calculate_relative_spread(best_ask: float, best_bid: float) -> float:
    """Calculates the spread relative to the midprice."""
    midprice = (best_ask + best_bid) / 2
    if midprice == 0:
        return 0.0
    return (best_ask - best_bid) / midprice
