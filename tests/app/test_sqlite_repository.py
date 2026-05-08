import pytest
from datetime import datetime
from app.db.session import init_db, get_db_session
from app.db.repository import SQLiteMarketDataRepository
from shared.domain.market_snapshot import MarketSnapshot

@pytest.fixture(autouse=True)
def setup_db():
    # Initialize DB tables
    init_db()
    yield

def test_save_and_get_latest_snapshot():
    repo = SQLiteMarketDataRepository()
    
    snapshot = MarketSnapshot(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        quality=1,
        timestamp=datetime.utcnow(),
        best_bid=1000.0,
        best_ask=1200.0,
        bid_depth=10,
        ask_depth=10,
        spread=200.0,
        midprice=1100.0,
        rolling_volume=100,
        volatility=0.0
    )
    
    repo.save_snapshots([snapshot])
    
    retrieved = repo.get_latest_snapshot("T8_HEAD_CLOTH", "Bridgewatch")
    
    assert retrieved is not None
    assert retrieved.item_id == "T8_HEAD_CLOTH"
    assert retrieved.city == "Bridgewatch"
    assert retrieved.best_bid == 1000.0
    assert retrieved.best_ask == 1200.0
