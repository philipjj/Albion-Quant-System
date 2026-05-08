"""
Tests for trend regime detector.
"""
from app.regime.trend_regime import detect_trend_regime
import pytest

def test_trending_up():
    prices = [100.0, 102.0, 105.0, 107.0, 110.0]
    assert detect_trend_regime(prices) == "trending"

def test_trending_down():
    prices = [110.0, 107.0, 105.0, 102.0, 100.0]
    assert detect_trend_regime(prices) == "trending"

def test_ranging():
    prices = [100.0, 102.0, 100.0, 101.0, 100.0]
    assert detect_trend_regime(prices) == "ranging"
