import math
from datetime import datetime
from typing import Any, Dict, Optional


class Scorer:
    """
    Advanced AQS v3.1+ Intelligence Engine.
    Implements Liquidity-Aware Opportunity Scoring and Confidence Engine.
    Goal: Calculate 'Expected Realized Profit per Hour' (ERPH).
    """

    def calculate_data_confidence(self, opp: dict[str, Any]) -> float:
        """
        Calculates a 0.0 -> 1.0 confidence score based on data age and market liquidity.
        """
        # 1. Exponential Freshness Decay (Task 7.1)
        age_sec = opp.get("data_age_seconds") or 0
        age_min = age_sec / 60.0
        # Decay constant: 45 min half-life
        freshness = math.exp(-age_min / 45.0)

        # 2. Liquidity Confidence
        volume = opp.get("daily_volume", 0)
        volume_score = min(1.0, volume / 50.0) if volume > 0 else 0.1

        # 3. Persistence Bonus
        persistence = opp.get("persistence", 1)
        persistence_bonus = min(0.3, (persistence - 1) * 0.1)

        # 4. Volatility Penalty
        volatility = opp.get("volatility", 0.05)
        volatility_penalty = max(0.0, volatility * 2.0)

        confidence = (freshness * 0.4) + (volume_score * 0.3) + persistence_bonus - volatility_penalty
        return round(max(0.05, min(1.0, confidence)), 4)

    def calculate_fill_probability(self, volume_24h: int, margin_pct: float) -> float:
        """Estimates execution probability."""
        if volume_24h <= 0: return 0.05
        vol_factor = min(1.0, volume_24h / 150)
        margin_penalty = 1.0
        if margin_pct > 30: margin_penalty = 0.6
        if margin_pct > 100: margin_penalty = 0.1
        return round(vol_factor * margin_penalty, 2)

    def score_arbitrage(self, opp: dict[str, Any]) -> float:
        """Calculates ERPH for Arbitrage."""
        net_profit = opp.get("estimated_profit", 0)
        margin_pct = opp.get("estimated_margin", 0)
        volume = opp.get("daily_volume", 0)
        
        fill_prob = self.calculate_fill_probability(volume, margin_pct)
        confidence = self.calculate_data_confidence(opp)
        
        from app.core.constants import DANGEROUS_ROUTES, get_distance
        dist = get_distance(opp["source_city"], opp["destination_city"])
        
        is_dangerous = (opp["source_city"], opp["destination_city"]) in DANGEROUS_ROUTES
        risk_multiplier = 1.5 if is_dangerous else 1.0
        transport_cost = (dist * 1000) * risk_multiplier
        
        # [v3.1] Strictly unit-based expected value to avoid Alpha hallucinations
        erph = (net_profit * fill_prob * confidence) - transport_cost
        
        opp["fill_prob"] = fill_prob
        opp["confidence"] = confidence
        opp["transport_cost"] = transport_cost
        
        return round(max(0.0, erph), 2)

    def score_crafting(self, opp: dict[str, Any]) -> float:
        """Calculates ERPH for Crafting."""
        net_profit = opp.get("profit", 0)
        margin_pct = opp.get("profit_margin", 0)
        volume = opp.get("daily_volume", 0)
        
        fill_prob = self.calculate_fill_probability(volume, margin_pct)
        confidence = self.calculate_data_confidence(opp)
        
        craft_overhead = 1500 
        # [v3.1] Strictly unit-based expected value to avoid Alpha hallucinations
        erph = (net_profit * fill_prob * confidence) - craft_overhead
        
        opp["fill_prob"] = fill_prob
        opp["confidence"] = confidence
        
        return round(max(0.0, erph), 2)

scorer = Scorer()
