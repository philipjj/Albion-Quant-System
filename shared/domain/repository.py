from abc import ABC, abstractmethod
from shared.domain.market_snapshot import MarketSnapshot

class IMarketDataRepository(ABC):
    @abstractmethod
    def save_snapshots(self, snapshots: list[MarketSnapshot]) -> None:
        """Saves a list of market snapshots to storage."""
        pass
        
    @abstractmethod
    def get_latest_snapshot(self, item_id: str, city: str) -> MarketSnapshot | None:
        """Retrieves the latest market snapshot for a given item and city."""
        pass
