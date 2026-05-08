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
