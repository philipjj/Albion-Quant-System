from abc import ABC, abstractmethod
from typing import List

from app.shared.domain.market_snapshot import MarketSnapshot
from app.shared.domain.signal import Signal


class SignalGenerator(ABC):
    @abstractmethod
    def generate(self, snapshot: MarketSnapshot) -> list[Signal]:
        raise NotImplementedError("Subclasses must implement generate()")
