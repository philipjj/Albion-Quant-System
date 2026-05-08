from abc import ABC, abstractmethod
from app.shared.domain.market_snapshot import MarketSnapshot

class IMarketDataRepository(ABC):
    @abstractmethod
    async def save_snapshots(self, snapshots: list[MarketSnapshot]) -> None:
        """Saves a list of market snapshots to storage."""
        pass
        
    @abstractmethod
    async def get_latest_snapshot(self, item_id: str, city: str) -> MarketSnapshot | None:
        """Retrieves the latest market snapshot for a given item and city."""
        pass
        
    @abstractmethod
    async def get_historical_prices(self, item_id: str, city: str, limit: int = 100) -> list[float]:
        """Retrieves a list of historical midprices for a given item and city."""
        pass
        
    @abstractmethod
    async def update_volume(self, item_id: str, city: str, quality: int, volume: int) -> None:
        """Updates the volume for the latest snapshot of an item and city."""
        pass
