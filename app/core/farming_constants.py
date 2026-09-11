"""
Authoritative Albion Online Island Agriculture, Pasture, and Mount Constants.
Up to date as of September 2026 (including Foundations, Wild Blood, and Dragonfire updates).
"""

from typing import Any, Dict, List, Optional

# ═══════════════════════════════════════════════════════════════
# CITY ISLAND BIOME SPECIALIZATIONS (+10% Yield Bonus)
# Official Albion Online Biome Local Production Bonuses per Host City
# ═══════════════════════════════════════════════════════════════

CITY_ISLAND_BIOMES: Dict[str, Dict[str, Any]] = {
    "Bridgewatch": {
        "crops": ["T2_BEAN", "T7_CORN"],
        "herbs": ["T5_TEASEL"],
        "livestock": ["T4_FARM_GOAT_GROWN", "T4_MILK", "T4_MEAT"],
        "mounts": ["T3_MOUNT_HORSE", "T4_MOUNT_HORSE", "T5_MOUNT_HORSE", "T6_MOUNT_HORSE", "T7_MOUNT_HORSE", "T8_MOUNT_HORSE", "T5_MOUNT_ARMORED_HORSE"],
        "bonus_yield_pct": 10.0,
        "theme": "Steppe",
    },
    "Fort Sterling": {
        "crops": ["T4_TURNIP"],
        "herbs": ["T8_YARROW"],
        "livestock": ["T3_FARM_CHICKEN_GROWN", "T6_FARM_SHEEP_GROWN", "T3_EGG", "T6_MILK", "T3_MEAT", "T6_MEAT"],
        "mounts": ["T5_MOUNT_DIREBEAR_FW_FORTSTERLING", "T8_MOUNT_DIREBEAR_FW_FORTSTERLING_ELITE"],
        "bonus_yield_pct": 10.0,
        "theme": "Mountain",
    },
    "Lymhurst": {
        "crops": ["T1_CARROT", "T8_PUMPKIN"],
        "herbs": ["T4_BURDOCK"],
        "livestock": ["T5_FARM_GOOSE_GROWN", "T5_EGG", "T5_MEAT"],
        "mounts": ["T4_MOUNT_GIANTSTAG", "T6_MOUNT_GIANTSTAG_MOOSE"],
        "bonus_yield_pct": 10.0,
        "theme": "Forest",
    },
    "Martlock": {
        "crops": ["T3_WHEAT", "T6_POTATO"],
        "herbs": ["T6_FOXGLOVE"],
        "livestock": ["T8_FARM_COW_GROWN", "T8_MILK", "T8_MEAT"],
        "mounts": ["T3_MOUNT_OX", "T4_MOUNT_OX", "T5_MOUNT_OX", "T6_MOUNT_OX", "T7_MOUNT_OX", "T8_MOUNT_OX", "T5_MOUNT_RAM_FW_MARTLOCK", "T8_MOUNT_RAM_FW_MARTLOCK_ELITE"],
        "bonus_yield_pct": 10.0,
        "theme": "Highland",
    },
    "Thetford": {
        "crops": ["T5_CABBAGE"],
        "herbs": ["T2_AGARIC", "T7_MULLEIN"],
        "livestock": ["T7_FARM_PIG_GROWN", "T7_MEAT"],
        "mounts": ["T7_MOUNT_SWAMPDRAGON", "T5_MOUNT_SWAMPDRAGON_FW_THETFORD", "T8_MOUNT_SWAMPDRAGON_FW_THETFORD_ELITE"],
        "bonus_yield_pct": 10.0,
        "theme": "Swamp",
    },
    "Caerleon": {
        "crops": [],
        "herbs": ["T3_COMFREY", "T5_TEASEL", "T7_MULLEIN"],
        "livestock": [],
        "mounts": ["T6_MOUNT_DIREWOLF", "T7_MOUNT_DIREBOAR", "T8_MOUNT_DIREBEAR"],
        "bonus_yield_pct": 10.0,
        "theme": "Bandit Outpost",
    },
    "Brecilien": {
        "crops": ["T1_CARROT", "T2_BEAN", "T3_WHEAT", "T4_TURNIP", "T5_CABBAGE", "T6_POTATO", "T7_CORN", "T8_PUMPKIN"],
        "herbs": ["T2_AGARIC", "T3_COMFREY", "T4_BURDOCK", "T5_TEASEL", "T6_FOXGLOVE", "T7_MULLEIN", "T8_YARROW"],
        "livestock": [],
        "mounts": ["T5_MOUNT_OWL_FW_BRECILIEN", "T8_MOUNT_OWL_FW_BRECILIEN_ELITE"],
        "bonus_yield_pct": 10.0,
        "theme": "Mists",
    },
}

