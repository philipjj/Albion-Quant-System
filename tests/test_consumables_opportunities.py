import pytest
from app.core.opportunity_engine import OpportunityScanner, CraftingOpportunity
from app.core.freshness import is_market_data_fresh, _classify_item, COMMODITY_AGE_LIMITS


def test_commodity_freshness_classification():
    """Verify agricultural commodities (herbs, crops, milk, meat, eggs) get 24h age limit."""
    assert _classify_item("T4_BURDOCK") == "commodity"
    assert _classify_item("T4_TURNIP") == "commodity"
    assert _classify_item("T4_MILK") == "commodity"
    assert _classify_item("T4_MEAT") == "commodity"
    assert _classify_item("T3_EGG") == "commodity"
    assert _classify_item("T3_FLOUR") == "commodity"
    assert _classify_item("T4_BUTTER") == "commodity"
    assert _classify_item("T1_FISHCHOPS") == "commodity"

    # Verify age limit is 86,400 seconds (24 hours) for T4.0 commodity
    assert COMMODITY_AGE_LIMITS[(4, 0)] == 86400

    # 12 hours old (43,200s) should be fresh for a commodity
    assert is_market_data_fresh("T4_BURDOCK", 43200, city="Bridgewatch") is True
    # 26 hours old (95,000s) should be stale (exceeds 86,400s threshold)
    assert is_market_data_fresh("T4_BURDOCK", 95000, city="Bridgewatch") is False


def test_potions_batch_yield_5x():
    """Verify that crafting 1 potion batch yields 5 potions and calculates revenue accordingly."""
    engine = OpportunityScanner(premium=True, min_craft_profit=10)
    engine.allow_zero_volume = True

    # Potion: T4_POTION_HEAL requires 12x T4_BURDOCK
    # Burdock cost: 500s each -> 12 * 500 = 6,000s gross
    # With 5x batch yield @ 2,500s each: 5 * 2,500 = 12,500s gross revenue
    mock_prices = {
        "T4_BURDOCK": {
            "Brecilien": {1: {"sell_price_min": 500, "buy_price_max": 450, "volume_24h": 5000, "data_age_seconds": 300}}
        },
        "T4_POTION_HEAL": {
            "Brecilien": {1: {"sell_price_min": 2500, "buy_price_max": 2200, "volume_24h": 5000, "data_age_seconds": 300}}
        },
    }
    recipes = {"T4_POTION_HEAL": {"ingredients": [{"item_id": "T4_BURDOCK", "quantity": 12}]}}
    names = {"T4_POTION_HEAL": "Major Healing Potion", "T4_BURDOCK": "Arcane Burdock"}
    categories = {"T4_POTION_HEAL": "potions", "T4_BURDOCK": "farming"}
    values = {"T4_POTION_HEAL": 100.0, "T4_BURDOCK": 20.0}

    # Brecilien has +15% LPB for potions (24.81% base RRR)
    potions, _ = engine.scan_consumables(mock_prices, names, recipes, categories, values)
    heal_opps = [o for o in potions if "HEAL" in o.item_id and o.craft_city == "Brecilien"]
    assert len(heal_opps) > 0

    opp = heal_opps[0]
    assert opp.output_qty == 5
    # Revenue must reflect 5 items: 5 * 2500 * (1 - 0.04 - 0.025) = 11,687.5s net
    expected_net_rev = 5 * 2500 * (1.0 - 0.04 - 0.025)
    assert abs(opp.revenue_net - expected_net_rev) < 1.0

    # Net material cost with 24.81% RRR
    assert abs(opp.rrr_used - 0.2481) < 0.001
    assert opp.profit > 6000  # Positive profit verified!


