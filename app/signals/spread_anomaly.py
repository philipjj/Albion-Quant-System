from typing import List
from shared.domain.market_snapshot import MarketSnapshot
from shared.domain.signal import Signal
from app.signals.base import SignalGenerator
from app.features.spread import calculate_relative_spread

class SpreadAnomalyGenerator(SignalGenerator):
    def __init__(self, threshold: float):
        self.threshold = threshold
        
    def generate(self, snapshot: MarketSnapshot) -> List[Signal]:
        rel_spread = calculate_relative_spread(snapshot.best_ask, snapshot.best_bid)
        if rel_spread > self.threshold:
            return [
                Signal(
                    item_id=snapshot.item_id,
                    city=snapshot.city,
                    timestamp=snapshot.timestamp,
                    signal_type="spread_anomaly",
                    strength=rel_spread,
                    metadata={"threshold": self.threshold}
                )
            ]
        return []
