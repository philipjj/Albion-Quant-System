"""
Tests for backtesting strategies.
"""
from research.backtesting.strategy import SimpleArbitrageStrategy
from research.backtesting.engine import BacktestEngine
import pytest

class MockEngine:
    def __init__(self):
        self.orders = []
        self.positions = {}
        self.cash = 10000.0
        
    def execute_order(self, item_id, quantity, price, side):
        self.orders.append((item_id, quantity, price, side))
        if side == "buy":
            self.positions[item_id] = self.positions.get(item_id, 0.0) + quantity
        elif side == "sell":
            self.positions[item_id] = self.positions.get(item_id, 0.0) - quantity

def test_simple_arbitrage_strategy():
    strategy = SimpleArbitrageStrategy()
    engine = MockEngine()
    
    # Event 1: Low price in City A
    event1 = {"item_id": "T4_SWORD", "city": "Caerleon", "price": 100.0}
    strategy.on_data(event1, engine)
    
    # Event 2: High price in City B
    event2 = {"item_id": "T4_SWORD", "city": "Bridgewatch", "price": 150.0}
    strategy.on_data(event2, engine)
    
    # Strategy should detect that 100 < 150 and buy in Caerleon, sell in Bridgewatch
    # In a real event-driven system, it would buy at 100 and then sell at 150 later
    # Let's see how we implement it.
    
    # If the strategy keeps track of best prices across cities:
    # On event 2, it sees Bridgewatch is 150, and last Caerleon was 100.
    # So it buys at 100 (if possible) or just flags the opportunity.
    
    # Let's assume the strategy simply buys if price < threshold and sells if price > threshold.
    # Or stores the state.
    
    # Let's check if it recorded prices
    assert strategy.prices["T4_SWORD"]["Caerleon"] == 100.0
    assert strategy.prices["T4_SWORD"]["Bridgewatch"] == 150.0
