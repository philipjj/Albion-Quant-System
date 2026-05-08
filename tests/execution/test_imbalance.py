"""
Tests for order book imbalance.
"""
from app.execution.imbalance import calculate_imbalance

def test_imbalance_all_bids():
    assert calculate_imbalance(100.0, 0.0) == 1.0

def test_imbalance_all_asks():
    assert calculate_imbalance(0.0, 100.0) == -1.0

def test_imbalance_equal():
    assert calculate_imbalance(50.0, 50.0) == 0.0

def test_imbalance_more_bids():
    assert calculate_imbalance(75.0, 25.0) == 0.5

def test_imbalance_more_asks():
    assert calculate_imbalance(25.0, 75.0) == -0.5

def test_imbalance_zero_denominator():
    assert calculate_imbalance(0.0, 0.0) == 0.0
