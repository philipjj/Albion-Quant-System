import pytest
from app.core.farming_constants import (
    CITY_ISLAND_BIOMES,
    CROPS,
    HERBS,
    LIVESTOCK,
    MOUNTS,
    get_city_biome_farming_bonus,
)
from app.core.opportunity_engine import OpportunityScanner, CraftingOpportunity
from app.alerts.discord import DiscordAlerter


def test_island_biome_bonuses():
    """Verify official +10% island biome bonuses per city."""
    # Bridgewatch: Corn, Beans, Dragon Teasel, Goats, Horses
    assert get_city_biome_farming_bonus("Bridgewatch", "T7_CORN") == 0.10
    assert get_city_biome_farming_bonus("Bridgewatch", "T2_BEAN") == 0.10
    assert get_city_biome_farming_bonus("Bridgewatch", "T5_TEASEL") == 0.10
    assert get_city_biome_farming_bonus("Bridgewatch Island", "T4_MILK") == 0.10
    assert get_city_biome_farming_bonus("Personal Island (Bridgewatch)", "T4_MEAT") == 0.10
    assert get_city_biome_farming_bonus("Bridgewatch", "T4_TURNIP") == 0.0  # Turnip is Fort Sterling

    # Fort Sterling: Turnip, Ghoul Yarrow, Sheep, Chickens
    assert get_city_biome_farming_bonus("Fort Sterling", "T4_TURNIP") == 0.10
    assert get_city_biome_farming_bonus("Fort Sterling", "T8_YARROW") == 0.10
    assert get_city_biome_farming_bonus("Fort Sterling", "T3_EGG") == 0.10
    assert get_city_biome_farming_bonus("Fort Sterling", "T3_MEAT") == 0.10

    # Lymhurst: Carrots, Pumpkin, Burdock, Goose
    assert get_city_biome_farming_bonus("Lymhurst", "T1_CARROT") == 0.10
    assert get_city_biome_farming_bonus("Lymhurst", "T8_PUMPKIN") == 0.10
    assert get_city_biome_farming_bonus("Lymhurst", "T4_BURDOCK") == 0.10
    assert get_city_biome_farming_bonus("Lymhurst", "T5_EGG") == 0.10

    # Martlock: Wheat, Potato, Foxglove, Cow
    assert get_city_biome_farming_bonus("Martlock", "T3_WHEAT") == 0.10
    assert get_city_biome_farming_bonus("Martlock", "T6_POTATO") == 0.10
    assert get_city_biome_farming_bonus("Martlock", "T6_FOXGLOVE") == 0.10
    assert get_city_biome_farming_bonus("Martlock", "T8_MILK") == 0.10

    # Thetford: Cabbage, Agaric, Mullein, Pig
    assert get_city_biome_farming_bonus("Thetford", "T5_CABBAGE") == 0.10
    assert get_city_biome_farming_bonus("Thetford", "T2_AGARIC") == 0.10
    assert get_city_biome_farming_bonus("Thetford", "T7_MEAT") == 0.10


def test_crops_and_herbs_factual_yield_and_plot_profit():
    """Verify that scan_island evaluates crops with 9.0 (or 9.9) yield and factual seed return rates."""
    engine = OpportunityScanner(premium=True, min_craft_profit=100)
    engine.allow_zero_volume = True

    # Turnip on Fort Sterling (Fort Sterling has +10% turnip bonus)
    # Seed price = 2,500s. Turnip sell price = 400s.
    # Unwatered seed return = 80% (net seed loss = 500s).
    # Effective yield = 9.0 * 1.10 = 9.9 turnips.
    # Revenue = 9.9 * 400 * (1 - 0.04 - 0.025) = 3,702.6s.
    # Spot profit = 3,702.6 - 500 = 3,202.6s.
    # Plot profit / day (9 spots) = 3,202.6 * 9 = ~28,823s.
    prices = {
        "T4_FARM_TURNIP_SEED": {
            "Fort Sterling": {
                1: {"sell_price_min": 2500, "buy_price_max": 2200, "volume_24h": 500, "data_age_seconds": 60}
            }
        },
        "T4_TURNIP": {
            "Fort Sterling": {
                1: {"sell_price_min": 400, "buy_price_max": 380, "volume_24h": 2000, "data_age_seconds": 60}
            }
        }
    }
    names = {"T4_TURNIP": "Turnips", "T4_FARM_TURNIP_SEED": "Turnip Seeds"}
    recipes = {}
    categories = {"T4_TURNIP": "farming"}
    values = {"T4_TURNIP": 32.0}

    opps = engine.scan_island(prices, names, recipes, categories, values)
    turnip_opps = [o for o in opps if o.item_id == "T4_TURNIP"]
    assert len(turnip_opps) >= 1
    opp = turnip_opps[0]
    assert "Fort Sterling" in opp.craft_city
    assert opp.profit > 0
    assert opp.profit_per_plot_day > 20000  # Positive daily plot profit!
    assert opp.biome_bonus_active is True
    assert opp.cycle_hours == 22.0
    assert opp.subsector == "crops"
    assert opp.ingredients[0]["yield_per_spot"] == 9.9
    assert opp.ingredients[0]["plot_yield"] == 89.1
    assert opp.output_qty == 10  # 9.9 rounded to 10 batch yield


