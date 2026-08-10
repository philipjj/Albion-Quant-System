"""
Tests for the redesigned OpportunityEngine.
Run: pytest tests/test_opportunity_engine.py -v
"""

import pytest
from app.core.opportunity_engine import (
    ROYAL_CITIES,
    OpportunityScanner,
    cross_city_outlier_check,
    is_bm_price_valid,
    is_price_valid,
    rrr,
)

# ─── RRR Tests ────────────────────────────────────────────────────────────────


from app.core.constants import calculate_rrr, calculate_station_fee


def test_rrr_formula_exact_math():
    """Verify RRR = LPB / (1 + LPB) for 18%, 33%, 58%, and focus bonuses"""
    assert calculate_rrr(0.18) == 0.15254
    assert calculate_rrr(0.33) == 0.24812
    assert calculate_rrr(0.58) == 0.36709
    assert calculate_rrr(1.18) == 0.54128


def test_brecilien_potion_crafting_bonus():
    """Brecilien gives +15% crafting bonus to potions, bags, capes"""
    rate_potion_brecilien = rrr("Brecilien", "potion", use_focus=False)
    rate_potion_royal = rrr("Bridgewatch", "potion", use_focus=False)
    assert rate_potion_brecilien > rate_potion_royal
    assert abs(rate_potion_brecilien - 0.2481) < 0.005


def test_station_fee_calculation():
    """Verify Nutrition = Item Value * 0.1125, Fee = (Nutrition * Tax) / 100"""
    # Item Value = 1000, Tax = 500 Silver per 100 Nutrition
    fee = calculate_station_fee(1000.0, 500.0)
    assert fee == 562.5, f"Expected 562.5, got {fee}"


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
    assert is_price_valid(50, 40) is False  # Below MIN_PRICE


def test_price_invalid_too_high():
    assert is_price_valid(600_000_000, 500_000) is False  # Above 500M cap


def test_price_invalid_manipulation_ratio():
    # sell_min is 10x buy_max → likely a single troll listing
    assert is_price_valid(1_000_000, 100_000) is False  # ratio = 10x > 8x limit


def test_price_valid_normal_spread():
    # 5x spread is on the edge but acceptable for rare items
    assert is_price_valid(400_000, 100_000) is True  # 4x


def test_price_invalid_tier_min():
    """T6-T8 items listed for 100-200 silver should be rejected as corrupt data"""
    assert is_price_valid(193, 0, item_id="T8_2H_DUALSWORD@1") is False  # T8 min is 35k
    assert is_price_valid(130, 0, item_id="T7_MAIN_NATURESTAFF_KEEPER@2") is False  # T7 min is 12k
    assert is_price_valid(233, 0, item_id="T6_2H_INFERNOSTAFF@1") is False  # T6 min is 4k
    assert is_price_valid(25000, 0, item_id="T4_HEAD_CLOTH_SET2@2") is True  # 25.5k for T4 is valid


def test_bm_price_valid_with_item_value():
    """BM price should be rejected if it exceeds 5000x item value"""
    assert is_bm_price_valid(10_000_000, 1_000) is False  # 10000x
    assert is_bm_price_valid(4_000_000, 1_000) is True  # 4000x


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
        min_bm_profit=1_000,  # Low thresholds for testing
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
            "Lymhurst": {
                1: {
                    "sell_price_min": 500_000,
                    "buy_price_max": 400_000,
                    "volume_24h": 10,
                    "data_age_seconds": 600,
                    "is_black_market": False,
                }
            },
            "Bridgewatch": {
                1: {
                    "sell_price_min": 480_000,
                    "buy_price_max": 390_000,
                    "volume_24h": 5,
                    "data_age_seconds": 900,
                    "is_black_market": False,
                }
            },
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 900_000,  # BM pays 900k, cheapest buy is 480k -> very profitable
                    "volume_24h": 1,
                    "data_age_seconds": 500,
                    "is_black_market": True,
                }
            },
        }
    }
    names = {"T6_MAIN_SWORD": "Expert's Broadsword"}
    recipes = {}
    categories = {"T6_MAIN_SWORD": "sword"}

    opps = scanner.scan_black_market(prices, names, recipes, categories)
    assert len(opps) >= 1
    best = opps[0]
    assert best.item_id == "T6_MAIN_SWORD"
    assert best.buy_city == "Bridgewatch"  # Cheapest city
    assert best.net_profit > 300_000
    assert best.profit_pct > 0


