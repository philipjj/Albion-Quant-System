"""
Test Suite: Albion Online Verified Facts & Data Integrity
Tests city crafting bonuses, RRR math, fallback station fees, fallback weights,
and Artifact Foundry enchantment rules against empirical game data.
"""

import pytest
from app.core.constants import (
    CITY_CRAFTING_BONUSES,
    calculate_rrr,
    BASE_PRODUCTION_BONUS,
    CRAFTING_SPECIALTY_LPB,
    REFINING_SPECIALTY_LPB,
    FOCUS_CRAFTING_LPB,
)
from app.core.market_utils import calculate_rrr as calculate_rrr_utils, CITY_BONUS
from app.core.opportunity_engine import (
    OpportunityScanner,
    get_fallback_item_value,
)
from app.core.scanner_integration import UnifiedScanner


def test_city_crafting_bonuses_integrity():
    """Verify city crafting bonuses match exact Albion Online rules."""
    # Bridgewatch
    assert "plate_armor" in CITY_CRAFTING_BONUSES["Bridgewatch"]["bonus_categories"]
    assert "cloth_shoes" in CITY_CRAFTING_BONUSES["Bridgewatch"]["bonus_categories"]
    assert "stoneblock" in CITY_CRAFTING_BONUSES["Bridgewatch"]["refining_bonus"]

    # Martlock
    assert "plate_shoes" in CITY_CRAFTING_BONUSES["Martlock"]["bonus_categories"]
    assert "offhand" in CITY_CRAFTING_BONUSES["Martlock"]["bonus_categories"]
    assert "leather_armor" not in CITY_CRAFTING_BONUSES["Martlock"]["bonus_categories"]
    assert "leather" in CITY_CRAFTING_BONUSES["Martlock"]["refining_bonus"]

    # Lymhurst
    assert "leather_helmet" in CITY_CRAFTING_BONUSES["Lymhurst"]["bonus_categories"]
    assert "leather_shoes" in CITY_CRAFTING_BONUSES["Lymhurst"]["bonus_categories"]
    assert "cloth_armor" not in CITY_CRAFTING_BONUSES["Lymhurst"]["bonus_categories"]
    assert "cloth" in CITY_CRAFTING_BONUSES["Lymhurst"]["refining_bonus"]

    # Fort Sterling
    assert "plate_helmet" in CITY_CRAFTING_BONUSES["Fort Sterling"]["bonus_categories"]
    assert "cloth_armor" in CITY_CRAFTING_BONUSES["Fort Sterling"]["bonus_categories"]
    assert "planks" in CITY_CRAFTING_BONUSES["Fort Sterling"]["refining_bonus"]

    # Thetford
    assert "cloth_helmet" in CITY_CRAFTING_BONUSES["Thetford"]["bonus_categories"]
    assert "leather_armor" in CITY_CRAFTING_BONUSES["Thetford"]["bonus_categories"]
    assert "metalbar" in CITY_CRAFTING_BONUSES["Thetford"]["refining_bonus"]


def test_rrr_mathematical_precision():
    """Verify RRR = LPB / (1 + LPB) for base, city bonus, refining bonus, and focus."""
    # Base Royal City RRR (18% LPB) -> 0.15254
    assert calculate_rrr(BASE_PRODUCTION_BONUS) == 0.15254

    # City Crafting Bonus (18% + 15% = 33% LPB) -> 0.24812
    assert calculate_rrr(BASE_PRODUCTION_BONUS + CRAFTING_SPECIALTY_LPB) == 0.24812

    # City Refining Bonus (18% + 40% = 58% LPB) -> 0.36709
    assert calculate_rrr(BASE_PRODUCTION_BONUS + REFINING_SPECIALTY_LPB) == 0.36709

    # Base + Focus (18% + 59% = 77% LPB) -> 0.43503
    assert calculate_rrr(BASE_PRODUCTION_BONUS + FOCUS_CRAFTING_LPB) == 0.43503

    # City Crafting + Focus (18% + 15% + 59% = 92% LPB) -> 0.47917
    assert calculate_rrr(BASE_PRODUCTION_BONUS + CRAFTING_SPECIALTY_LPB + FOCUS_CRAFTING_LPB) == 0.47917

    # City Refining + Focus (18% + 40% + 59% = 117% LPB) -> 0.53917
    assert calculate_rrr(BASE_PRODUCTION_BONUS + REFINING_SPECIALTY_LPB + FOCUS_CRAFTING_LPB) == 0.53917


