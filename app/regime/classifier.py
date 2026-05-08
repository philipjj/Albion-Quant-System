"""
Regime Classifier.
Combines multiple regime detectors to classify the market state.
"""
from typing import List, Dict, Any
from app.regime.volatility_regime import detect_volatility_regime
from app.regime.liquidity_regime import detect_liquidity_regime
from app.regime.trend_regime import detect_trend_regime
from app.regime.manipulation import detect_manipulation

class RegimeClassifier:
    """
    Classifies the market into one of the supported regimes:
    Stable, Trending, Mean-Reverting, Illiquid, Adversarial.
    """
    def __init__(
        self,
        vol_threshold: float = 0.05,
        liq_threshold: float = 500.0
    ):
        self.vol_threshold = vol_threshold
        self.liq_threshold = liq_threshold

    def classify(
        self,
        prices: List[float],
        volumes: List[float],
        snapshots: List[Dict[str, Any]]
    ) -> str:
        """
        Classifies the market state.
        """
        # 1. Check for manipulation (Adversarial)
        if detect_manipulation(snapshots):
            return "Adversarial"
            
        # 2. Check for liquidity (Illiquid)
        if detect_liquidity_regime(volumes, self.liq_threshold) == "illiquid":
            return "Illiquid"
            
        # 3. Check for volatility
        vol_regime = detect_volatility_regime(prices, self.vol_threshold)
        
        # 4. Check for trend
        trend_regime = detect_trend_regime(prices)
        
        if trend_regime == "trending":
            return "Trending"
            
        if vol_regime == "high_volatility":
            # High volatility but not trending -> likely Mean-Reverting or just chaotic
            return "Mean-Reverting"
            
        # Default
        return "Stable"