# ═══════════════════════════════════════════════════════════════
# CROPS ONTOLOGY (Farm Plots — 9 squares per plot)
# Yield: 9.0 base crops per square with Premium (81 crops/plot)
# ═══════════════════════════════════════════════════════════════

CROPS: Dict[str, Dict[str, Any]] = {
    "T1_CARROT": {
        "tier": 1,
        "name": "Carrots",
        "seed_id": "T1_FARM_CARROT_SEED",
        "seed_name": "Carrot Seeds",
        "base_yield": 9.0,
        "base_return_pct": 0.0,       # 0% base return (must buy seeds if unwatered)
        "watered_return_pct": 200.0,  # 200% return with watering (2 seeds per plant)
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Lymhurst",
    },
    "T2_BEAN": {
        "tier": 2,
        "name": "Beans",
        "seed_id": "T2_FARM_BEAN_SEED",
        "seed_name": "Bean Seeds",
        "base_yield": 9.0,
        "base_return_pct": 66.67,
        "watered_return_pct": 106.67,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Bridgewatch",
    },
    "T3_WHEAT": {
        "tier": 3,
        "name": "Sheaf of Wheat",
        "seed_id": "T3_FARM_WHEAT_SEED",
        "seed_name": "Wheat Seeds",
        "base_yield": 9.0,
        "base_return_pct": 73.33,
        "watered_return_pct": 113.33,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Martlock",
    },
    "T4_TURNIP": {
        "tier": 4,
        "name": "Turnips",
        "seed_id": "T4_FARM_TURNIP_SEED",
        "seed_name": "Turnip Seeds",
        "base_yield": 9.0,
        "base_return_pct": 80.0,
        "watered_return_pct": 120.0,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Fort Sterling",
    },
    "T5_CABBAGE": {
        "tier": 5,
        "name": "Cabbage",
        "seed_id": "T5_FARM_CABBAGE_SEED",
        "seed_name": "Cabbage Seeds",
        "base_yield": 9.0,
        "base_return_pct": 86.67,
        "watered_return_pct": 126.67,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Thetford",
    },
    "T6_POTATO": {
        "tier": 6,
        "name": "Potatoes",
        "seed_id": "T6_FARM_POTATO_SEED",
        "seed_name": "Potato Seeds",
        "base_yield": 9.0,
        "base_return_pct": 91.11,
        "watered_return_pct": 131.11,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Martlock",
    },
    "T7_CORN": {
        "tier": 7,
        "name": "Bundle of Corn",
        "seed_id": "T7_FARM_CORN_SEED",
        "seed_name": "Corn Seeds",
        "base_yield": 9.0,
        "base_return_pct": 93.33,
        "watered_return_pct": 133.33,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Bridgewatch",
    },
    "T8_PUMPKIN": {
        "tier": 8,
        "name": "Pumpkin",
        "seed_id": "T8_FARM_PUMPKIN_SEED",
        "seed_name": "Pumpkin Seeds",
        "base_yield": 9.0,
        "base_return_pct": 94.44,
        "watered_return_pct": 134.44,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Lymhurst",
    },
}

