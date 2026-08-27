import pytest
from app.core.constants import CITY_ISLAND_FARMING_BONUSES
from app.core.market_utils import (
    get_island_farming_bonus,
    get_item_crafting_subcategory,
    calculate_rrr,
)
from app.core.opportunity_engine import OpportunityScanner, CraftingOpportunity
from app.alerts.discord import DiscordAlerter


def test_island_biome_bonuses():
    """Verify official +10% island biome bonuses per city."""
    # Bridgewatch: Corn, Beans, Dragon Teasel, Goats, Horses
    assert get_island_farming_bonus("Bridgewatch", "T7_CORN") == 0.10
    assert get_island_farming_bonus("Bridgewatch", "T2_BEAN") == 0.10
    assert get_island_farming_bonus("Bridgewatch", "T5_TEASEL") == 0.10
    assert get_island_farming_bonus("Bridgewatch Island", "T4_MILK") == 0.10
    assert get_island_farming_bonus("Personal Island (Bridgewatch)", "T4_MEAT") == 0.10
    assert get_island_farming_bonus("Bridgewatch", "T4_TURNIP") == 0.0  # Turnip is Fort Sterling

    # Fort Sterling: Turnip, Ghoul Yarrow, Sheep, Chickens
    assert get_island_farming_bonus("Fort Sterling", "T4_TURNIP") == 0.10
    assert get_island_farming_bonus("Fort Sterling", "T7_YARROW") == 0.10
    assert get_island_farming_bonus("Fort Sterling", "T3_EGG") == 0.10
    assert get_island_farming_bonus("Fort Sterling", "T3_MEAT") == 0.10

    # Lymhurst: Carrots, Pumpkin, Burdock, Goose
    assert get_island_farming_bonus("Lymhurst", "T1_CARROT") == 0.10
    assert get_island_farming_bonus("Lymhurst", "T8_PUMPKIN") == 0.10
    assert get_island_farming_bonus("Lymhurst", "T4_BURDOCK") == 0.10
    assert get_island_farming_bonus("Lymhurst", "T5_EGG") == 0.10

    # Martlock: Wheat, Potato, Foxglove, Cow
    assert get_island_farming_bonus("Martlock", "T3_WHEAT") == 0.10
    assert get_island_farming_bonus("Martlock", "T6_POTATO") == 0.10
    assert get_island_farming_bonus("Martlock", "T6_FOXGLOVE") == 0.10
    assert get_island_farming_bonus("Martlock", "T8_MILK") == 0.10

    # Thetford: Cabbage, Agaric, Mullein, Pig
    assert get_island_farming_bonus("Thetford", "T5_CABBAGE") == 0.10
    assert get_island_farming_bonus("Thetford", "T2_AGARIC") == 0.10
    assert get_island_farming_bonus("Thetford", "T7_MEAT") == 0.10


def test_crafting_subcategories_and_city_bonuses():
    """Verify that Potions get Brecilien +15%, Cooked Food gets Caerleon +15%, and Tools get Caerleon +15%."""
    # Potions -> Brecilien bonus (0.2481 base RRR)
    subcat_pot = get_item_crafting_subcategory("T4_POTION_HEAL", "consumables")
    assert subcat_pot == "potion"
    assert calculate_rrr("Brecilien", subcat_pot) == 0.2481
    assert calculate_rrr("Bridgewatch", subcat_pot) == 0.1525

    # Food / Meals -> Caerleon bonus (0.2481 base RRR)
    subcat_food = get_item_crafting_subcategory("T7_MEAL_ROASTPORK", "consumables")
    assert subcat_food == "cooked_food"
    assert calculate_rrr("Caerleon", subcat_food) == 0.2481
    assert calculate_rrr("Lymhurst", subcat_food) == 0.1525

    # Gathering Tools -> Caerleon Toolmaker bonus (NOT weapon axe!)
    subcat_tool = get_item_crafting_subcategory("T4_2H_TOOL_AXE", "gathering")
    assert subcat_tool == "gathering_tool"
    assert calculate_rrr("Caerleon", subcat_tool) == 0.2481

    # Gathering Gear -> Caerleon Gathering Gear bonus
    subcat_gear = get_item_crafting_subcategory("T4_ARMOR_GATHERER_FIBER", "armors")
    assert subcat_gear == "gathering_gear"
    assert calculate_rrr("Caerleon", subcat_gear) == 0.2481