def test_cooking_batch_yield_10x():
    """Verify that cooking 1 food craft yields 10 meals and calculates revenue accordingly."""
    engine = OpportunityScanner(premium=True, min_craft_profit=10)
    engine.allow_zero_volume = True

    # Meal: T4_MEAL_STEW requires 8x T4_TURNIP, 4x T4_MEAT
    # Turnip: 500s ea, Meat: 500s ea -> 4000 + 2000 = 6000s gross
    # Stew sell price = 1500s ea -> 10x = 15,000s gross revenue
    mock_prices = {
        "T4_TURNIP": {
            "Caerleon": {1: {"sell_price_min": 500, "buy_price_max": 450, "volume_24h": 5000, "data_age_seconds": 300}}
        },
        "T4_MEAT": {
            "Caerleon": {1: {"sell_price_min": 500, "buy_price_max": 450, "volume_24h": 5000, "data_age_seconds": 300}}
        },
        "T4_MEAL_STEW": {
            "Caerleon": {1: {"sell_price_min": 1500, "buy_price_max": 1400, "volume_24h": 5000, "data_age_seconds": 300}}
        },
    }
    recipes = {"T4_MEAL_STEW": {"ingredients": [{"item_id": "T4_TURNIP", "quantity": 8}, {"item_id": "T4_MEAT", "quantity": 4}]}}
    names = {"T4_MEAL_STEW": "Turnip Stew", "T4_TURNIP": "Turnip", "T4_MEAT": "Raw Meat"}
    categories = {"T4_MEAL_STEW": "cooking", "T4_TURNIP": "farming", "T4_MEAT": "farming"}
    values = {"T4_MEAL_STEW": 120.0, "T4_TURNIP": 25.0, "T4_MEAT": 50.0}

    # Caerleon has +15% LPB for cooking (24.81% base RRR)
    _, cooking = engine.scan_consumables(mock_prices, names, recipes, categories, values)
    stew_opps = [o for o in cooking if "STEW" in o.item_id and o.craft_city == "Caerleon"]
    assert len(stew_opps) > 0

    opp = stew_opps[0]
    assert opp.output_qty == 10
    expected_net_rev = 10 * 1500 * (1.0 - 0.04 - 0.025)
    assert abs(opp.revenue_net - expected_net_rev) < 1.0
    assert abs(opp.rrr_used - 0.2481) < 0.001
    assert opp.profit > 9000


def test_city_lpb_specialization_differences():
    """Verify Brecilien gets 24.81% RRR for potions vs 15.25% in other royal cities, and Caerleon gets 24.81% for cooking."""
    from app.core.market_utils import calculate_rrr

    # Verify official Albion Online RRR bonus values
    assert abs(calculate_rrr("Brecilien", "potion", tier=4, use_focus=False) - 0.2481) < 0.001
    assert abs(calculate_rrr("Martlock", "potion", tier=4, use_focus=False) - 0.1525) < 0.001
    assert abs(calculate_rrr("Caerleon", "cooked_food", tier=4, use_focus=False) - 0.2481) < 0.001
    assert abs(calculate_rrr("Martlock", "cooked_food", tier=4, use_focus=False) - 0.1525) < 0.001

    # Focus RRR bonuses
    assert abs(calculate_rrr("Brecilien", "potion", tier=4, use_focus=True) - 0.479) < 0.01
    assert abs(calculate_rrr("Caerleon", "cooked_food", tier=4, use_focus=True) - 0.479) < 0.01

    # Verify engine routes potions to Brecilien to capture the 24.81% RRR bonus
    engine = OpportunityScanner(premium=True, min_craft_profit=1)
    engine.allow_zero_volume = True

    recipes = {"T4_POTION_HEAL": {"ingredients": [{"item_id": "T4_BURDOCK", "quantity": 12}]}}
    names = {"T4_POTION_HEAL": "Major Healing Potion", "T4_BURDOCK": "Arcane Burdock"}
    categories = {"T4_POTION_HEAL": "potions", "T4_BURDOCK": "farming"}
    values = {"T4_POTION_HEAL": 100.0, "T4_BURDOCK": 20.0}

    brecilien_prices = {
        "T4_BURDOCK": {"Brecilien": {1: {"sell_price_min": 500, "buy_price_max": 450, "volume_24h": 5000, "data_age_seconds": 300}}},
        "T4_POTION_HEAL": {"Brecilien": {1: {"sell_price_min": 2500, "buy_price_max": 2200, "volume_24h": 5000, "data_age_seconds": 300}}},
    }
    brecilien_opps, _ = engine.scan_consumables(brecilien_prices, names, recipes, categories, values)
    assert len(brecilien_opps) > 0
    b_opp = brecilien_opps[0]
    assert abs(b_opp.rrr_used - 0.2481) < 0.001
    assert b_opp.craft_city == "Brecilien"
    assert b_opp.biome_bonus_active is True


def test_farm_ingredients_are_returnable():
    """Verify that all agricultural ingredients (herbs, crops, meat, milk) are flagged returnable under RRR."""
    engine = OpportunityScanner(premium=True)
    recipe = {
        "ingredients": [
            {"item_id": "T4_BURDOCK", "quantity": 10},
            {"item_id": "T4_MEAT", "quantity": 5},
        ]
    }
    prices = {
        "T4_BURDOCK": {"Martlock": {1: {"sell_price_min": 100, "buy_price_max": 90, "data_age_seconds": 300}}},
        "T4_MEAT": {"Martlock": {1: {"sell_price_min": 200, "buy_price_max": 180, "data_age_seconds": 300}}},
    }
    total, ingredients, max_age = engine._calc_material_cost(
        "T4_POTION_HEAL", recipe, prices, "Martlock", quality=1, local_only=True
    )
    assert total == (10 * 100) + (5 * 200)
    assert len(ingredients) == 2
    assert ingredients[0]["is_returnable"] is True
    assert ingredients[1]["is_returnable"] is True


