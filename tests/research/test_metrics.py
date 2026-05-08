"""
Tests for Quant Metrics.
"""
from research.diagnostics.metrics import calculate_hit_rate, calculate_sharpe_ratio
import pytest

def test_hit_rate():
    outcomes = [1, 0, 1, 1, 0]  # 3 hits out of 5
    assert calculate_hit_rate(outcomes) == 0.6

def test_sharpe_ratio():
    returns = [0.01, 0.02, -0.01, 0.03, 0.0]
    # Mean: 0.01
    # Std: ~0.014
    # Sharpe: ~0.7
    sharpe = calculate_sharpe_ratio(returns)
    assert sharpe > 0.5
    
def test_sharpe_ratio_zero_std():
    returns = [0.01, 0.01, 0.01]
    assert calculate_sharpe_ratio(returns) == 0.0  # Or handle as special case

def test_max_drawdown():
    equity_curve = [100.0, 110.0, 90.0, 120.0]
    # Peak: 110, Trough: 90 -> Drop: 20 -> 20/110 = ~0.1818
    from research.diagnostics.metrics import calculate_max_drawdown
    mdd = calculate_max_drawdown(equity_curve)
    assert abs(mdd - 0.1818) < 0.001
