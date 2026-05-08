from abc import ABC, abstractmethod
from typing import List
from shared.domain.market_snapshot import MarketSnapshot
from shared.domain.signal import Signal

class SignalGenerator(ABC):
    @abstractmethod
    def generate(self, snapshot: MarketSnapshot) -> List[Signal]:
        raise NotImplementedError("Subclasses must implement generate()")
