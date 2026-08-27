"""
Unit tests for quality inversion detection and quality misprice arbitrage.
"""

from app.features.quality_arbitrage import detect_quality_inversion


def test_detect_quality_inversion_sell_undercut():
    prices = {
        1: {"sell_price_min": 100_000, "buy_price_max": 80_000, "data_age_seconds": 300, "volume_24h": 10},
        2: {"sell_price_min": 70_000, "buy_price_max": 60_000, "data_age_seconds": 300, "volume_24h": 10},  # Q2 listed cheaper than Q1!
    }
    
    inversions = detect_quality_inversion(
        prices,
        item_id="T6_2H_CLEAVER",
        city="Bridgewatch",
        tax_rate=0.08,
        setup_fee_rate=0.025,
        min_volume=1,
    )
    assert len(inversions) == 1
    inv = inversions[0]
    assert inv["buy_quality"] == 2
    assert inv["buy_price"] == 70_000
    assert inv["reference_quality"] == 1
    assert inv["reference_price"] == 100_000
    # Net payout = 100,000 * (1 - 0.08 - 0.025) = 89,500
    # Net profit = 89,500 - 70,000 = 19,500
    assert inv["net_profit"] == 19_500.0
    assert inv["profit_pct"] == 27.86  # (19500 / 70000) * 100 = 27.857...


def test_detect_quality_inversion_no_misprice():
    prices = {
        1: {"sell_price_min": 100_000, "buy_price_max": 80_000, "data_age_seconds": 300, "volume_24h": 10},
        2: {"sell_price_min": 120_000, "buy_price_max": 90_000, "data_age_seconds": 300, "volume_24h": 10},  # Q2 higher than Q1 (normal)
    }
    
    inversions = detect_quality_inversion(prices, item_id="T6_2H_CLEAVER", city="Bridgewatch")
    assert len(inversions) == 0


def test_detect_quality_inversion_zero_volume_filtered():
    # 0-volume item trap: Q4 Excellent listed at 8M, Q3 Outstanding at 12M (volume 0)
    prices_high_zero_vol = {
        3: {"sell_price_min": 12_000_000, "buy_price_max": 5_000_000, "data_age_seconds": 300, "volume_24h": 5},
        4: {"sell_price_min": 8_000_000, "buy_price_max": 4_000_000, "data_age_seconds": 300, "volume_24h": 0},  # 0 volume!
    }
    inversions = detect_quality_inversion(prices_high_zero_vol, item_id="T8_NATURESTAFF", city="Bridgewatch", min_volume=1, allow_zero_volume=False)
    assert len(inversions) == 0

    prices_low_zero_vol = {
        3: {"sell_price_min": 12_000_000, "buy_price_max": 5_000_000, "data_age_seconds": 300, "volume_24h": 0},  # 0 volume!
        4: {"sell_price_min": 8_000_000, "buy_price_max": 4_000_000, "data_age_seconds": 300, "volume_24h": 5},
    }
    inversions2 = detect_quality_inversion(prices_low_zero_vol, item_id="T8_NATURESTAFF", city="Bridgewatch", min_volume=1, allow_zero_volume=False)
    assert len(inversions2) == 0


def test_detect_quality_inversion_post_tax_deductions():
    # Premium tax (4%) + setup fee (2.5%) = 6.5% total fee
    prices = {
        1: {"sell_price_min": 1_000_000, "buy_price_max": 500_000, "data_age_seconds": 300, "volume_24h": 10},
        2: {"sell_price_min": 800_000, "buy_price_max": 400_000, "data_age_seconds": 300, "volume_24h": 10},
    }
    inversions = detect_quality_inversion(
        prices,
        item_id="T7_MAIN_SWORD",
        city="Lymhurst",
        tax_rate=0.04,
        setup_fee_rate=0.025,
        min_volume=1,
    )
    assert len(inversions) == 1
    inv = inversions[0]
    # Net payout = 1,000,000 * (1 - 0.04 - 0.025) = 935,000
    # Net profit = 935,000 - 800,000 = 135,000
    assert inv["net_profit"] == 135_000.0


def test_detect_quality_inversion_outlier_ratio_rejected():
    # Low quality (12M) vs High quality (4M) -> ratio = 3.0x > max_price_ratio (2.5x)
    prices = {
        3: {"sell_price_min": 12_000_000, "buy_price_max": 5_000_000, "data_age_seconds": 300, "volume_24h": 10},
        4: {"sell_price_min": 4_000_000, "buy_price_max": 2_000_000, "data_age_seconds": 300, "volume_24h": 10},
    }
    inversions = detect_quality_inversion(
        prices,
        item_id="T8_2H_NATURESTAFF",
        city="Fort Sterling",
        min_volume=1,
        max_price_ratio=2.5,
    )
    assert len(inversions) == 0


def test_detect_quality_inversion_instant_bm_fill():
    # Instant fill on buy order: tax_rate=0.08 applied, setup_fee not applied on buy order fill
    prices = {
        1: {"sell_price_min": 0, "buy_price_max": 100_000, "data_age_seconds": 300, "volume_24h": 10},
        2: {"sell_price_min": 70_000, "buy_price_max": 50_000, "data_age_seconds": 300, "volume_24h": 10},
    }
    inversions = detect_quality_inversion(
        prices,
        item_id="T6_MAIN_CURSED",
        city="Caerleon",
        tax_rate=0.08,
        setup_fee_rate=0.025,
        min_volume=1,
    )
    assert len(inversions) == 1
    inv = inversions[0]
    assert inv["inversion_type"] == "INSTANT_BM_FILL"
    # Net payout = 100,000 * (1 - 0.08) = 92,000
    # Net profit = 92,000 - 70,000 = 22,000
    assert inv["net_profit"] == 22_000.0
