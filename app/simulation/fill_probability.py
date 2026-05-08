"""
Fill Probability Modeling.
Estimates the likelihood of an order being filled based on market conditions.
"""
import math

def calculate_fill_probability(
    order_type: str,
    imbalance: float,
    volatility: float,
    spread: float,
    volume: float
) -> float:
    """
    Calculates the fill probability (0.0 to 1.0).
    
    Heuristic model:
    - Base probability is 0.5.
    - Imbalance affects it: 
      - Positive imbalance (more buyers) makes it easier to sell, harder to buy.
      - Negative imbalance (more sellers) makes it easier to buy, harder to sell.
    - Volatility reduces probability (higher risk of price moving away).
    - High spread reduces probability.
    """
    prob = 0.5
    
    # Imbalance effect
    # Imbalance = (Bid Vol - Ask Vol) / (Bid Vol + Ask Vol)
    # Range: -1.0 to 1.0
    if order_type == "buy":
        # Easier to buy if more sellers (imbalance < 0)
        prob -= imbalance * 0.3
    elif order_type == "sell":
        # Easier to sell if more buyers (imbalance > 0)
        prob += imbalance * 0.3
        
    # Volatility effect
    # Higher volatility -> lower fill probability (execution uncertainty)
    prob -= volatility * 0.5
    
    # Spread effect
    # Higher spread -> lower fill probability
    # Assuming a scale where spread of 100 is "high" for this asset class
    prob -= (spread / 100.0) * 0.1
    
    # Volume effect
    # More volume -> higher fill probability
    prob += (volume / 1000.0) * 0.05
    
    # Bound the output
    prob = max(0.05, min(0.95, prob))
    
    return prob
