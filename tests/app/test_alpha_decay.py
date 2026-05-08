"""
Tests for alpha decay modeling.
"""
from app.simulation.alpha_decay import estimate_alpha_decay

def test_slow_decay():
    # Low volume, short elapsed time -> long remaining lifetime
    result = estimate_alpha_decay(
        initial_strength=1.0,
        current_strength=0.9,
        elapsed_time=60.0,  # 1 minute
        market_volume=10.0
    )
    assert result["expected_remaining_lifetime"] > 300.0  # > 5 mins
    assert result["decay_velocity"] < 0.01

def test_fast_decay():
    # High volume, long elapsed time -> short remaining lifetime
    result = estimate_alpha_decay(
        initial_strength=1.0,
        current_strength=0.5,
        elapsed_time=300.0,  # 5 minutes
        market_volume=100.0
    )
    assert result["expected_remaining_lifetime"] < 600.0  # < 10 mins
    assert result["decay_velocity"] > 0.001
