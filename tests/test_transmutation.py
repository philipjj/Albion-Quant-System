"""
Test Suite: Transmutation Engine & Financial Math
Verifies raw and refined material transmutation, volume filtering,
official silver fees, mathematical margin bounds, and Discord alert formatting.
"""

import pytest
from app.core.opportunity_engine import (
    OpportunityScanner,
    parse_transmutable_resource,
    make_resource_id,
)
from app.alerts.discord import DiscordAlerter, _get_true_margin


def test_parse_transmutable_resource():
    """Verify parsing of canonical raw and refined resource IDs."""
    # Raw materials
    assert parse_transmutable_resource("T4_WOOD") == (4, "WOOD", 0, True)
    assert parse_transmutable_resource("T5_WOOD_LEVEL1@1") == (5, "WOOD", 1, True)
    assert parse_transmutable_resource("T6_ORE_LEVEL2@2") == (6, "ORE", 2, True)
    assert parse_transmutable_resource("T7_HIDE_LEVEL3@3") == (7, "HIDE", 3, True)
    assert parse_transmutable_resource("T8_FIBER_LEVEL4@4") == (8, "FIBER", 4, True)
    assert parse_transmutable_resource("T4_ROCK") == (4, "ROCK", 0, True)

    # Rock has no enchantments
    assert parse_transmutable_resource("T4_ROCK_LEVEL1@1") is None

    # Refined materials
    assert parse_transmutable_resource("T4_PLANKS") == (4, "PLANKS", 0, False)
    assert parse_transmutable_resource("T5_METALBAR_LEVEL1@1") == (5, "METALBAR", 1, False)
    assert parse_transmutable_resource("T6_LEATHER_LEVEL2@2") == (6, "LEATHER", 2, False)
    assert parse_transmutable_resource("T7_CLOTH_LEVEL3@3") == (7, "CLOTH", 3, False)
    assert parse_transmutable_resource("T8_CLOTH") == (8, "CLOTH", 0, False)
    assert parse_transmutable_resource("T5_STONEBLOCK") == (5, "STONEBLOCK", 0, False)

    # Stone blocks have no enchantments
    assert parse_transmutable_resource("T5_STONEBLOCK_LEVEL1@1") is None

    # Ineligible non-resources
    assert parse_transmutable_resource("QUESTITEM_TOKEN_ROYAL_T4") is None
    assert parse_transmutable_resource("QUESTITEM_TOKEN_ROYAL_T5") is None
    assert parse_transmutable_resource("T4_ARMOR_CLOTH") is None
    assert parse_transmutable_resource("T6_MAIN_SWORD") is None
    assert parse_transmutable_resource("T4_BAG") is None
    assert parse_transmutable_resource("T5_POTION_HEAL") is None


def test_make_resource_id():
    """Verify canonical item ID generator."""
    assert make_resource_id(4, "WOOD", 0) == "T4_WOOD"
    assert make_resource_id(5, "WOOD", 1) == "T5_WOOD_LEVEL1@1"
    assert make_resource_id(6, "PLANKS", 2) == "T6_PLANKS_LEVEL2@2"
    assert make_resource_id(8, "LEATHER", 4) == "T8_LEATHER_LEVEL4@4"


def test_scan_transmutation_raw_wood_tier():
    """Test raw wood tier transmutation T4 -> T5."""
    scanner = OpportunityScanner(premium=False)
    scanner.allow_zero_volume = False

    # T4 Pine Logs -> T5 Cedar Logs in Lymhurst
    # T4 price = 100, T5 fee = 781, total cost = 881
    # T5 sell price = 1,500. Net rev (non-prem 8% tax + 2.5% setup) = 1500 * 0.895 = 1342.5
    # Net profit = 1342.5 - 881 = +461.5 -> 461
    # Margin = 461.5 / 1500 = 30.77%
    # ROI = 461.5 / 881 = 52.38%
    prices = {
        "T5_WOOD": {
            "Lymhurst": {
                1: {"sell_price_min": 1500, "buy_price_max": 1200, "volume_24h": 500, "data_age_seconds": 100}
            }
        },
        "T4_WOOD": {
            "Lymhurst": {
                1: {"sell_price_min": 100, "buy_price_max": 80, "volume_24h": 1000, "data_age_seconds": 100}
            }
        },
    }
    names = {"T4_WOOD": "Pine Logs", "T5_WOOD": "Cedar Logs"}

    opps = scanner.scan_transmutation(prices, names)
    assert len(opps) == 1
    o = opps[0]
    assert o.item_id == "T5_WOOD"
    assert o.source_item_id == "T4_WOOD"
    assert o.transmutation_fee == 781
    assert o.total_cost == 881
    assert o.sell_price == 1500
    assert o.net_profit == 461
    assert o.profit_pct < 100.0  # Profit margin strictly < 100%
    assert abs(o.profit_pct - 30.77) < 0.1
    assert abs(o.roi - 52.38) < 0.1