def test_consumable_bait_spread_rejected():
    """Verify that artificial bait prices (>2.5x buy order max) are rejected by scan_consumables."""
    engine = OpportunityScanner(premium=True, min_craft_profit=10)
    engine.allow_zero_volume = False

    # Fake market listing: sell_price_min is 10,000s while buy_price_max is only 2,000s (5x spread -> bait!)
    mock_prices = {
        "T4_BURDOCK": {
            "Brecilien": {1: {"sell_price_min": 500, "buy_price_max": 450, "volume_24h": 5000, "data_age_seconds": 300}}
        },
        "T4_POTION_HEAL": {
            "Brecilien": {1: {"sell_price_min": 10000, "buy_price_max": 2000, "volume_24h": 50, "data_age_seconds": 300}}
        },
    }
    recipes = {"T4_POTION_HEAL": {"ingredients": [{"item_id": "T4_BURDOCK", "quantity": 12}]}}
    names = {"T4_POTION_HEAL": "Major Healing Potion", "T4_BURDOCK": "Arcane Burdock"}
    categories = {"T4_POTION_HEAL": "potions", "T4_BURDOCK": "farming"}
    values = {"T4_POTION_HEAL": 100.0, "T4_BURDOCK": 20.0}

    potions, _ = engine.scan_consumables(mock_prices, names, recipes, categories, values)
    # The opportunity must be rejected due to sell_price > buy_max * 2.5
    assert len(potions) == 0


def test_consumable_borderline_spread_flagged_medium_risk():
    """Verify that borderline spreads (1.5x to 2.5x buy order max) are tagged with manipulation_risk='medium'."""
    engine = OpportunityScanner(premium=True, min_craft_profit=10)
    engine.allow_zero_volume = False

    # Spread: sell_price 3,500s vs buy_price 2,000s (1.75x -> borderline medium risk)
    mock_prices = {
        "T4_BURDOCK": {
            "Brecilien": {1: {"sell_price_min": 200, "buy_price_max": 180, "volume_24h": 5000, "data_age_seconds": 300}}
        },
        "T4_POTION_HEAL": {
            "Brecilien": {1: {"sell_price_min": 3500, "buy_price_max": 2000, "volume_24h": 50, "data_age_seconds": 300}}
        },
    }
    recipes = {"T4_POTION_HEAL": {"ingredients": [{"item_id": "T4_BURDOCK", "quantity": 12}]}}
    names = {"T4_POTION_HEAL": "Major Healing Potion", "T4_BURDOCK": "Arcane Burdock"}
    categories = {"T4_POTION_HEAL": "potions", "T4_BURDOCK": "farming"}
    values = {"T4_POTION_HEAL": 100.0, "T4_BURDOCK": 20.0}

    potions, _ = engine.scan_consumables(mock_prices, names, recipes, categories, values)
    assert len(potions) > 0
    opp = potions[0]
    assert opp.manipulation_risk == "medium"


def test_consumable_low_volume_rejected():
    """Verify that consumables with daily volume < min_vol (default 3) are rejected to prevent bait."""
    engine = OpportunityScanner(premium=True, min_craft_profit=10)
    engine.allow_zero_volume = False

    mock_prices = {
        "T4_BURDOCK": {
            "Brecilien": {1: {"sell_price_min": 200, "buy_price_max": 180, "volume_24h": 5000, "data_age_seconds": 300}}
        },
        "T4_POTION_HEAL": {
            "Brecilien": {1: {"sell_price_min": 2500, "buy_price_max": 2200, "volume_24h": 1, "data_age_seconds": 300}}
        },
    }
    recipes = {"T4_POTION_HEAL": {"ingredients": [{"item_id": "T4_BURDOCK", "quantity": 12}]}}
    names = {"T4_POTION_HEAL": "Major Healing Potion", "T4_BURDOCK": "Arcane Burdock"}
    categories = {"T4_POTION_HEAL": "potions", "T4_BURDOCK": "farming"}
    values = {"T4_POTION_HEAL": 100.0, "T4_BURDOCK": 20.0}

    potions, _ = engine.scan_consumables(mock_prices, names, recipes, categories, values)
    # volume_24h = 1 is below min_vol=3, so should be filtered
    assert len(potions) == 0

