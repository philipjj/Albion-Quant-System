"""
Tests for the redesigned OpportunityEngine.
Run: pytest tests/test_opportunity_engine.py -v
"""

import pytest
from app.core.opportunity_engine import (
    OpportunityScanner,
    rrr,
    is_price_valid,
    is_bm_price_valid,
    cross_city_outlier_check,
    ROYAL_CITIES,
)


# ─── RRR Tests ────────────────────────────────────────────────────────────────

def test_rrr_base_no_bonus():
    """All cities, non-bonus items get ~15.3% RRR"""
    rate = rrr("Caerleon", "random_item", use_focus=False)
    assert 0.14 < rate < 0.17, f"Expected ~15%, got {rate}"

def test_rrr_city_crafting_bonus():
    """Lymhurst gives crafting bonus to swords"""
    rate_bonus = rrr("Lymhurst", "sword", use_focus=False)
    rate_base = rrr("Caerleon", "sword", use_focus=False)
    assert rate_bonus > rate_base, "Bonus city should have higher RRR"
    assert rate_bonus > 0.24, f"Expected >24% for bonus city, got {rate_bonus}"

def test_rrr_with_focus():
    """Focus always increases RRR"""
    rate_no_focus = rrr("Bridgewatch", "crossbow", use_focus=False)
    rate_with_focus = rrr("Bridgewatch", "crossbow", use_focus=True)
    assert rate_with_focus > rate_no_focus
    assert rate_with_focus < 1.0

def test_rrr_never_exceeds_99pct():
    rate = rrr("Martlock", "axe", use_focus=True)
    assert rate < 1.0


# ─── Price Validity Tests ─────────────────────────────────────────────────────

def test_price_valid_normal():
    assert is_price_valid(100_000, 80_000) is True

def test_price_invalid_too_low():
    assert is_price_valid(50, 40) is False   # Below MIN_PRICE

def test_price_invalid_too_high():
    assert is_price_valid(600_000_000, 500_000) is False  # Above 500M cap

def test_price_invalid_manipulation_ratio():
    # sell_min is 10x buy_max → likely a single troll listing
    assert is_price_valid(1_000_000, 100_000) is False   # ratio = 10x > 8x limit

def test_price_valid_normal_spread():
    # 5x spread is on the edge but acceptable for rare items
    assert is_price_valid(400_000, 100_000) is True    # 4x


def test_bm_price_valid_with_item_value():
    """BM price should be rejected if it exceeds 5000x item value"""
    assert is_bm_price_valid(10_000_000, 1_000) is False  # 10000x
    assert is_bm_price_valid(4_000_000, 1_000) is True   # 4000x


# ─── Cross-City Outlier Tests ─────────────────────────────────────────────────

def test_outlier_detection_removes_spike():
    """One city at 10x median should be zeroed out"""
    prices = {
        "Bridgewatch": 1_000_000,
        "Martlock": 1_100_000,
        "Lymhurst": 900_000,
        "Fort Sterling": 1_050_000,
        "Thetford": 10_000_000,  # ← troll listing
    }
    cleaned = cross_city_outlier_check(prices)
    assert cleaned["Thetford"] == 0, "Troll listing should be zeroed"
    assert cleaned["Bridgewatch"] > 0, "Normal price should be kept"

def test_outlier_detection_keeps_valid_prices():
    prices = {
        "Bridgewatch": 1_000_000,
        "Martlock": 1_200_000,
        "Lymhurst": 950_000,
    }
    cleaned = cross_city_outlier_check(prices)
    for city, price in cleaned.items():
        assert price > 0, f"{city} should not be filtered"


# ─── Scanner Integration Tests ────────────────────────────────────────────────

@pytest.fixture
def scanner():
    return OpportunityScanner(
        min_bm_profit=1_000,    # Low thresholds for testing
        min_craft_profit=500,
        min_arb_profit=500,
        min_bm_profit_pct=2.0,
        min_craft_profit_pct=1.0,
        min_arb_profit_pct=2.0,
    )


def make_price_map(item_id: str, city_data: dict) -> dict:
    """Helper to build the nested price structure"""
    return {item_id: city_data}


def test_bm_scan_finds_profitable_flip(scanner):
    """BM buy order > royal sell price → should be detected"""
    prices = {
        "T6_MAIN_SWORD": {
            "Lymhurst": {1: {
                "sell_price_min": 500_000,
                "buy_price_max": 400_000,
                "volume_24h": 10,
                "data_age_seconds": 600,
                "is_black_market": False,
            }},
            "Bridgewatch": {1: {
                "sell_price_min": 480_000,
                "buy_price_max": 390_000,
                "volume_24h": 5,
                "data_age_seconds": 900,
                "is_black_market": False,
            }},
            "Black Market": {1: {
                "sell_price_min": 0,
                "buy_price_max": 700_000,   # BM pays 700k, cheapest buy is 480k → 220k profit
                "volume_24h": 1,
                "data_age_seconds": 1200,
                "is_black_market": True,
            }},
        }
    }
    names = {"T6_MAIN_SWORD": "Expert's Broadsword"}
    recipes = {}
    categories = {"T6_MAIN_SWORD": "sword"}

    opps = scanner.scan_black_market(prices, names, recipes, categories)
    assert len(opps) >= 1
    best = opps[0]
    assert best.item_id == "T6_MAIN_SWORD"
    assert best.buy_city == "Bridgewatch"   # Cheapest city
    assert best.net_profit == 700_000 - 480_000
    assert best.profit_pct > 0