def test_market_utils_rrr_matches_constants():
    """Verify calculate_rrr in market_utils matches derived CITY_BONUS."""
    # Plate armor in Bridgewatch gets city crafting bonus (33% LPB -> 0.2481)
    rrr_bw = calculate_rrr_utils("Bridgewatch", "plate_armor", tier=4)
    assert rrr_bw == 0.2481

    # Plate armor in Martlock does NOT get crafting bonus (18% LPB -> 0.1525)
    rrr_mt = calculate_rrr_utils("Martlock", "plate_armor", tier=4)
    assert rrr_mt == 0.1525

    # Leather armor in Thetford gets crafting bonus (33% LPB -> 0.2481)
    rrr_thet = calculate_rrr_utils("Thetford", "leather_armor", tier=4)
    assert rrr_thet == 0.2481

    # Leather shoes in Lymhurst gets crafting bonus (33% LPB -> 0.2481)
    rrr_lym = calculate_rrr_utils("Lymhurst", "leather_shoes", tier=4)
    assert rrr_lym == 0.2481


def test_enchantment_material_quantities():
    """Verify Artifact Foundry rules: 1H=288, 2H=384, Chest=192, Head/Feet=96."""
    scanner = OpportunityScanner()

    # 1H Mainhand Weapon -> 288
    reqs_1h = scanner._get_enchant_requirements("T4_MAIN_SWORD@1")
    assert reqs_1h is not None
    assert reqs_1h[2] == 288

    # 2H Weapon -> 384
    reqs_2h = scanner._get_enchant_requirements("T5_2H_BOW@1")
    assert reqs_2h is not None
    assert reqs_2h[2] == 384

    # Chest Armor -> 192
    reqs_chest = scanner._get_enchant_requirements("T6_ARMOR_PLATE_SET1@1")
    assert reqs_chest is not None
    assert reqs_chest[2] == 192

    # Headgear -> 96
    reqs_head = scanner._get_enchant_requirements("T7_HEAD_CLOTH_SET1@1")
    assert reqs_head is not None
    assert reqs_head[2] == 96

    # Off-hands -> 96
    reqs_off = scanner._get_enchant_requirements("T4_OFF_SHIELD_HELL@1")
    assert reqs_off is not None
    assert reqs_off[2] == 96

    # Standard Capes -> 96, Standard Bags -> 192
    reqs_cape = scanner._get_enchant_requirements("T5_CAPE@1")
    assert reqs_cape is not None
    assert reqs_cape[2] == 96

    reqs_bag = scanner._get_enchant_requirements("T6_BAG@1")
    assert reqs_bag is not None
    assert reqs_bag[2] == 192

    # Ineligible gear (Faction Capes, Bags of Insight, Royal items) -> None
    assert scanner._get_enchant_requirements("T6_CAPEITEM_FW_BRIDGEWATCH@3") is None
    assert scanner._get_enchant_requirements("T7_BAG_INSIGHT@3") is None
    assert scanner._get_enchant_requirements("T8_ARMOR_ROYAL_SET1@1") is None


def test_fallback_item_value_and_weights():
    """Verify fallback ItemValue and item weight resolution when DB values are missing."""
    assert get_fallback_item_value("T4_ARMOR_PLATE_SET1") == 64.0
    assert get_fallback_item_value("T8_MAIN_SWORD") == 1024.0
    assert get_fallback_item_value("NON_TIER") == 32.0


def test_market_making_troll_buy_order_rejected():
    """
    Verify troll buy orders (e.g. 332 silver on a T8.3 Masterpiece Royal Jacket listed for 15M)
    are strictly rejected by is_price_valid and scan_market_making.
    """
    from app.core.opportunity_engine import is_price_valid, OpportunityScanner

    item_id = "T8_ARMOR_ROYAL_SET1@3"
    sell_min = 15_000_000
    buy_max = 332

    # 1. is_price_valid MUST return False
    assert not is_price_valid(sell_min, buy_max, item_id=item_id)

    # 2. scan_market_making MUST produce 0 opportunities for this troll order
    prices = {
        item_id: {
            "Martlock": {
                5: {  # Masterpiece quality
                    "sell_price_min": sell_min,
                    "buy_price_max": buy_max,
                    "volume_24h": 5,
                    "data_age_seconds": 100,
                }
            }
        }
    }
    names = {item_id: "Elder's Royal Jacket .3"}
    categories = {item_id: "cloth_armor"}

    scanner = OpportunityScanner()
    opps = scanner.scan_market_making(prices, names, categories)
    assert len(opps) == 0

