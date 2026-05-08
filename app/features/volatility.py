"""
Volatility features.
Calculates volatility based on price history.
"""
import math
from typing import List

def calculate_historical_volatility(prices: List[float]) -> float:
    """
    Calculates the standard deviation of log returns.
    This is a standard way to calculate historical volatility.
    """
    if len(prices) < 2:
        return 0.0
        
    log_returns = []
    for i in range(1, len(prices)):
        if prices[i-1] == 0 or prices[i] == 0:
            continue
        log_returns.append(math.log(prices[i] / prices[i-1]))
        
    if len(log_returns) < 2:
        return 0.0
        
    mean = sum(log_returns) / len(log_returns)
    variance = sum((x - mean) ** 2 for x in log_returns) / (len(log_returns) - 1)
    
    return math.sqrt(variance)
