"""
Tests for equipment crafting, enchanted recipe ingredients, subcategory bonus resolution,
and artifact/vanity exclusions.
"""

import pytest
from app.core.market_utils import get_item_crafting_subcategory, calculate_rrr
from app.core.opportunity_engine import OpportunityScanner, ROYAL_SAFE_CITIES
from app.core.constants import CITY_CRAFTING_BONUSES


def test_get_item_crafting_subcategory():
    """Verify subcategory extraction for city bonus matching."""
    assert get_item_crafting_subcategory("T4_MAIN_SWORD") == "sword"
    assert get_item_crafting_subcategory("T6_2H_BOW") == "bow"
    assert get_item_crafting_subcategory("T5_2H_CROSSBOW") == "crossbow"
    assert get_item_crafting_subcategory("T4_2H_AXE") == "axe"
    assert get_item_crafting_subcategory("T4_ARMOR_PLATE_SET1") == "plate_armor"
    assert get_item_crafting_subcategory("T6_ARMOR_LEATHER_SET1") == "leather_armor"
    assert get_item_crafting_subcategory("T4_ARMOR_CLOTH_SET1") == "cloth_armor"
    assert get_item_crafting_subcategory("T5_HEAD_PLATE_SET1") == "plate_helmet"
    assert get_item_crafting_subcategory("T6_HEAD_LEATHER_SET1") == "leather_helmet"
    assert get_item_crafting_subcategory("T4_HEAD_CLOTH_SET1") == "cloth_cowl"
    assert get_item_crafting_subcategory("T4_SHOES_PLATE_SET1") == "plate_shoes"
    assert get_item_crafting_subcategory("T5_SHOES_LEATHER_SET1") == "leather_shoes"
    assert get_item_crafting_subcategory("T6_SHOES_CLOTH_SET1") == "cloth_shoes"
    assert get_item_crafting_subcategory("T7_OFF_SHIELD") == "offhand"
    assert get_item_crafting_subcategory("T4_BAG") == "bag"
    assert get_item_crafting_subcategory("T4_CAPE") == "cape"


def test_city_crafting_rrr_specialization():
    """Verify each item subcategory receives its +15% LPB bonus in the designated city."""
    # Swords -> Lymhurst
    rrr_lym_sword = calculate_rrr("Lymhurst", "sword")
    rrr_mart_sword = calculate_rrr("Martlock", "sword")
    assert rrr_lym_sword > rrr_mart_sword

    # Axes -> Martlock
    rrr_mart_axe = calculate_rrr("Martlock", "axe")
    rrr_lym_axe = calculate_rrr("Lymhurst", "axe")
    assert rrr_mart_axe > rrr_lym_axe

    # Plate Armor -> Bridgewatch
    rrr_bw_plate = calculate_rrr("Bridgewatch", "plate_armor")
    rrr_thet_plate = calculate_rrr("Thetford", "plate_armor")
    assert rrr_bw_plate > rrr_thet_plate

    # Leather Armor -> Thetford
    rrr_thet_leather = calculate_rrr("Thetford", "leather_armor")
    rrr_fs_leather = calculate_rrr("Fort Sterling", "leather_armor")
    assert rrr_thet_leather > rrr_fs_leather

    # Plate Helmet -> Fort Sterling
    rrr_fs_helm = calculate_rrr("Fort Sterling", "plate_helmet")
    rrr_bw_helm = calculate_rrr("Bridgewatch", "plate_helmet")
    assert rrr_fs_helm > rrr_bw_helm


def test_enchanted_ingredient_resolution():
    """Verify that enchanted recipes use Albion API refined material keys (_LEVEL{e}@{e})."""
    from app.core.scanner_integration import UnifiedScanner
    scanner = UnifiedScanner(premium=True)

    class MockRecipe:
        def __init__(self, cid, ing_id, qty):
            self.crafted_item_id = cid
            self.ingredient_item_id = ing_id
            self.quantity = qty

    class MockQuery:
        def all(self):
            return [
                MockRecipe("T4_MAIN_SWORD", "T4_METALBAR", 16.0),
                MockRecipe("T4_MAIN_SWORD", "T4_LEATHER", 8.0),
                MockRecipe("T6_ARTEFACT_2H_DUALAXE_KEEPER", "QUESTITEM_TOKEN_AVALON", 50.0),
                MockRecipe("UNIQUE_UNLOCK_ARMOR_VANITY_PIRATE", "UNIQUE_TOKEN_COMMUNITY", 1.0),
            ]

    class MockSession:
        def query(self, *args):
            return MockQuery()

    recipes = scanner._load_recipes(MockSession())

    # Raw artifact and vanity recipes must be excluded
    assert "T6_ARTEFACT_2H_DUALAXE_KEEPER" not in recipes
    assert "UNIQUE_UNLOCK_ARMOR_VANITY_PIRATE" not in recipes

    # Base sword recipe exists
    assert "T4_MAIN_SWORD" in recipes
    assert len(recipes["T4_MAIN_SWORD"]["ingredients"]) == 2

    # Enchanted sword recipes must use _LEVEL{e}@{e} for refined materials
    assert "T4_MAIN_SWORD@1" in recipes
    ing_ids_1 = [ing["item_id"] for ing in recipes["T4_MAIN_SWORD@1"]["ingredients"]]
    assert "T4_METALBAR_LEVEL1@1" in ing_ids_1
    assert "T4_LEATHER_LEVEL1@1" in ing_ids_1

    assert "T4_MAIN_SWORD@2" in recipes
    ing_ids_2 = [ing["item_id"] for ing in recipes["T4_MAIN_SWORD@2"]["ingredients"]]
    assert "T4_METALBAR_LEVEL2@2" in ing_ids_2
    assert "T4_LEATHER_LEVEL2@2" in ing_ids_2


