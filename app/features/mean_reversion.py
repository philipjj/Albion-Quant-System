"""
Mean Reversion features.
Calculates half-life and persistence.
"""
import math
from typing import List

def calculate_half_life(prices: List[float]) -> float:
    """
    Estimates the half-life of mean reversion using an AR(1) process.
    This is a simplified version of Ornstein-Uhlenbeck parameter estimation.
    """
    if len(prices) < 3:
        return 0.0
        
    # Calculate lagged differences
    y = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    x = [prices[i-1] for i in range(1, len(prices))]
    
    # Simple linear regression: y = alpha + beta * x
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(len(x)))
    den = sum((x[i] - mean_x) ** 2 for i in range(len(x)))
    
    if den == 0:
        return 0.0
        
    beta = num / den
    
    if beta >= 0:
        return float('inf') # Not mean reverting
        
    return -math.log(2) / beta