def test_scan_transmutation_refined_leather_enchant():
    """Test refined leather enchantment transmutation T5.0 -> T5.1."""
    scanner = OpportunityScanner(premium=False)
    scanner.allow_zero_volume = False

    # T5 Hardened Leather -> T5.1 Hardened Leather (.1) in Martlock
    # T5.0 price = 1,200, T5.1 fee = 2,000, total cost = 3,200
    # T5.1 sell price = 4,500. Net rev (non-prem 8% tax + 2.5% setup) = 4500 * 0.895 = 4027.5
    # Net profit = 4027.5 - 3200 = +827.5 -> 827
    # Margin = 827.5 / 4500 = 18.39%
    # ROI = 827.5 / 3200 = 25.86%
    prices = {
        "T5_LEATHER_LEVEL1@1": {
            "Martlock": {
                1: {"sell_price_min": 4500, "buy_price_max": 3800, "volume_24h": 300, "data_age_seconds": 60}
            }
        },
        "T5_LEATHER": {
            "Martlock": {
                1: {"sell_price_min": 1200, "buy_price_max": 1000, "volume_24h": 800, "data_age_seconds": 60}
            }
        },
    }
    names = {"T5_LEATHER": "Hardened Leather", "T5_LEATHER_LEVEL1@1": "Hardened Leather .1"}

    opps = scanner.scan_transmutation(prices, names)
    assert len(opps) == 1
    o = opps[0]
    assert o.item_id == "T5_LEATHER_LEVEL1@1"
    assert o.source_item_id == "T5_LEATHER"
    assert o.transmutation_fee == 2000
    assert o.total_cost == 3200
    assert o.sell_price == 4500
    assert o.net_profit == 827
    assert o.profit_pct < 100.0
    assert abs(o.profit_pct - 18.39) < 0.1
    assert abs(o.roi - 25.86) < 0.1


def test_scan_transmutation_zero_volume_rejected():
    """Verify 0-volume and illiquid listings are strictly rejected."""
    scanner = OpportunityScanner()
    scanner.allow_zero_volume = False

    prices = {
        "T8_CLOTH": {
            "Lymhurst": {
                1: {"sell_price_min": 27000, "buy_price_max": 6000, "volume_24h": 0, "data_age_seconds": 100}
            }
        },
        "T7_CLOTH": {
            "Lymhurst": {
                1: {"sell_price_min": 9500, "buy_price_max": 8000, "volume_24h": 500, "data_age_seconds": 100}
            }
        },
    }
    names = {"T7_CLOTH": "Opulent Cloth", "T8_CLOTH": "Baroque Cloth"}

    opps = scanner.scan_transmutation(prices, names)
    assert len(opps) == 0, "0 volume transmutation listings must be rejected"


def test_scan_transmutation_royal_sigil_rejected():
    """Verify Royal Sigils cannot be transmuted."""
    scanner = OpportunityScanner()
    scanner.allow_zero_volume = False

    prices = {
        "QUESTITEM_TOKEN_ROYAL_T5": {
            "Lymhurst": {
                1: {"sell_price_min": 39000, "buy_price_max": 30000, "volume_24h": 100, "data_age_seconds": 100}
            }
        },
        "QUESTITEM_TOKEN_ROYAL_T4": {
            "Lymhurst": {
                1: {"sell_price_min": 4, "buy_price_max": 2, "volume_24h": 100, "data_age_seconds": 100}
            }
        },
    }
    names = {
        "QUESTITEM_TOKEN_ROYAL_T4": "Expert's Royal Sigil",
        "QUESTITEM_TOKEN_ROYAL_T5": "Master's Royal Sigil",
    }

    opps = scanner.scan_transmutation(prices, names)
    assert len(opps) == 0, "Royal Sigils must never be considered transmutable"


def test_discord_transmutation_embed_formatting():
    """Verify Discord embed formatting displays accurate margin and batch metrics."""
    opp_dict = {
        "item_id": "T5_WOOD",
        "item_name": "Cedar Logs",
        "source_item_id": "T4_WOOD",
        "source_item_name": "Pine Logs",
        "source_price": 100,
        "transmutation_fee": 781,
        "total_cost": 881,
        "sell_price": 1500,
        "destination_city": "Lymhurst",
        "source_city": "Lymhurst",
        "profit": 469,
        "estimated_profit": 469,
        "profit_pct": 31.27,
        "profit_margin": 31.27,
        "roi": 53.23,
        "safe_limit": 50,
        "daily_volume": 500,
        "data_age_sell": 120,
        "ev_score": 4690,
        "is_premium": False,
        "tax_rate": 0.08,
    }

    alerter = DiscordAlerter()
    embed = alerter._format_transmutation_embed(opp_dict)

    assert "Transmute: Cedar Logs" in embed["title"]
    margin_field = [f for f in embed["fields"] if f["name"] == "📊 Yield & ROI"][0]
    assert "Margin: **31.3%**" in margin_field["value"]
    assert "ROI: **53.2%**" in margin_field["value"]

    math_field = [f for f in embed["fields"] if f["name"] == "🔮 Transmutation Financial Math"][0]
    assert "Base Material Price: **100**" in math_field["value"]
    assert "Transmutation Silver Fee: **781**" in math_field["value"]
    assert "Total Cost: **881**" in math_field["value"]
    assert "Net Profit / Unit: **+469**" in math_field["value"]
    assert "Total Batch Profit (50x): **+23.4k**" in math_field["value"]
