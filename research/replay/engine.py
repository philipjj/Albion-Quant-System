"""
Replay Engine.
Reconstructs historical market states and replays signals.
"""
from datetime import datetime
from typing import Iterator, List, Any, Dict
import sqlite3
import os

class ReplayEngine:
    """
    Engine to replay historical market data.
    """
    def __init__(self, source: str = "db", db_path: str = "data/albion_quant.db"):
        self.source = source
        self.db_path = db_path
        self.mock_data: List[Any] = []
        
    def set_mock_data(self, data: List[Any]):
        """Sets data for testing."""
        self.mock_data = data
        
    def replay_iterator(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> Iterator[Dict[str, Any]]:
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
                yield {
                    "item_id": item.item_id,
                    "city": item.city,
                    "captured_at": item.captured_at
                }
        else:
            if not os.path.exists(self.db_path):
                raise FileNotFoundError(f"Database file not found: {self.db_path}")
                
            conn = sqlite3.connect(self.db_path)
            # Use Row factory to get dict-like objects
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Query market_prices ordered by captured_at
            # We filter by time if requested
            query = """
                SELECT * FROM market_prices 
                WHERE captured_at >= ? AND captured_at <= ?
                ORDER BY captured_at ASC
            """
            
            cursor.execute(query, (start_time.strftime('%Y-%m-%d %H:%M:%S'), end_time.strftime('%Y-%m-%d %H:%M:%S')))
            
            for row in cursor:
                # Convert row to dict
                data = dict(row)
                # Parse captured_at string back to datetime if needed
                # For now, just yield the dict
                yield data
                
            conn.close()
