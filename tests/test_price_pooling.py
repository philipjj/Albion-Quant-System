import pytest
from app.core.opportunity_engine import pool_price_sanity, cross_city_outlier_check


def test_pool_price_sanity_anchors_single_bought_order():
    # User's scenario: Item listed at 100 silver, bought immediately, real market is 150 silver.
    # 24h history average pool price is 150 silver.
    scanned_price = 100
    history_avg = 150.0
    daily_volume = 10  # Low volume

    sanitized_price = pool_price_sanity(scanned_price, history_avg_price=history_avg, daily_volume=daily_volume)

    # Scanned price 100 is < 65% of 150 (97.5), so it should be safely anchored to the 150 pool price!
    assert sanitized_price == 150


def test_pool_price_sanity_leaves_normal_price_intact():
    # Normal price 145 silver against 150 average pool
    scanned_price = 145
    history_avg = 150.0
    daily_volume = 200

    sanitized_price = pool_price_sanity(scanned_price, history_avg_price=history_avg, daily_volume=daily_volume)
    assert sanitized_price == 145


def test_cross_city_outlier_check_anchors_low_dump_traps():
    # 5 Royal cities: Martlock 150, Lymhurst 155, Fort Sterling 160, Thetford 152, Bridgewatch 40 (stale 1-unit dump)
    prices = {
        "Martlock": 150,
        "Lymhurst": 155,
        "Fort Sterling": 160,
        "Thetford": 152,
        "Bridgewatch": 40,
    }

    cleaned = cross_city_outlier_check(prices)

    # Bridgewatch 40 is < 0.35x median (152), so it is anchored to median (152) to avoid false profit
    assert cleaned["Bridgewatch"] == 152
    assert cleaned["Martlock"] == 150
    assert cleaned["Fort Sterling"] == 160


def test_cross_city_outlier_check_discards_high_traps():
    # Bridgewatch troll listing at 1,000,000 when rest are ~1,000
    prices = {
        "Martlock": 1000,
        "Lymhurst": 1050,
        "Fort Sterling": 980,
        "Thetford": 1020,
        "Bridgewatch": 1000000,
    }

    cleaned = cross_city_outlier_check(prices)
    assert cleaned["Bridgewatch"] == 0  # Zeroed out to prevent buying at troll price
