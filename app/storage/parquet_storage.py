import os
from typing import List
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime
from app.shared.domain.market_snapshot import MarketSnapshot
from loguru import logger

class ParquetHistoricalStorage:
    """Handles saving market snapshots to partitioned Parquet files for historical research."""
    
    def __init__(self, base_path: str = "data/historical"):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    def save_snapshots(self, snapshots: List[MarketSnapshot]):
        """Saves a list of snapshots to the Parquet dataset."""
        if not snapshots:
            return

        # Convert to DataFrame
        data = []
        for s in snapshots:
            d = s.model_dump()
            # Add partition columns from timestamp
            ts = s.timestamp
            d['year'] = ts.year
            d['month'] = ts.month
            d['day'] = ts.day
            data.append(d)

        df = pd.DataFrame(data)
        
        # Convert to PyArrow Table
        table = pa.Table.from_pandas(df)

        try:
            # Write to dataset with partitioning
            # This automatically handles creating the directory structure:
            # base_path/year=YYYY/month=MM/day=DD/city=CITY/item_id=ITEM/
            pq.write_to_dataset(
                table,
                root_path=self.base_path,
                partition_cols=['year', 'month', 'day', 'city', 'item_id']
            )
            logger.info(f"Saved {len(snapshots)} snapshots to Parquet dataset at {self.base_path}")
        except Exception as e:
            logger.error(f"Failed to save snapshots to Parquet: {e}")
            raise e
