"""
Integration test for the full system.
Tests Replay, Backtesting, and Metrics together.
"""
from research.replay.engine import ReplayEngine
from research.backtesting.engine import BacktestEngine
from research.backtesting.strategy import SimpleArbitrageStrategy
from app.db.models import MarketPrice
from datetime import datetime, timedelta
import pytest

def test_full_system_integration():
    # 1. Setup mock data
    items = [
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow() - timedelta(hours=1)),
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow()),
    ]
    
    # We need to set price or sell_price_min!
    # MarketPrice might not have 'price' attribute in the model if it uses 'sell_price_min'
    # Let's check the model or just use dictionaries if we assume the iterator handles it.
    # The iterator yields dictionaries!
    
    class MockReplay(ReplayEngine):
        def replay_iterator(self, start, end):
            yield {"item_id": "T4_SWORD", "city": "Caerleon", "price": 100.0, "captured_at": datetime.utcnow()}
            yield {"item_id": "T4_SWORD", "city": "Bridgewatch", "price": 150.0, "captured_at": datetime.utcnow()}

    # 2. Initialize components
    replay_engine = MockReplay(source="mock")
    strategy = SimpleArbitrageStrategy()
    backtester = BacktestEngine(replay_engine=replay_engine, strategy=strategy, initial_cash=10000.0)
    
    # 3. Run backtest
    metrics = backtester.run(
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=1)
    )
    
    # 4. Verify results
    assert metrics["status"] == "completed"
    assert metrics["total_events"] == 2
    assert "sharpe_ratio" in metrics
    assert "max_drawdown" in metrics
    
    # The strategy should have recorded prices
    assert "T4_SWORD" in strategy.prices
    assert strategy.prices["T4_SWORD"]["Caerleon"] == 100.0
    assert strategy.prices["T4_SWORD"]["Bridgewatch"] == 150.0
