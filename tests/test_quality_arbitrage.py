"""
Unit tests for quality inversion detection and quality misprice arbitrage.
"""

from app.features.quality_arbitrage import detect_quality_inversion


def test_detect_quality_inversion_sell_undercut():
    prices = {
        1: {"sell_price_min": 100_000, "buy_price_max": 80_000, "data_age_seconds": 300, "volume_24h": 10},
        2: {"sell_price_min": 70_000, "buy_price_max": 60_000, "data_age_seconds": 300, "volume_24h": 10},  # Q2 listed cheaper than Q1!
    }
    
    inversions = detect_quality_inversion(prices, item_id="T6_2H_CLEAVER", city="Bridgewatch")
    assert len(inversions) == 1
    inv = inversions[0]
    assert inv["buy_quality"] == 2
    assert inv["buy_price"] == 70_000
    assert inv["reference_quality"] == 1
    assert inv["reference_price"] == 100_000
    assert inv["net_profit"] == 30_000


def test_detect_quality_inversion_no_misprice():
    prices = {
        1: {"sell_price_min": 100_000, "buy_price_max": 80_000, "data_age_seconds": 300, "volume_24h": 10},
        2: {"sell_price_min": 120_000, "buy_price_max": 90_000, "data_age_seconds": 300, "volume_24h": 10},  # Q2 higher than Q1 (normal)
    }
    
    inversions = detect_quality_inversion(prices, item_id="T6_2H_CLEAVER", city="Bridgewatch")
    assert len(inversions) == 0
