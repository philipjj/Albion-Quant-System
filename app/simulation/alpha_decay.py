"""
Alpha Decay Modeling.
Estimates the lifetime and decay velocity of trading signals.
"""
import math
from typing import Dict

def estimate_alpha_decay(
    initial_strength: float,
    current_strength: float,
    elapsed_time: float,
    market_volume: float
) -> Dict[str, float]:
    """
    Estimates alpha decay based on exponential decay model:
    Strength = Initial * exp(-lambda * t)
    
    Returns:
    - expected_remaining_lifetime: seconds until strength hits 0.1
    - decay_velocity: the lambda parameter
    """
    if elapsed_time <= 0:
        return {
            "expected_remaining_lifetime": 3600.0,  # 1 hour default
            "decay_velocity": 0.0
        }
        
    if current_strength >= initial_strength:
        # No decay observed yet or strength increased
        # Return a conservative long lifetime
        return {
            "expected_remaining_lifetime": 3600.0,
            "decay_velocity": 0.0
        }
        
    # Calculate observed lambda
    # current = initial * exp(-lambda * t)
    # current / initial = exp(-lambda * t)
    # log(current / initial) = -lambda * t
    # lambda = -log(current / initial) / t
    
    try:
        decay_rate = -math.log(current_strength / initial_strength) / elapsed_time
    except (ValueError, ZeroDivisionError):
        decay_rate = 0.001  # Fallback
        
    # Adjust for market volume (higher volume accelerates decay)
    # Assuming market_volume is normalized or we just use it as a scale
    # Let's say volume of 100 is "normal".
    volume_factor = 1.0 + (market_volume / 100.0)
    effective_decay_rate = decay_rate * volume_factor
    
    if effective_decay_rate <= 0:
        effective_decay_rate = 0.0001  # Prevent divide by zero
        
    # Estimate remaining lifetime (time to reach 0.1 of initial strength)
    # 0.1 * initial = initial * exp(-lambda * t_total)
    # 0.1 = exp(-lambda * t_total)
    # log(0.1) = -lambda * t_total
    # t_total = -log(0.1) / lambda
    # remaining = t_total - elapsed_time
    
    t_total = -math.log(0.1) / effective_decay_rate
    remaining_lifetime = max(0.0, t_total - elapsed_time)
    
    return {
        "expected_remaining_lifetime": remaining_lifetime,
        "decay_velocity": effective_decay_rate
    }
