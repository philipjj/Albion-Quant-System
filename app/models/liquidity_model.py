"""
Liquidity Model.
Calculates liquidity score and flags illiquid items.
"""
from datetime import datetime
from typing import List
from app.features.liquidity import calculate_market_depth_score, calculate_spread_stability
from app.shared.domain.signal import Signal

class LiquidityModel:
    def __init__(self, illiquid_threshold: float = 30.0):
        self.illiquid_threshold = illiquid_threshold

    def calculate_score(self, bid_volume: float, ask_volume: float, spreads: List[float]) -> float:
        """
        Calculates a liquidity score from 0 to 100.
        Combines depth and spread stability.
        """
        depth = calculate_market_depth_score(bid_volume, ask_volume)
        stability = calculate_spread_stability(spreads)
        
        # Normalize depth (heuristic, ideally needs historical context)
        normalized_depth = min(50.0, depth / 1000.0)
        
        # Combine them (50% depth, 50% stability)
        score = normalized_depth + (stability * 50.0)
        return min(100.0, score)

    def evaluate(self, item_id: str, city: str, bid_volume: float, ask_volume: float, spreads: List[float]) -> Signal | None:
        """
        Evaluates liquidity and returns a signal if it's too low.
        """
        score = self.calculate_score(bid_volume, ask_volume, spreads)
        
        if score < self.illiquid_threshold:
            return Signal(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                signal_type="risk_illiquid",
                strength=(self.illiquid_threshold - score) / self.illiquid_threshold,
                metadata={
                    "liquidity_score": score,
                    "threshold": self.illiquid_threshold
                }
            )
            
        return None