# ═══════════════════════════════════════════════════════════════
# HERBS ONTOLOGY (Herb Garden — 9 squares per plot)
# Yield: 9.0 base herbs per square with Premium (81 herbs/plot)
# ═══════════════════════════════════════════════════════════════

HERBS: Dict[str, Dict[str, Any]] = {
    "T2_AGARIC": {
        "tier": 2,
        "name": "Arcane Agaric",
        "seed_id": "T2_FARM_AGARIC_SEED",
        "seed_name": "Arcane Agaric Seeds",
        "base_yield": 9.0,
        "base_return_pct": 66.67,
        "watered_return_pct": 106.67,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Thetford",
    },
    "T3_COMFREY": {
        "tier": 3,
        "name": "Brightleaf Comfrey",
        "seed_id": "T3_FARM_COMFREY_SEED",
        "seed_name": "Brightleaf Comfrey Seeds",
        "base_yield": 9.0,
        "base_return_pct": 73.33,
        "watered_return_pct": 113.33,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Caerleon",
    },
    "T4_BURDOCK": {
        "tier": 4,
        "name": "Crenellated Burdock",
        "seed_id": "T4_FARM_BURDOCK_SEED",
        "seed_name": "Crenellated Burdock Seeds",
        "base_yield": 9.0,
        "base_return_pct": 80.0,
        "watered_return_pct": 120.0,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Lymhurst",
    },
    "T5_TEASEL": {
        "tier": 5,
        "name": "Dragon Teasel",
        "seed_id": "T5_FARM_TEASEL_SEED",
        "seed_name": "Dragon Teasel Seeds",
        "base_yield": 9.0,
        "base_return_pct": 86.67,
        "watered_return_pct": 126.67,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Bridgewatch",
    },
    "T6_FOXGLOVE": {
        "tier": 6,
        "name": "Elusive Foxglove",
        "seed_id": "T6_FARM_FOXGLOVE_SEED",
        "seed_name": "Elusive Foxglove Seeds",
        "base_yield": 9.0,
        "base_return_pct": 91.11,
        "watered_return_pct": 131.11,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Martlock",
    },
    "T7_MULLEIN": {
        "tier": 7,
        "name": "Firetouched Mullein",
        "seed_id": "T7_FARM_MULLEIN_SEED",
        "seed_name": "Firetouched Mullein Seeds",
        "base_yield": 9.0,
        "base_return_pct": 93.33,
        "watered_return_pct": 133.33,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Thetford",
    },
    "T8_YARROW": {
        "tier": 8,
        "name": "Ghoul Yarrow",
        "seed_id": "T8_FARM_YARROW_SEED",
        "seed_name": "Ghoul Yarrow Seeds",
        "base_yield": 9.0,
        "base_return_pct": 94.44,
        "watered_return_pct": 134.44,
        "base_focus_cost": 1000,
        "growth_hours": 22.0,
        "biome_city": "Fort Sterling",
    },
}

# ═══════════════════════════════════════════════════════════════
# LIVESTOCK & PASTURES ONTOLOGY
# Feed: 10 crops per animal per day (22 hours)
# Butcher yield: 20 units of raw meat per grown animal
# ═══════════════════════════════════════════════════════════════