def test_crafting_equipment_opportunities_filtering():
    """Verify scan_crafting produces opportunities for equipment and skips raw artifacts."""
    engine = OpportunityScanner(premium=True, min_craft_profit=1000)
    engine.crafting_local_sourcing_only = False
    engine.allow_zero_volume = True

    recipes = {
        "T4_MAIN_SWORD": {
            "ingredients": [
                {"item_id": "T4_METALBAR", "quantity": 16.0},
                {"item_id": "T4_LEATHER", "quantity": 8.0},
            ]
        },
        "T6_ARTEFACT_2H_DUALAXE_KEEPER": {
            "ingredients": [
                {"item_id": "QUESTITEM_TOKEN_AVALON", "quantity": 50.0},
            ]
        }
    }

    prices = {
        "T4_METALBAR": {
            "Thetford": {
                1: {"sell_price_min": 300, "buy_price_max": 250, "volume_24h": 1000, "data_age_seconds": 100}
            }
        },
        "T4_LEATHER": {
            "Martlock": {
                1: {"sell_price_min": 400, "buy_price_max": 350, "volume_24h": 1000, "data_age_seconds": 100}
            }
        },
        "T4_MAIN_SWORD": {
            "Lymhurst": {
                1: {"sell_price_min": 9800, "buy_price_max": 9500, "volume_24h": 100, "data_age_seconds": 100}
            }
        },
        "QUESTITEM_TOKEN_AVALON": {
            "Bridgewatch": {
                1: {"sell_price_min": 100, "buy_price_max": 90, "volume_24h": 500, "data_age_seconds": 100}
            }
        },
        "T6_ARTEFACT_2H_DUALAXE_KEEPER": {
            "Martlock": {
                1: {"sell_price_min": 200000, "buy_price_max": 180000, "volume_24h": 10, "data_age_seconds": 100}
            }
        },
    }

    names = {
        "T4_MAIN_SWORD": "Adept's Broadsword",
        "T6_ARTEFACT_2H_DUALAXE_KEEPER": "Master's Keeper Axeheads",
    }
    categories = {
        "T4_MAIN_SWORD": "weapons",
        "T6_ARTEFACT_2H_DUALAXE_KEEPER": "artefacts",
    }
    values = {
        "T4_MAIN_SWORD": 2000.0,
        "T6_ARTEFACT_2H_DUALAXE_KEEPER": 10000.0,
    }

    opps = engine.scan_crafting(prices, names, recipes, categories, values)

    # Must contain T4_MAIN_SWORD
    item_ids = [o.item_id for o in opps]
    assert "T4_MAIN_SWORD" in item_ids
    # Must NOT contain raw artifact
    assert "T6_ARTEFACT_2H_DUALAXE_KEEPER" not in item_ids

    sword_opp = next(o for o in opps if o.item_id == "T4_MAIN_SWORD")
    assert sword_opp.craft_city == "Lymhurst"  # Sword bonus city
    assert sword_opp.sell_city == "Lymhurst"
    assert sword_opp.profit > 0


def test_crafting_level_4_equipment_with_level_4_materials():
    """Verify that .4 equipment crafts are allowed and resolve .4 material costs accurately."""
    engine = OpportunityScanner(premium=True, min_craft_profit=1000)
    engine.crafting_local_sourcing_only = False
    engine.allow_zero_volume = True

    recipes = {
        "T5_MAIN_SWORD@4": {
            "ingredients": [
                {"item_id": "T5_METALBAR_LEVEL4@4", "quantity": 16.0},
                {"item_id": "T5_LEATHER_LEVEL4@4", "quantity": 8.0},
            ]
        }
    }

    # Prices using @4 shorthand or full _LEVEL4@4 keys
    prices = {
        "T5_METALBAR@4": {
            "Thetford": {
                1: {"sell_price_min": 15000, "buy_price_max": 14000, "volume_24h": 500, "data_age_seconds": 100}
            }
        },
        "T5_LEATHER_LEVEL4@4": {
            "Martlock": {
                1: {"sell_price_min": 18000, "buy_price_max": 16000, "volume_24h": 500, "data_age_seconds": 100}
            }
        },
        "T5_MAIN_SWORD@4": {
            "Lymhurst": {
                1: {"sell_price_min": 350000, "buy_price_max": 330000, "volume_24h": 20, "data_age_seconds": 100}
            }
        }
    }

    names = {"T5_MAIN_SWORD@4": "Expert's Broadsword .4"}
    categories = {"T5_MAIN_SWORD@4": "weapons"}
    values = {"T5_MAIN_SWORD@4": 8000.0}

    opps = engine.scan_crafting(prices, names, recipes, categories, values)
    assert len(opps) == 1
    opp = opps[0]
    assert opp.item_id == "T5_MAIN_SWORD@4"
    assert opp.craft_city == "Lymhurst"
    assert opp.profit > 0


