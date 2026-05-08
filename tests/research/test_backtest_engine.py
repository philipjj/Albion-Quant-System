"""
Tests for Backtesting Engine.
"""
from research.backtesting.engine import BacktestEngine, Strategy
from research.replay.engine import ReplayEngine
from app.db.models import MarketPrice
from datetime import datetime, timedelta
import pytest

class MockStrategy(Strategy):
    def __init__(self):
        self.calls = 0
        self.last_event = None
        
    def on_data(self, event):
        self.calls += 1
        self.last_event = event

def test_backtest_engine_runs():
    # Setup mock data in replay engine
    items = [
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow() - timedelta(hours=1)),
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow()),
    ]
    
    replay_engine = ReplayEngine(source="mock")
    replay_engine.set_mock_data(items)
    
    strategy = MockStrategy()
    backtester = BacktestEngine(replay_engine=replay_engine, strategy=strategy)
    
    metrics = backtester.run(
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=1)
    )
    
    assert strategy.calls == 2
    assert strategy.last_event["item_id"] == "T4_SWORD"
    assert "total_events" in metrics
    assert metrics["total_events"] == 2
