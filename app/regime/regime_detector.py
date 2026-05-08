"""
Regime Detector.
Combines multiple features to detect market regimes.
"""
from typing import List
from app.regime.volatility_regime import detect_volatility_regime
from app.features.mean_reversion import calculate_half_life

class RegimeDetector:
    def __init__(self, vol_threshold: float = 0.05, half_life_threshold_hours: float = 4.0):
        self.vol_threshold = vol_threshold
        self.half_life_threshold_seconds = half_life_threshold_hours * 3600

    def detect_regime(self, prices: List[float]) -> str:
        """
        Detects the market regime.
        Returns 'mean_reverting', 'trending', or 'volatile'.
        """
        vol_regime = detect_volatility_regime(prices, self.vol_threshold)
        
        if vol_regime == 'high_volatility':
            return 'volatile'
            
        half_life = calculate_half_life(prices)
        
        if half_life > 0 and half_life < self.half_life_threshold_seconds:
            return 'mean_reverting'
            
        return 'trending'