def test_livestock_butcher_20_meat_yield():
    """Verify that butchering livestock yields 20 units of raw meat (+10% on biome city)."""
    engine = OpportunityScanner(premium=True, min_craft_profit=100)
    engine.allow_zero_volume = True

    # Chicken on Fort Sterling (+10% bonus for Chicken / T3_MEAT)
    # Baby chicken = 5,000s. Raw chicken meat = 500s.
    # Offspring return = 80% (net baby cost = 1,000s).
    # Feed = 10 carrots @ 300s = 3,000s.
    # Total cost = 4,000s.
    # Yield = 20 * 1.10 = 22 raw meats.
    # Revenue = 22 * 500 * 0.935 = 10,285s.
    # Profit = 10,285 - 4,000 = +6,285s!
    prices = {
        "T3_FARM_CHICKEN_BABY": {
            "Fort Sterling": {
                1: {"sell_price_min": 5000, "buy_price_max": 4500, "volume_24h": 200, "data_age_seconds": 60}
            }
        },
        "T1_CARROT": {
            "Fort Sterling": {
                1: {"sell_price_min": 300, "buy_price_max": 280, "volume_24h": 5000, "data_age_seconds": 60}
            }
        },
        "T3_MEAT": {
            "Fort Sterling": {
                1: {"sell_price_min": 500, "buy_price_max": 480, "volume_24h": 3000, "data_age_seconds": 60}
            }
        }
    }
    names = {"T3_MEAT": "Raw Chicken", "T3_FARM_CHICKEN_BABY": "Baby Chickens", "T1_CARROT": "Carrots"}
    recipes = {}
    categories = {"T3_MEAT": "meat"}
    values = {"T3_MEAT": 16.0}

    opps = engine.scan_island(prices, names, recipes, categories, values)
    meat_opps = [o for o in opps if o.item_id == "T3_MEAT"]
    assert len(meat_opps) >= 1
    opp = meat_opps[0]
    assert opp.profit > 0
    assert opp.profit_per_plot_day > 0
    assert opp.subsector == "livestock"
    assert opp.biome_bonus_active is True
    assert opp.output_qty == 22  # 20 * 1.10 = 22 meat slaughter yield


def test_mount_raising_pipeline():
    """Verify that raising foals and saddling with leather produces positive profit when market allows."""
    engine = OpportunityScanner(premium=True, min_craft_profit=100)
    engine.allow_zero_volume = True

    # T3 Horse on Bridgewatch (+10% horse bonus)
    # Foal = 10,000s. Feed = 10 carrots @ 300s = 3,000s.
    # 20 T3 Leather @ 400s = 8,000s.
    # Total cost = 10,000 + 3,000 + 8,000 = 21,000s.
    # Finished T3 Riding Horse sells for 35,000s.
    # Revenue = 35,000 * 0.935 = 32,725s.
    # Profit = 32,725 - 21,000 = +11,725s!
    prices = {
        "T3_FARM_HORSE_BABY": {
            "Bridgewatch": {
                1: {"sell_price_min": 10000, "buy_price_max": 9000, "volume_24h": 100, "data_age_seconds": 60}
            }
        },
        "T1_CARROT": {
            "Bridgewatch": {
                1: {"sell_price_min": 300, "buy_price_max": 280, "volume_24h": 5000, "data_age_seconds": 60}
            }
        },
        "T3_LEATHER": {
            "Bridgewatch": {
                1: {"sell_price_min": 400, "buy_price_max": 380, "volume_24h": 5000, "data_age_seconds": 60}
            }
        },
        "T3_MOUNT_HORSE": {
            "Bridgewatch": {
                1: {"sell_price_min": 35000, "buy_price_max": 30000, "volume_24h": 300, "data_age_seconds": 60}
            }
        }
    }
    names = {"T3_MOUNT_HORSE": "Riding Horse (T3)", "T3_FARM_HORSE_BABY": "Journeyman's Foal", "T3_LEATHER": "Thick Leather"}
    recipes = {}
    categories = {"T3_MOUNT_HORSE": "mounts"}
    values = {"T3_MOUNT_HORSE": 1000.0}

    opps = engine.scan_island(prices, names, recipes, categories, values)
    mount_opps = [o for o in opps if o.item_id == "T3_MOUNT_HORSE"]
    assert len(mount_opps) >= 1
    opp = mount_opps[0]
    assert opp.profit > 0
    assert opp.subsector == "mounts"
    assert opp.profit_per_plot_day > 0


def test_format_island_embed():
    """Verify DiscordAlerter._format_island_embed creates a valid embed with plot profit."""
    alerter = DiscordAlerter()
    opp = {
        "item_id": "T4_TURNIP",
        "item_name": "Turnips",
        "craft_city": "Personal Island (Fort Sterling)",
        "crafting_city": "Personal Island (Fort Sterling)",
        "source_city": "Personal Island (Fort Sterling)",
        "sell_city": "Fort Sterling",
        "destination_city": "Fort Sterling Market",
        "buy_city": "Fort Sterling",
        "total_cost": 500,
        "sell_price": 400,
        "profit": 3200,
        "profit_pct": 640.0,
        "roi": 640.0,
        "profit_per_plot_day": 28800,
        "silver_per_focus": 1.2,
        "cycle_hours": 22.0,
        "safe_limit": 100,
        "daily_volume": 2000,
        "data_age_materials": 60,
        "data_age_sell": 60,
        "rrr_used": 0.80,
        "ingredients": [
            {"item_id": "T4_FARM_TURNIP_SEED", "name": "Turnip Seeds", "quantity": 1, "unit_price": 2500, "buy_city": "Fort Sterling"}
        ]
    }

    embed = alerter._format_island_embed(opp)
    assert "Turnips" in embed["title"]
    assert "Personal Island (Fort Sterling)" in embed["description"]
    assert "Biome Specialty" in embed["description"]
    assert len(embed["fields"]) >= 3
    # Check that Plot Profit/Day is in the yield field
    yield_field = next(f for f in embed["fields"] if "Yield & Efficiency" in f["name"])
    assert "Plot Profit/Day" in yield_field["value"]
