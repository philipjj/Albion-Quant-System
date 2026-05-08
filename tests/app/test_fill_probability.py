"""
Tests for fill probability modeling.
"""
from app.simulation.fill_probability import calculate_fill_probability

def test_high_probability_buy():
    # Buy order with negative imbalance (more sellers/supply)
    # Low volatility, low spread
    prob = calculate_fill_probability(
        order_type="buy",
        imbalance=-0.8,
        volatility=0.01,
        spread=10.0,
        volume=1000.0
    )
    # 0.5 - (-0.8 * 0.3) = 0.74
    # - 0.005 = 0.735
    # - 0.01 = 0.725
    # + 0.05 = 0.775
    assert prob > 0.7
    assert 0.0 <= prob <= 1.0

def test_low_probability_buy():
    # Buy order with positive imbalance (more buyers/demand)
    # High volatility, high spread
    prob = calculate_fill_probability(
        order_type="buy",
        imbalance=0.8,
        volatility=0.1,
        spread=100.0,
        volume=100.0
    )
    # 0.5 - (0.8 * 0.3) = 0.26
    # - 0.05 = 0.21
    # - 0.1 = 0.11
    # + 0.005 = 0.115
    assert prob < 0.4
    assert 0.0 <= prob <= 1.0

def test_high_probability_sell():
    # Sell order easier when Imbalance > 0 (more buyers)
    prob = calculate_fill_probability(
        order_type="sell",
        imbalance=0.8,
        volatility=0.01,
        spread=10.0,
        volume=1000.0
    )
    assert prob > 0.7
    
def test_low_probability_sell():
    # Sell order harder when Imbalance < 0 (more sellers)
    prob = calculate_fill_probability(
        order_type="sell",
        imbalance=-0.8,
        volatility=0.1,
        spread=100.0,
        volume=100.0
    )
    assert prob < 0.4