LIVESTOCK: Dict[str, Dict[str, Any]] = {
    "T3_FARM_CHICKEN": {
        "tier": 3,
        "name": "Chicken",
        "baby_id": "T3_FARM_CHICKEN_BABY",
        "baby_name": "Baby Chickens",
        "grown_id": "T3_FARM_CHICKEN_GROWN",
        "produce_id": "T3_EGG",
        "produce_name": "Hen Eggs",
        "produce_daily_yield": 2.0,
        "meat_id": "T3_MEAT",
        "meat_name": "Raw Chicken",
        "meat_yield": 20.0,
        "feed_daily": 10,
        "growth_hours": 22.0,
        "base_offspring_pct": 80.0,
        "nurtured_offspring_pct": 120.0,
        "base_focus_cost": 1000,
        "biome_city": "Fort Sterling",
    },
    "T4_FARM_GOAT": {
        "tier": 4,
        "name": "Goat",
        "baby_id": "T4_FARM_GOAT_BABY",
        "baby_name": "Kid",
        "grown_id": "T4_FARM_GOAT_GROWN",
        "produce_id": "T4_MILK",
        "produce_name": "Goat's Milk",
        "produce_daily_yield": 2.0,
        "meat_id": "T4_MEAT",
        "meat_name": "Raw Goat",
        "meat_yield": 20.0,
        "feed_daily": 10,
        "growth_hours": 22.0,
        "base_offspring_pct": 80.0,
        "nurtured_offspring_pct": 120.0,
        "base_focus_cost": 1000,
        "biome_city": "Bridgewatch",
    },
    "T5_FARM_GOOSE": {
        "tier": 5,
        "name": "Goose",
        "baby_id": "T5_FARM_GOOSE_BABY",
        "baby_name": "Gosling",
        "grown_id": "T5_FARM_GOOSE_GROWN",
        "produce_id": "T5_EGG",
        "produce_name": "Goose Eggs",
        "produce_daily_yield": 2.0,
        "meat_id": "T5_MEAT",
        "meat_name": "Raw Goose",
        "meat_yield": 20.0,
        "feed_daily": 10,
        "growth_hours": 22.0,
        "base_offspring_pct": 80.0,
        "nurtured_offspring_pct": 120.0,
        "base_focus_cost": 1000,
        "biome_city": "Lymhurst",
    },
    "T6_FARM_SHEEP": {
        "tier": 6,
        "name": "Sheep",
        "baby_id": "T6_FARM_SHEEP_BABY",
        "baby_name": "Lamb",
        "grown_id": "T6_FARM_SHEEP_GROWN",
        "produce_id": "T6_MILK",
        "produce_name": "Sheep's Milk",
        "produce_daily_yield": 2.0,
        "meat_id": "T6_MEAT",
        "meat_name": "Raw Mutton",
        "meat_yield": 20.0,
        "feed_daily": 10,
        "growth_hours": 22.0,
        "base_offspring_pct": 85.0,
        "nurtured_offspring_pct": 125.0,
        "base_focus_cost": 1000,
        "biome_city": "Fort Sterling",
    },
    "T7_FARM_PIG": {
        "tier": 7,
        "name": "Pig",
        "baby_id": "T7_FARM_PIG_BABY",
        "baby_name": "Piglet",
        "grown_id": "T7_FARM_PIG_GROWN",
        "produce_id": None,
        "produce_name": None,
        "produce_daily_yield": 0.0,
        "meat_id": "T7_MEAT",
        "meat_name": "Raw Pork",
        "meat_yield": 20.0,
        "feed_daily": 10,
        "growth_hours": 22.0,
        "base_offspring_pct": 90.0,
        "nurtured_offspring_pct": 130.0,
        "base_focus_cost": 1000,
        "biome_city": "Thetford",
    },
    "T8_FARM_COW": {
        "tier": 8,
        "name": "Cow",
        "baby_id": "T8_FARM_COW_BABY",
        "baby_name": "Calf",
        "grown_id": "T8_FARM_COW_GROWN",
        "produce_id": "T8_MILK",
        "produce_name": "Cow's Milk",
        "produce_daily_yield": 2.0,
        "meat_id": "T8_MEAT",
        "meat_name": "Raw Beef",
        "meat_yield": 20.0,
        "feed_daily": 10,
        "growth_hours": 22.0,
        "base_offspring_pct": 92.0,
        "nurtured_offspring_pct": 132.0,
        "base_focus_cost": 1000,
        "biome_city": "Martlock",
    },
}