def test_bm_scan_skips_unrealistic_spread(scanner):
    """BM price > 8x royal price should be skipped"""
    prices = {
        "T8_BOW": {
            "Lymhurst": {
                1: {
                    "sell_price_min": 1_000_000,
                    "buy_price_max": 800_000,
                    "volume_24h": 10,
                    "data_age_seconds": 600,
                    "is_black_market": False,
                }
            },
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 9_000_000,  # 9x > 8x
                    "volume_24h": 1,
                    "data_age_seconds": 1200,
                    "is_black_market": True,
                }
            },
        }
    }
    names = {"T8_BOW": "Elder's Bow"}
    opps = scanner.scan_black_market(prices, names, {}, {})
    assert len(opps) == 0, "Unrealistic spread should be skipped"


def test_bm_scan_skips_stale_bm_price(scanner):
    """BM price older than 1hr should be skipped"""
    prices = {
        "T5_AXE": {
            "Martlock": {
                1: {
                    "sell_price_min": 200_000,
                    "buy_price_max": 150_000,
                    "volume_24h": 5,
                    "data_age_seconds": 600,
                    "is_black_market": False,
                }
            },
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 500_000,
                    "volume_24h": 1,
                    "data_age_seconds": 5_000,  # ← Stale: >3600s
                    "is_black_market": True,
                }
            },
        }
    }
    names = {"T5_AXE": "Adept's Battleaxe"}
    opps = scanner.scan_black_market(prices, names, {}, {})
    assert len(opps) == 0, "Stale BM price should not produce opportunity"


def test_bm_scan_skips_manipulated_royal_price(scanner):
    """If one city has a 10x spike, it should be ignored as buy source"""
    prices = {
        "T7_SPEAR": {
            "Fort Sterling": {
                1: {
                    "sell_price_min": 900_000,  # Normal
                    "buy_price_max": 800_000,
                    "volume_24h": 8,
                    "data_age_seconds": 300,
                    "is_black_market": False,
                }
            },
            "Martlock": {
                1: {
                    "sell_price_min": 10_000_000,  # ← Manipulated (10x other cities)
                    "buy_price_max": 800_000,
                    "volume_24h": 1,
                    "data_age_seconds": 300,
                    "is_black_market": False,
                }
            },
            "Lymhurst": {
                1: {
                    "sell_price_min": 950_000,  # Normal
                    "buy_price_max": 820_000,
                    "volume_24h": 3,
                    "data_age_seconds": 600,
                    "is_black_market": False,
                }
            },
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 1_600_000,
                    "volume_24h": 1,
                    "data_age_seconds": 500,
                    "is_black_market": True,
                }
            },
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
            "Bridgewatch": {
                1: {
                    "sell_price_min": 100_000,
                    "buy_price_max": 90_000,
                    "volume_24h": 50,
                    "data_age_seconds": 300,
                }
            },
            "Martlock": {
                1: {
                    "sell_price_min": 200_000,
                    "buy_price_max": 0,  # ← No buy order → should NOT be an arb dest
                    "volume_24h": 30,
                    "data_age_seconds": 400,
                }
            },
            "Fort Sterling": {
                1: {
                    "sell_price_min": 180_000,
                    "buy_price_max": 160_000,  # ← Has buy order → valid destination
                    "volume_24h": 20,
                    "data_age_seconds": 500,
                }
            },
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

def test_scan_market_making(scanner):
    scanner.min_mm_profit = 1000
    prices = {
        'T4_BAG': {
            'Martlock': {
                1: {
                    'sell_price_min': 5000,
                    'buy_price_max': 2000,
                    'volume_24h': 100,
                    'data_age_seconds': 100,
                }
            },
            'Bridgewatch': {
                1: {
                    'sell_price_min': 4500,
                    'buy_price_max': 3000,
                    'volume_24h': 200,
                    'data_age_seconds': 100,
                }
            }
        }
    }
    names = {'T4_BAG': 'Adept bag'}
    categories = {'T4_BAG': 'bag'}
    
    # We lowered requirement to 10 in the code, and these have 100 and 200 volume.
    opps = scanner.scan_market_making(prices, names, categories)
    
    # We should have multiple combinations. 
    # Martlock -> Bridgewatch
    # Buy at Martlock buy_price_max + 1 = 2001
    # Sell at Bridgewatch sell_price_min - 1 = 4499
    
    mb_opp = next((o for o in opps if o.source_city == 'Martlock' and o.destination_city == 'Bridgewatch'), None)
    assert mb_opp is not None
    assert mb_opp.buy_price == 2001
    assert mb_opp.sell_price == 4499
    
    # Check gross profit
    assert mb_opp.gross_profit == 4499 - 2001
    
    # Check fees: 
    # setup fee: 2001 * 0.025 = 50.025
    # setup fee sell: 4499 * 0.025 = 112.475
    # tax paid: 4499 * 0.04 = 179.96
    
    total_fees = 2001 * 0.025 + 4499 * 0.025 + 4499 * 0.04
    net = mb_opp.gross_profit - total_fees
    assert abs(mb_opp.net_profit - round(net, 0)) <= 1


