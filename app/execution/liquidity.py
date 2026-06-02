"""
Liquidity score calculation.
"""


def calculate_liquidity_score(volume_24h: float, spread: float) -> float:
    """
    Calculates a liquidity score based on volume and spread.
    High volume and low spread -> high score (closer to 1.0)
    """
    if volume_24h <= 0:
        return 0.0

    # Normalize volume (10,000+ is max liquidity)
    vol_score = min(volume_24h / 10000.0, 1.0)

    # Penalize high spreads (0% = no penalty, 20%+ = max penalty)
    spread_discount = max(1.0 - (spread / 0.20), 0.1) if spread > 0 else 1.0

    score = vol_score * spread_discount
    return min(max(score, 0.0), 1.0)
