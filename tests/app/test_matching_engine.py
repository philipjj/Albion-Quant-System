"""
Tests for the matching engine.
"""
from app.simulation.matching_engine import match_order

def test_match_order_simple():
    snapshot = {
        "ask_price": 100.0,
        "ask_volume": 10.0,
        "bid_price": 90.0,
        "bid_volume": 10.0
    }
    
    # Buy crossing ask
    result = match_order("buy", 5.0, 105.0, snapshot)
    assert result["executed_size"] == 5.0
    assert result["avg_price"] == 100.0
    assert result["remaining_size"] == 0.0

def test_match_order_depth():
    # Snapshot with depth (lists of [price, volume])
    snapshot = {
        "asks": [
            [100.0, 5.0],
            [105.0, 10.0],
            [110.0, 20.0]
        ],
        "bids": [
            [95.0, 5.0],
            [90.0, 10.0],
            [85.0, 20.0]
        ]
    }
    
    # Buy 10 units at limit 110
    # Should match 5 at 100 and 5 at 105
    # Avg price: (5*100 + 5*105) / 10 = 102.5
    result = match_order("buy", 10.0, 110.0, snapshot)
    assert result["executed_size"] == 10.0
    assert result["avg_price"] == 102.5
    assert result["remaining_size"] == 0.0
    
def test_match_order_depth_partial():
    snapshot = {
        "asks": [
            [100.0, 5.0],
            [105.0, 10.0]
        ]
    }
    
    # Buy 20 units at limit 110
    # Should match 5 at 100, 10 at 105. Total 15 executed.
    # Avg price: (5*100 + 10*105) / 15 = 103.333...
    result = match_order("buy", 20.0, 110.0, snapshot)
    assert result["executed_size"] == 15.0
    assert abs(result["avg_price"] - 103.33333333333333) < 0.0001
    assert result["remaining_size"] == 5.0
