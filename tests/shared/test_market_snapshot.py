from datetime import datetime
from shared.domain.market_snapshot import MarketSnapshot

def test_market_snapshot_creation():
    snapshot = MarketSnapshot(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        best_bid=1000.0,
        best_ask=1200.0,
        bid_depth=50,
        ask_depth=40,
        spread=200.0,
        midprice=1100.0,
        rolling_volume=1000,
        volatility=0.05
    )
    assert snapshot.item_id == "T8_HEAD_CLOTH"
    assert snapshot.midprice == 1100.0
