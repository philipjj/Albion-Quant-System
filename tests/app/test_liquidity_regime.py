"""
Tests for liquidity regime detector.
"""
from app.regime.liquidity_regime import detect_liquidity_regime
import pytest

def test_liquid_regime():
    volumes = [1000.0, 1200.0, 1100.0]
    assert detect_liquidity_regime(volumes, threshold=500.0) == "liquid"

def test_illiquid_regime():
    volumes = [100.0, 50.0, 80.0]
    assert detect_liquidity_regime(volumes, threshold=500.0) == "illiquid"
