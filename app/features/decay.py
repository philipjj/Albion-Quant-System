"""
Decay features.
Calculates alpha decay and lifetime estimation.
"""

def calculate_linear_decay(initial_alpha: float, elapsed_seconds: float, half_life_seconds: float) -> float:
    """
    Calculates linear decay based on half-life.
    If half-life is 0 or inf, returns initial_alpha.
    """
    if half_life_seconds <= 0 or half_life_seconds == float('inf'):
        return initial_alpha
        
    decay_rate = 0.5 / half_life_seconds
    remaining = initial_alpha - (decay_rate * elapsed_seconds)
    return max(0.0, remaining)

def calculate_exponential_decay(initial_alpha: float, elapsed_seconds: float, half_life_seconds: float) -> float:
    """
    Calculates exponential decay based on half-life.
    """
    if half_life_seconds <= 0 or half_life_seconds == float('inf'):
        return initial_alpha
        
    import math
    decay_constant = math.log(2) / half_life_seconds
    return initial_alpha * math.exp(-decay_constant * elapsed_seconds)
