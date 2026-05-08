"""
Market Advisor.
Synthesizes signals and regimes into actionable recommendations.
"""
from datetime import datetime
from typing import List
from app.shared.domain.signal import Signal
from app.intelligence.recommendations import Recommendation

class MarketAdvisor:
    def generate_recommendation(self, item_id: str, city: str, signals: List[Signal], regime: str) -> Recommendation:
        """
        Generates a recommendation based on signals and current market regime.
        """
        if not signals:
            return Recommendation(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                action="hold",
                reason="No signals generated",
                confidence=1.0
            )
            
        # Aggregate signals
        buy_strength = sum(s.strength for s in signals if "buy" in s.signal_type)
        sell_strength = sum(s.strength for s in signals if "sell" in s.signal_type)
        
        # Adjust based on regime
        if regime == 'mean_reverting':
            # Mean reversion signals are more reliable in this regime
            buy_strength *= 1.5
            sell_strength *= 1.5
        elif regime == 'trending':
            # Trend following signals would be more reliable here
            pass
        elif regime == 'volatile':
            # Reduce confidence in all signals in volatile regimes
            buy_strength *= 0.5
            sell_strength *= 0.5
            
        if buy_strength > sell_strength and buy_strength > 0.5:
            return Recommendation(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                action="buy",
                reason=f"Strong buy signals in {regime} regime",
                confidence=min(1.0, buy_strength / 2.0),
                metadata={"regime": regime, "buy_strength": buy_strength, "sell_strength": sell_strength}
            )
        elif sell_strength > buy_strength and sell_strength > 0.5:
            return Recommendation(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                action="sell",
                reason=f"Strong sell signals in {regime} regime",
                confidence=min(1.0, sell_strength / 2.0),
                metadata={"regime": regime, "buy_strength": buy_strength, "sell_strength": sell_strength}
            )
            
        return Recommendation(
            item_id=item_id,
            city=city,
            timestamp=datetime.utcnow(),
            action="hold",
            reason="Conflicting or weak signals",
            confidence=1.0,
            metadata={"regime": regime, "buy_strength": buy_strength, "sell_strength": sell_strength}
        )