# ─── Enchantment Material Quantity Tests ─────────────────────────────────────


def test_get_enchant_qty_categories():
    """Verify correct enchantment material quantities per level across item types"""
    # 1H Mainhand Weapons -> 288
    assert OpportunityScanner._get_enchant_qty("T7_MAIN_SWORD") == 288
    assert OpportunityScanner._get_enchant_qty("T7_MAIN_FIRESTAFF") == 288
    assert OpportunityScanner._get_enchant_qty("T7_MAIN_1HCROSSBOW") == 288

    # 2H Weapons & Dual Weapons -> 384
    assert OpportunityScanner._get_enchant_qty("T7_2H_CLAYMORE") == 384
    assert OpportunityScanner._get_enchant_qty("T7_2H_BOW") == 384
    assert OpportunityScanner._get_enchant_qty("T7_2H_FIRESTAFF") == 384
    assert OpportunityScanner._get_enchant_qty("T7_2H_KNUCKLES_SET1") == 384

    # Chest Armors -> 192
    assert OpportunityScanner._get_enchant_qty("T7_ARMOR_PLATE_SET1") == 192
    assert OpportunityScanner._get_enchant_qty("T7_ARMOR_LEATHER_SET1") == 192
    assert OpportunityScanner._get_enchant_qty("T7_ARMOR_CLOTH_SET1") == 192

    # Headgear & Footwear -> 96
    assert OpportunityScanner._get_enchant_qty("T7_HEAD_PLATE_SET1") == 96
    assert OpportunityScanner._get_enchant_qty("T7_SHOES_PLATE_SET1") == 96

    # Chest Armors -> 192
    assert OpportunityScanner._get_enchant_qty("T7_ARMOR_PLATE_SET1") == 192
    assert OpportunityScanner._get_enchant_qty("T7_ARMOR_LEATHER_SET1") == 192
    assert OpportunityScanner._get_enchant_qty("T7_ARMOR_CLOTH_SET1") == 192

    # Headgear, Footwear, Off-hands, Capes, Backpacks -> 96
    assert OpportunityScanner._get_enchant_qty("T7_HEAD_PLATE_SET1") == 96
    assert OpportunityScanner._get_enchant_qty("T7_SHOES_PLATE_SET1") == 96
    assert OpportunityScanner._get_enchant_qty("T7_OFF_SHIELD") == 96
    assert OpportunityScanner._get_enchant_qty("T7_CAPE") == 96
    assert OpportunityScanner._get_enchant_qty("T7_BACKPACK_GATHERER_FIBER") == 96


def test_scan_enchanting_satchel_of_insight_accurate_math(scanner):
    """
    User scenario:
    - Base T7 Satchel @2 sell_price_min in Caerleon = 845,000
    - T7 Relic sell_price_min in Caerleon = 9,000
    - BM Buy order for T7 Satchel @3 = 2,430,000
    - True enchantment requirement: 384 T7 Relics
    - True total cost: 845,000 + (384 * 9,000) = 4,301,000 silver
    - Resulting trade is a LOSS (-1,871,000 silver) -> Scanner MUST reject it!
    """
    prices = {
        "T7_BAG_INSIGHT@2": {
            "Caerleon": {
                1: {
                    "sell_price_min": 845_000,
                    "buy_price_max": 700_000,
                    "volume_24h": 10,
                    "data_age_seconds": 300,
                }
            }
        },
        "T7_RELIC": {
            "Caerleon": {
                1: {
                    "sell_price_min": 9_000,
                    "buy_price_max": 8_500,
                    "volume_24h": 500,
                    "data_age_seconds": 300,
                }
            }
        },
        "T7_BAG_INSIGHT@3": {
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 2_430_000,
                    "volume_24h": 5,
                    "data_age_seconds": 60,
                }
            }
        },
    }
    names = {
        "T7_BAG_INSIGHT@3": "Grandmaster's Satchel of Insight .3",
        "T7_BAG_INSIGHT@2": "Grandmaster's Satchel of Insight .2",
        "T7_RELIC": "Grandmaster's Relic",
    }
    categories = {"T7_BAG_INSIGHT@3": "satchels"}

    # Run scan
    opps = scanner.scan_enchanting(prices, names, categories)

    # Must find ZERO opportunities because 4.301M cost > 2.43M BM buy price (loss of ~1.87M silver)
    assert len(opps) == 0, "Satchel of Insight trade has negative profit and must be rejected"


