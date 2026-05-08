"""
Volatility Regime Detector.
Classifies the market environment based on volatility.
"""
from typing import List
from app.features.volatility import calculate_historical_volatility

def detect_volatility_regime(prices: List[float], threshold: float = 0.05) -> str:
    """
    Classifies the market as 'high_volatility' or 'low_volatility'.
    """
    vol = calculate_historical_volatility(prices)
    
    if vol > threshold:
        return 'high_volatility'
    else:
        return 'low_volatility'