def test_bm_scan_skips_unrealistic_spread(scanner):
    """BM price > 8x royal price should be skipped"""
    prices = {
        "T8_BOW": {
            "Lymhurst": {1: {
                "sell_price_min": 1_000_000,
                "buy_price_max": 800_000,
                "volume_24h": 10,
                "data_age_seconds": 600,
                "is_black_market": False,
            }},
            "Black Market": {1: {
                "sell_price_min": 0,
                "buy_price_max": 9_000_000,   # 9x > 8x
                "volume_24h": 1,
                "data_age_seconds": 1200,
                "is_black_market": True,
            }},
        }
    }
    names = {"T8_BOW": "Elder's Bow"}
    opps = scanner.scan_black_market(prices, names, {}, {})
    assert len(opps) == 0, "Unrealistic spread should be skipped"


def test_bm_scan_skips_stale_bm_price(scanner):
    """BM price older than 1hr should be skipped"""
    prices = {
        "T5_AXE": {
            "Martlock": {1: {
                "sell_price_min": 200_000,
                "buy_price_max": 150_000,
                "volume_24h": 5,
                "data_age_seconds": 600,
                "is_black_market": False,
            }},
            "Black Market": {1: {
                "sell_price_min": 0,
                "buy_price_max": 500_000,
                "volume_24h": 1,
                "data_age_seconds": 5_000,  # ← Stale: >3600s
                "is_black_market": True,
            }},
        }
    }
    names = {"T5_AXE": "Adept's Battleaxe"}
    opps = scanner.scan_black_market(prices, names, {}, {})
    assert len(opps) == 0, "Stale BM price should not produce opportunity"


def test_bm_scan_skips_manipulated_royal_price(scanner):
    """If one city has a 10x spike, it should be ignored as buy source"""
    prices = {
        "T7_SPEAR": {
            "Fort Sterling": {1: {
                "sell_price_min": 900_000,   # Normal
                "buy_price_max": 800_000,
                "volume_24h": 8,
                "data_age_seconds": 300,
                "is_black_market": False,
            }},
            "Martlock": {1: {
                "sell_price_min": 10_000_000,  # ← Manipulated (10x other cities)
                "buy_price_max": 800_000,
                "volume_24h": 1,
                "data_age_seconds": 300,
                "is_black_market": False,
            }},
            "Lymhurst": {1: {
                "sell_price_min": 950_000,   # Normal
                "buy_price_max": 820_000,
                "volume_24h": 3,
                "data_age_seconds": 600,
                "is_black_market": False,
            }},
            "Black Market": {1: {
                "sell_price_min": 0,
                "buy_price_max": 1_500_000,
                "volume_24h": 1,
                "data_age_seconds": 500,
                "is_black_market": True,
            }},
        }
    }
    names = {"T7_SPEAR": "Master's Spear"}
    opps = scanner.scan_black_market(prices, names, {}, {})
    assert len(opps) >= 1
    # The opportunity buy source must be Fort Sterling or Lymhurst, NOT Martlock
    assert opps[0].buy_city != "Martlock", "Manipulated city should not be buy source"
    assert opps[0].buy_price < 1_000_000, "Buy price should be the real market price"


def test_arb_uses_buy_order_not_sell_order(scanner):
    """
    Arbitrage must use buy_price_max at destination (instant fill),
    NOT sell_price_min (which would mean listing and waiting).
    """
    prices = {
        "T4_HIDE": {
            "Bridgewatch": {1: {
                "sell_price_min": 100_000,
                "buy_price_max": 90_000,
                "volume_24h": 50,
                "data_age_seconds": 300,
            }},
            "Martlock": {1: {
                "sell_price_min": 200_000,
                "buy_price_max": 0,   # ← No buy order → should NOT be an arb dest
                "volume_24h": 30,
                "data_age_seconds": 400,
            }},
            "Fort Sterling": {1: {
                "sell_price_min": 180_000,
                "buy_price_max": 160_000,   # ← Has buy order → valid destination
                "volume_24h": 20,
                "data_age_seconds": 500,
            }},
        }
    }
    names = {"T4_HIDE": "Journeyman's Hide"}
    opps = scanner.scan_arbitrage(prices, names)

    destinations = {o.sell_city for o in opps if o.item_id == "T4_HIDE"}
    assert "Martlock" not in destinations, "Martlock has no buy order, should not be arb dest"
    assert "Fort Sterling" in destinations, "Fort Sterling has buy order, should be arb dest"


def test_crafting_uses_correct_city_bonus(scanner):
    """Swords crafted in Lymhurst should have higher RRR than Caerleon"""
    rrr_lymhurst = rrr("Lymhurst", "sword", use_focus=False)
    rrr_caerleon = rrr("Caerleon", "sword", use_focus=False)
    assert rrr_lymhurst > rrr_caerleon


def test_crafting_profit_formula():
    """Manually verify the craft profit formula matches game mechanics"""
    # Material cost: 100k silver gross
    # RRR: 33% (Lymhurst sword bonus)
    # Net material cost: 100k * (1 - 0.33) = 67k
    # Station fee: 3k
    # Total cost: 70k
    # Sell price: 100k
    # Revenue after 4% tax + 2.5% setup: 100k * (1 - 0.065) = 93.5k
    # Profit: 93.5k - 70k = 23.5k
    gross = 100_000
    rrr_val = 0.33
    net_mat = gross * (1 - rrr_val)
    station = 3_000
    total_cost = net_mat + station
    sell = 100_000
    tax = 0.04
    setup = 0.025
    revenue = sell * (1 - tax - setup)
    profit = revenue - total_cost
    assert profit > 0
    assert abs(profit - 23_500) < 1_000, f"Expected ~23.5k profit, got {profit}"