# ═══════════════════════════════════════════════════════════════
# MOUNT RAISING & SADDLING ONTOLOGY
# Saddler Crafting: Baby -> Feed -> Saddling Materials -> Mount
# ═══════════════════════════════════════════════════════════════

MOUNTS: Dict[str, Dict[str, Any]] = {
    "T3_MOUNT_HORSE": {
        "tier": 3,
        "name": "Riding Horse (T3)",
        "baby_id": "T3_FARM_HORSE_BABY",
        "grown_id": "T3_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 1,
        "growth_hours": 22.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T3_LEATHER", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T4_MOUNT_HORSE": {
        "tier": 4,
        "name": "Riding Horse (T4)",
        "baby_id": "T4_FARM_HORSE_BABY",
        "grown_id": "T4_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 1,
        "growth_hours": 22.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T4_LEATHER", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T5_MOUNT_HORSE": {
        "tier": 5,
        "name": "Riding Horse (T5)",
        "baby_id": "T5_FARM_HORSE_BABY",
        "grown_id": "T5_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 2,
        "growth_hours": 44.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T5_LEATHER", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T6_MOUNT_HORSE": {
        "tier": 6,
        "name": "Riding Horse (T6)",
        "baby_id": "T6_FARM_HORSE_BABY",
        "grown_id": "T6_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 3,
        "growth_hours": 66.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T6_LEATHER", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T7_MOUNT_HORSE": {
        "tier": 7,
        "name": "Riding Horse (T7)",
        "baby_id": "T7_FARM_HORSE_BABY",
        "grown_id": "T7_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 4,
        "growth_hours": 88.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T7_LEATHER", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T8_MOUNT_HORSE": {
        "tier": 8,
        "name": "Riding Horse (T8)",
        "baby_id": "T8_FARM_HORSE_BABY",
        "grown_id": "T8_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 5,
        "growth_hours": 110.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T8_LEATHER", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T5_MOUNT_ARMORED_HORSE": {
        "tier": 5,
        "name": "Armored Horse (T5)",
        "baby_id": "T5_FARM_HORSE_BABY",
        "grown_id": "T5_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 2,
        "growth_hours": 44.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T5_CLOTH", "quantity": 10.0}, {"item_id": "T5_METALBAR", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T6_MOUNT_ARMORED_HORSE": {
        "tier": 6,
        "name": "Armored Horse (T6)",
        "baby_id": "T6_FARM_HORSE_BABY",
        "grown_id": "T6_FARM_HORSE_GROWN",
        "feed_daily": 10,
        "growth_days": 3,
        "growth_hours": 66.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T6_CLOTH", "quantity": 10.0}, {"item_id": "T6_METALBAR", "quantity": 20.0}],
        "biome_city": "Bridgewatch",
    },
    "T3_MOUNT_OX": {
        "tier": 3,
        "name": "Transport Ox (T3)",
        "baby_id": "T3_FARM_OX_BABY",
        "grown_id": "T3_FARM_OX_GROWN",
        "feed_daily": 10,
        "growth_days": 1,
        "growth_hours": 22.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T3_PLANKS", "quantity": 30.0}],
        "biome_city": "Martlock",
    },
    "T4_MOUNT_OX": {
        "tier": 4,
        "name": "Transport Ox (T4)",
        "baby_id": "T4_FARM_OX_BABY",
        "grown_id": "T4_FARM_OX_GROWN",
        "feed_daily": 10,
        "growth_days": 1,
        "growth_hours": 22.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T4_PLANKS", "quantity": 30.0}],
        "biome_city": "Martlock",
    },
    "T5_MOUNT_OX": {
        "tier": 5,
        "name": "Transport Ox (T5)",
        "baby_id": "T5_FARM_OX_BABY",
        "grown_id": "T5_FARM_OX_GROWN",
        "feed_daily": 10,
        "growth_days": 2,
        "growth_hours": 44.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T5_PLANKS", "quantity": 30.0}],
        "biome_city": "Martlock",
    },
    "T6_MOUNT_OX": {
        "tier": 6,
        "name": "Transport Ox (T6)",
        "baby_id": "T6_FARM_OX_BABY",
        "grown_id": "T6_FARM_OX_GROWN",
        "feed_daily": 10,
        "growth_days": 3,
        "growth_hours": 66.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T6_PLANKS", "quantity": 30.0}],
        "biome_city": "Martlock",
    },
    "T7_MOUNT_OX": {
        "tier": 7,
        "name": "Transport Ox (T7)",
        "baby_id": "T7_FARM_OX_BABY",
        "grown_id": "T7_FARM_OX_GROWN",
        "feed_daily": 10,
        "growth_days": 4,
        "growth_hours": 88.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T7_PLANKS", "quantity": 30.0}],
        "biome_city": "Martlock",
    },
    "T8_MOUNT_OX": {
        "tier": 8,
        "name": "Transport Ox (T8)",
        "baby_id": "T8_FARM_OX_BABY",
        "grown_id": "T8_FARM_OX_GROWN",
        "feed_daily": 10,
        "growth_days": 5,
        "growth_hours": 110.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T8_PLANKS", "quantity": 30.0}],
        "biome_city": "Martlock",
    },
    "T4_MOUNT_GIANTSTAG": {
        "tier": 4,
        "name": "Adept's Giant Stag",
        "baby_id": "T4_FARM_GIANTSTAG_BABY",
        "grown_id": "T4_FARM_GIANTSTAG_GROWN",
        "feed_daily": 10,
        "growth_days": 1,
        "growth_hours": 22.0,
        "feed_type": "crop",
        "saddling_ingredients": [{"item_id": "T4_LEATHER", "quantity": 20.0}],
        "biome_city": "Lymhurst",
    },
    "T5_MOUNT_COUGAR_KEEPER": {
        "tier": 5,
        "name": "Swiftclaw",
        "baby_id": "T5_FARM_COUGAR_BABY",
        "grown_id": "T5_FARM_COUGAR_GROWN",
        "feed_daily": 10,
        "growth_days": 2,
        "growth_hours": 44.0,
        "feed_type": "meat",
        "saddling_ingredients": [{"item_id": "T5_LEATHER", "quantity": 20.0}],
        "biome_city": None,
    },
    "T6_MOUNT_DIREWOLF": {
        "tier": 6,
        "name": "Direwolf",
        "baby_id": "T6_FARM_DIREWOLF_BABY",
        "grown_id": "T6_FARM_DIREWOLF_GROWN",
        "feed_daily": 10,
        "growth_days": 3,
        "growth_hours": 66.0,
        "feed_type": "meat",
        "saddling_ingredients": [{"item_id": "T6_LEATHER", "quantity": 20.0}],
        "biome_city": "Caerleon",
    },
}

# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS FOR BIOME & AGRICULTURAL PROFIT
# ═══════════════════════════════════════════════════════════════

def get_city_biome_farming_bonus(island_city: str, item_id: str) -> float:
    """
    Returns +10% (0.10) if the crop, herb, animal, or mount has a local production bonus in the given city.
    """
    if not island_city or not item_id:
        return 0.0

    clean_city = (
        island_city.replace("Personal Island (", "")
        .replace(")", "")
        .replace(" Island", "")
        .strip()
    )

    biome_data = CITY_ISLAND_BIOMES.get(clean_city)
    if not biome_data:
        return 0.0

    u = item_id.upper()
    all_bonus_items = (
        biome_data.get("crops", [])
        + biome_data.get("herbs", [])
        + biome_data.get("livestock", [])
        + biome_data.get("mounts", [])
    )

    # Check direct match or keyword match
    if item_id in all_bonus_items or any(k in u for k in all_bonus_items):
        return biome_data.get("bonus_yield_pct", 10.0) / 100.0

    return 0.0
