"""
Tests for VWAP engine.
"""
from app.execution.vwap import calculate_vwap, calculate_slippage

def test_vwap_single_order():
    orders = [{'price': 10.0, 'volume': 100.0}]
    assert calculate_vwap(orders, 50.0) == 10.0

def test_vwap_multiple_orders():
    orders = [
        {'price': 10.0, 'volume': 50.0},
        {'price': 12.0, 'volume': 50.0}
    ]
    # 50 @ 10 + 50 @ 12 = 500 + 600 = 1100 / 100 = 11.0
    assert calculate_vwap(orders, 100.0) == 11.0

def test_vwap_partial_fill():
    orders = [
        {'price': 10.0, 'volume': 50.0},
        {'price': 12.0, 'volume': 50.0}
    ]
    # 50 @ 10 + 25 @ 12 = 500 + 300 = 800 / 75 = 10.666...
    assert abs(calculate_vwap(orders, 75.0) - 10.666666666666666) < 0.0001

def test_vwap_insufficient_liquidity():
    orders = [{'price': 10.0, 'volume': 50.0}]
    # It will only fill 50, so total cost 500 / 50 = 10.0
    assert calculate_vwap(orders, 100.0) == 10.0

def test_slippage():
    assert calculate_slippage(10.0, 11.0) == 0.1
    assert calculate_slippage(10.0, 9.0) == 0.1