def test_scan_enchanting_level_4_rejected(scanner):
    """Verify level .4 enchantment is rejected because Artifact Foundry only supports up to .3"""
    prices = {
        "T7_2H_BOW@3": {
            "Caerleon": {
                1: {
                    "sell_price_min": 2_000_000,
                    "buy_price_max": 1_800_000,
                    "volume_24h": 5,
                    "data_age_seconds": 300,
                }
            }
        },
        "T7_2H_BOW@4": {
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 6_000_000,
                    "volume_24h": 2,
                    "data_age_seconds": 60,
                }
            }
        },
    }
    names = {
        "T7_2H_BOW@4": "Grandmaster's Warbow .4",
        "T7_2H_BOW@3": "Grandmaster's Warbow .3",
    }
    categories = {"T7_2H_BOW@4": "bows"}

    opps = scanner.scan_enchanting(prices, names, categories)
    assert len(opps) == 0, "Level .4 items cannot be enchanted at Artifact Foundry and must be rejected"


def test_non_enchantable_items_are_skipped():
    """Verify that off-hands, bags, satchels, capes, royal items, and level .4 are rejected by enchanting scanner."""
    scanner = OpportunityScanner()
    # Level .4 items -> Cannot be enchanted at Artifact Foundry
    assert scanner._get_enchant_requirements("T5_ARMOR_LEATHER_MORGANA@4") is None
    assert scanner._get_enchant_requirements("T7_2H_BOW@4") is None

    # Taproot / Offhand -> Cannot be enchanted at Artifact Foundry
    assert scanner._get_enchant_requirements("T5_OFF_TOTEM_KEEPER@3") is None
    assert scanner._get_enchant_requirements("T4_OFF_SHIELD@1") is None

    # Royal items -> Cannot be enchanted at Artifact Foundry
    assert scanner._get_enchant_requirements("T5_ARMOR_LEATHER_ROYAL@2") is None

    # Bags & Satchels -> Cannot be enchanted at Artifact Foundry
    assert scanner._get_enchant_requirements("T7_BAG_INSIGHT@3") is None
    assert scanner._get_enchant_requirements("T5_BAG@2") is None

    # Capes -> Cannot be enchanted at Artifact Foundry
    assert scanner._get_enchant_requirements("T6_CAPEITEM_FW_BRIDGEWATCH@3") is None

    # Valid weapon & armor (.1, .2, .3) -> Can be enchanted at Artifact Foundry
    assert scanner._get_enchant_requirements("T6_ARMOR_PLATE_SET1@2") is not None
    assert scanner._get_enchant_requirements("T7_2H_BOW@3") is not None


def test_scan_enchanting_rejects_corrupted_material_price(scanner):
    """Verify 1-silver or 0-silver material prices in Caerleon are rejected by is_price_valid."""
    prices = {
        "T8_MAIN_FROSTSTAFF": {
            "Caerleon": {
                1: {
                    "sell_price_min": 1_700_000,
                    "buy_price_max": 1_500_000,
                    "volume_24h": 10,
                    "data_age_seconds": 300,
                }
            }
        },
        "T8_SOUL": {
            "Caerleon": {
                1: {
                    "sell_price_min": 1,  # Corrupted 1-silver listing
                    "buy_price_max": 0,
                    "volume_24h": 500,
                    "data_age_seconds": 300,
                }
            }
        },
        "T8_MAIN_FROSTSTAFF@1": {
            "Black Market": {
                1: {
                    "sell_price_min": 0,
                    "buy_price_max": 2_790_000,
                    "volume_24h": 5,
                    "data_age_seconds": 60,
                }
            }
        },
    }
    names = {
        "T8_MAIN_FROSTSTAFF@1": "Elder's Frost Staff .1",
        "T8_MAIN_FROSTSTAFF": "Elder's Frost Staff",
        "T8_SOUL": "Elder's Soul",
    }
    categories = {"T8_MAIN_FROSTSTAFF@1": "staffs"}

    opps = scanner.scan_enchanting(prices, names, categories)
    assert len(opps) == 0, "Corrupted 1-silver material price must be rejected"




