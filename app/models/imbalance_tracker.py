"""
Imbalance Tracker Model.
Tracks order book imbalance and generates signals.
"""
from datetime import datetime
from typing import List
from app.features.imbalance import calculate_imbalance
from app.shared.domain.signal import Signal

class ImbalanceTracker:
    def __init__(self, threshold: float = 0.6, consecutive_periods: int = 3):
        self.threshold = threshold
        self.consecutive_periods = consecutive_periods

    def evaluate(self, item_id: str, city: str, snapshots: List[dict]) -> Signal | None:
        """
        Evaluates a sequence of snapshots for imbalance signals.
        If imbalance > threshold for N consecutive snapshots -> trigger signal.
        snapshots is a list of dicts with 'bid_volume' and 'ask_volume'.
        """
        if len(snapshots) < self.consecutive_periods:
            return None
            
        imbalances = []
        for snap in snapshots:
            imb = calculate_imbalance(snap.get('bid_volume', 0), snap.get('ask_volume', 0))
            imbalances.append(imb)
            
        # Check the last N periods
        last_n = imbalances[-self.consecutive_periods:]
        
        # All must be above threshold (positive means buy pressure)
        if all(imb > self.threshold for imb in last_n):
            return Signal(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                signal_type="momentum_buy",
                strength=sum(last_n) / len(last_n),
                metadata={
                    "consecutive_imbalances": last_n,
                    "threshold": self.threshold
                }
            )
            
        # All must be below -threshold (negative means sell pressure)
        if all(imb < -self.threshold for imb in last_n):
            return Signal(
                item_id=item_id,
                city=city,
                timestamp=datetime.utcnow(),
                signal_type="momentum_sell",
                strength=abs(sum(last_n) / len(last_n)),
                metadata={
                    "consecutive_imbalances": last_n,
                    "threshold": self.threshold
                }
            )
            
        return None
