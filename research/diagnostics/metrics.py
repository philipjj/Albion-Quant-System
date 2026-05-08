"""
Quant Metrics.
Calculates performance metrics for signals and execution.
"""
import math
from typing import List

def calculate_hit_rate(outcomes: List[int]) -> float:
    """
    Calculates the hit rate (percentage of positive outcomes).
    """
    if not outcomes:
        return 0.0
    return sum(outcomes) / len(outcomes)

def calculate_sharpe_ratio(
    returns: List[float],
    risk_free_rate: float = 0.0
) -> float:
    """
    Calculates the Sharpe-like ratio.
    Sharpe = (mean(returns) - risk_free_rate) / std(returns)
    """
    if not returns:
        return 0.0
        
    n = len(returns)
    if n < 2:
        return 0.0
        
    mean_return = sum(returns) / n
    excess_mean = mean_return - risk_free_rate
    
    # Calculate variance
    squared_diffs = [(r - mean_return) ** 2 for r in returns]
    variance = sum(squared_diffs) / n  # Population variance or (n-1) for sample
    
    if variance <= 0:
        return 0.0
        
    std_dev = math.sqrt(variance)
    
    return excess_mean / std_dev
