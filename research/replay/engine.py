"""
Replay Engine.
Reconstructs historical market states and replays signals.
"""
from datetime import datetime
from typing import Iterator, List, Any

class ReplayEngine:
    """
    Engine to replay historical market data.
    """
    def __init__(self, source: str = "db"):
        self.source = source
        self.mock_data: List[Any] = []
        
    def set_mock_data(self, data: List[Any]):
        """Sets data for testing."""
        self.mock_data = data
        
    def replay_iterator(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> Iterator[Any]:
        """
        Yields market states chronologically.
        """
        if self.source == "mock":
            # Filter and sort mock data
            filtered = [
                item for item in self.mock_data
                if start_time <= item.captured_at <= end_time
            ]
            # Sort by captured_at
            filtered.sort(key=lambda x: x.captured_at)
            
            for item in filtered:
                yield item
        else:
            # TODO: Implement database query to yield rows ordered by captured_at
            # Connect to SQLite or Postgres
            # For now, yield nothing or raise NotImplemented
            raise NotImplementedError("Database source not yet implemented")