def test_royal_and_faction_cape_crafting():
    """Verify that Royal / Faction Capes can be crafted using Base Cape + Crest + Faction Heart."""
    engine = OpportunityScanner(premium=True, min_craft_profit=1000)
    engine.crafting_local_sourcing_only = False
    engine.allow_zero_volume = True

    recipes = {
        "T4_CAPEITEM_FW_BRIDGEWATCH": {
            "ingredients": [
                {"item_id": "T4_CAPE", "quantity": 1.0},
                {"item_id": "T4_CAPEITEM_FW_BRIDGEWATCH_BP", "quantity": 1.0},
                {"item_id": "T1_FACTION_STEPPE_TOKEN_1", "quantity": 1.0},
            ]
        }
    }

    prices = {
        "T4_CAPE": {
            "Bridgewatch": {1: {"sell_price_min": 3000, "buy_price_max": 2500, "volume_24h": 100, "data_age_seconds": 100}}
        },
        "T4_CAPEITEM_FW_BRIDGEWATCH_BP": {
            "Bridgewatch": {1: {"sell_price_min": 15000, "buy_price_max": 12000, "volume_24h": 50, "data_age_seconds": 100}}
        },
        "T1_FACTION_STEPPE_TOKEN_1": {
            "Bridgewatch": {1: {"sell_price_min": 35000, "buy_price_max": 32000, "volume_24h": 500, "data_age_seconds": 100}}
        },
        "T4_CAPEITEM_FW_BRIDGEWATCH": {
            "Bridgewatch": {1: {"sell_price_min": 75000, "buy_price_max": 65000, "volume_24h": 30, "data_age_seconds": 100}}
        },
    }

    names = {"T4_CAPEITEM_FW_BRIDGEWATCH": "Adept's Bridgewatch Cape"}
    categories = {"T4_CAPEITEM_FW_BRIDGEWATCH": "capes"}
    values = {"T4_CAPEITEM_FW_BRIDGEWATCH": 2000.0}

    opps = engine.scan_crafting(prices, names, recipes, categories, values)
    assert len(opps) == 1
    opp = opps[0]
    assert opp.item_id == "T4_CAPEITEM_FW_BRIDGEWATCH"
    assert opp.craft_city == "Bridgewatch"
    assert opp.profit > 0
    assert opp.roi > 20.0


def test_royal_equipment_crafting_with_sigils():
    """Verify that Royal armor/cowl/shoes can be crafted using base item + Royal Sigils."""
    engine = OpportunityScanner(premium=True, min_craft_profit=1000)
    engine.crafting_local_sourcing_only = False
    engine.allow_zero_volume = True

    recipes = {
        "T4_HEAD_CLOTH_ROYAL": {
            "ingredients": [
                {"item_id": "T4_HEAD_CLOTH_SET1", "quantity": 1.0},
                {"item_id": "QUESTITEM_TOKEN_ROYAL_T4", "quantity": 2.0},
            ]
        }
    }

    prices = {
        "T4_HEAD_CLOTH_SET1": {
            "Thetford": {1: {"sell_price_min": 2500, "buy_price_max": 2000, "volume_24h": 100, "data_age_seconds": 100}}
        },
        "QUESTITEM_TOKEN_ROYAL_T4": {
            "Thetford": {1: {"sell_price_min": 5000, "buy_price_max": 4500, "volume_24h": 200, "data_age_seconds": 100}}
        },
        "T4_HEAD_CLOTH_ROYAL": {
            "Thetford": {1: {"sell_price_min": 20000, "buy_price_max": 17000, "volume_24h": 30, "data_age_seconds": 100}}
        },
    }

    names = {"T4_HEAD_CLOTH_ROYAL": "Adept's Royal Cowl"}
    categories = {"T4_HEAD_CLOTH_ROYAL": "head"}
    values = {"T4_HEAD_CLOTH_ROYAL": 2000.0}

    opps = engine.scan_crafting(prices, names, recipes, categories, values)
    assert len(opps) == 1
    opp = opps[0]
    assert opp.item_id == "T4_HEAD_CLOTH_ROYAL"
    assert opp.craft_city == "Thetford"
    assert opp.profit > 0
