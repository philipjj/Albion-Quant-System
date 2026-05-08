"""
Mean Reversion Engine.
Uses mean reversion features to generate signals.
"""
from datetime import datetime
from typing import List
from app.features.mean_reversion import calculate_half_life
from app.features.volatility import calculate_historical_volatility
from app.shared.domain.signal import Signal

class MeanReversionEngine:
    def __init__(self, half_life_threshold_hours: float = 4.0, std_dev_threshold: float = 2.0):
        self.half_life_threshold_seconds = half_life_threshold_hours * 3600
        self.std_dev_threshold = std_dev_threshold

    def evaluate(self, item_id: str, city: str, prices: List[float]) -> Signal | None:
        """
        Evaluates price history for mean reversion signals.
        If current price diverges from midprice by > N std dev,
        and half-life < threshold -> trigger signal.
        """
        if len(prices) < 10:
            return None
            
        half_life = calculate_half_life(prices)
        volatility = calculate_historical_volatility(prices)
        
        if half_life == 0 or half_life == float('inf'):
            return None
            
        if half_life > self.half_life_threshold_seconds:
            return None
            
        # Calculate midprice (mean of prices for simplicity in this pure function)
        midprice = sum(prices) / len(prices)
        current_price = prices[-1]
        
        # Calculate standard deviation
        mean = sum(prices) / len(prices)
        variance = sum((x - mean) ** 2 for x in prices) / len(prices)
        std_dev = variance ** 0.5
        
        if std_dev == 0:
            return None
            
        divergence = (current_price - midprice) / std_dev
        
        if abs(divergence) > self.std_dev_threshold:
            # We have a signal!
            # If current price is low, it's a buy signal (divergence is negative)
            # If current price is high, it's a sell signal (divergence is positive)
            signal_type = "buy" if divergence < 0 else "sell"
            
            # Strength can be normalized divergence or similar
            strength = abs(divergence) / 10.0  # Arbitrary scaling
            strength = min(1.0, strength)  # Cap at 1.0
            
            return Signal(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                signal_type=signal_type,
                strength=strength,
                metadata={
                    "half_life_seconds": half_life,
                    "volatility": volatility,
                    "divergence_std": divergence,
                    "midprice": midprice,
                    "current_price": current_price
                }
            )
            
        return None
