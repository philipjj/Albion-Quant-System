import pytest
from datetime import datetime
from shared.domain.market_snapshot import MarketSnapshot
from app.signals.base import SignalGenerator

def test_base_signal_generator_not_implemented():
    class DummyGenerator(SignalGenerator):
        def generate(self, snapshot):
            return super().generate(snapshot)
        
    gen = DummyGenerator()
    snapshot = MarketSnapshot(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        best_bid=1000.0,
        best_ask=1200.0,
        bid_depth=10,
        ask_depth=10,
        spread=200.0,
        midprice=1100.0,
        rolling_volume=100,
        volatility=0.1
    )
    with pytest.raises(NotImplementedError):
        gen.generate(snapshot)