def test_get_price_level_alias_resolution():
    """Verify that _get_price properly resolves _LEVEL{e} to @{e} and doesn't strip to flat base."""
    engine = OpportunityScanner()
    prices = {
        "T4_CLOTH@1": {
            "Lymhurst": {
                1: {"sell_price_min": 1200, "buy_price_max": 1000, "volume_24h": 500, "data_age_seconds": 100}
            }
        },
        "T4_CLOTH": {
            "Lymhurst": {
                1: {"sell_price_min": 400, "buy_price_max": 300, "volume_24h": 500, "data_age_seconds": 100}
            }
        }
    }

    # Looking up T4_CLOTH_LEVEL1 must find T4_CLOTH@1 (price 1200), NOT flat T4_CLOTH (price 400)
    p_level = engine._get_price(prices, "T4_CLOTH_LEVEL1", "Lymhurst", 1)
    assert p_level is not None
    assert p_level["sell_price_min"] == 1200


def test_scan_island_production_and_naming():
    """Verify scan_island generates opportunities with Personal Island (City) naming and biome bonus."""
    engine = OpportunityScanner(premium=True, min_craft_profit=100)
    engine.allow_zero_volume = True

    # Carrot recipe in Lymhurst (Lymhurst has +10% carrot bonus!)
    prices = {
        "T1_FARM_CARROT_SEED": {
            "Lymhurst": {
                1: {"sell_price_min": 250, "buy_price_max": 220, "volume_24h": 1000, "data_age_seconds": 50}
            }
        },
        "T1_CARROT": {
            "Lymhurst": {
                1: {"sell_price_min": 380, "buy_price_max": 350, "volume_24h": 1000, "data_age_seconds": 50}
            }
        }
    }
    recipes = {
        "T1_CARROT": {
            "ingredients": [{"item_id": "T1_FARM_CARROT_SEED", "quantity": 1.0, "is_returnable": False}]
        }
    }
    names = {"T1_CARROT": "Carrots", "T1_FARM_CARROT_SEED": "Carrot Seeds"}
    categories = {"T1_CARROT": "farming", "T1_FARM_CARROT_SEED": "farming"}
    values = {"T1_CARROT": 8.0}

    opps = engine.scan_island(prices, names, recipes, categories, values)
    assert len(opps) >= 1
    opp = next(o for o in opps if "Lymhurst" in o.craft_city)
    assert "Personal Island (Lymhurst)" in opp.craft_city
    assert opp.sell_city == "Lymhurst"
    assert opp.profit > 0


def test_format_island_embed():
    """Verify DiscordAlerter._format_island_embed creates a valid embed dictionary."""
    alerter = DiscordAlerter()
    opp = {
        "item_id": "T1_CARROT",
        "item_name": "Carrots",
        "craft_city": "Personal Island (Lymhurst)",
        "crafting_city": "Personal Island (Lymhurst)",
        "source_city": "Personal Island (Lymhurst)",
        "sell_city": "Lymhurst",
        "destination_city": "Lymhurst Market",
        "buy_city": "Lymhurst",
        "total_cost": 100,
        "sell_price": 500,
        "profit": 350,
        "profit_pct": 350.0,
        "roi": 350.0,
        "safe_limit": 100,
        "daily_volume": 500,
        "data_age_materials": 100,
        "data_age_sell": 100,
        "rrr_used": 0.0,
        "ingredients": [
            {"item_id": "T1_FARM_CARROT_SEED", "name": "Carrot Seeds", "quantity": 1, "unit_price": 100, "buy_city": "Lymhurst"}
        ]
    }

    embed = alerter._format_island_embed(opp)
    assert "Carrots" in embed["title"]
    assert "Personal Island (Lymhurst)" in embed["description"]
    assert "Lymhurst Market" in embed["description"]
    assert "Biome Specialty" in embed["description"]  # Lymhurst carrot bonus tag
    assert len(embed["fields"]) >= 3
