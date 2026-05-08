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
        
    def on_data(self, event, engine):
        self.calls += 1
        self.last_event = event

class TradingStrategy(Strategy):
    def on_data(self, event, engine):
        # Buy on first event, sell on second
        if engine.positions.get(event["item_id"], 0) == 0:
            engine.execute_order(event["item_id"], quantity=1, price=100.0, side="buy")
        else:
            engine.execute_order(event["item_id"], quantity=1, price=120.0, side="sell")

def test_backtest_engine_runs():
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
    assert metrics["total_events"] == 2

def test_backtest_execution():
    items = [
        {"item_id": "T4_SWORD", "city": "Caerleon", "captured_at": datetime.utcnow() - timedelta(hours=1)},
        {"item_id": "T4_SWORD", "city": "Caerleon", "captured_at": datetime.utcnow()},
    ]
    
    # We can use mock data directly if we yield dicts
    replay_engine = ReplayEngine(source="mock")
    # Need to adapt set_mock_data or just mock the iterator
    
    class MockReplay:
        def replay_iterator(self, start, end):
            for item in items:
                yield item
                
    strategy = TradingStrategy()
    backtester = BacktestEngine(replay_engine=MockReplay(), strategy=strategy, initial_cash=1000.0)
    
    metrics = backtester.run(
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=1)
    )
    
    # Cash should be 1000 - 100 + 120 = 1020
    assert backtester.cash == 1020.0
    assert backtester.positions["T4_SWORD"] == 0
    assert metrics["pnl"] == 20.0
