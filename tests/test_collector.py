import pytest
from unittest.mock import AsyncMock, MagicMock
from app.ingestion.collector import MarketCollector

@pytest.mark.asyncio
async def test_collect_partition_smoke():
    collector = MarketCollector(
        repository=MagicMock(), 
        parquet_storage=MagicMock(), 
        redis_cache=MagicMock()
    )
    # Mock fetch_market_data to avoid real API calls
    collector.fetch_market_data = AsyncMock(return_value=[])
    
    # Mock DB interaction and category filtering
    collector._get_tradeable_items_info = MagicMock(return_value={"ITEM1": {"category": "weapon"}})
    collector.should_poll_category = MagicMock(return_value=True)
    
    # Should run and return batches
    result = await collector.collect_partition(0, 6)
    assert result is not None
