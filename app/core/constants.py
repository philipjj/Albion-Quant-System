"""
Constants for the Albion Quant Trading System.
Game mechanics, city data, transport routes, and item categories.
"""

# ═══════════════════════════════════════════════════════════════
# CITIES
# ═══════════════════════════════════════════════════════════════

ROYAL_SAFE_CITIES = [
    "Bridgewatch",
    "Martlock",
    "Lymhurst",
    "Fort Sterling",
    "Thetford",
]
ROYAL_CITIES = ROYAL_SAFE_CITIES

BLACK_MARKET_CITY = "Black Market"
CAERLEON = "Caerleon"
BRECILIEN = "Brecilien"

ALL_MARKET_CITIES = ROYAL_SAFE_CITIES + [CAERLEON, BRECILIEN]
ALL_CITIES_WITH_BM = ALL_MARKET_CITIES + [BLACK_MARKET_CITY]

# API location strings
CITY_API_NAMES = {
    "Bridgewatch": "Bridgewatch",
    "Martlock": "Martlock",
    "Lymhurst": "Lymhurst",
    "Fort Sterling": "Fort Sterling",
    "Thetford": "Thetford",
    "Caerleon": "Caerleon",
    "Brecilien": "Brecilien",
    "Black Market": "Black Market",
}

# ═══════════════════════════════════════════════════════════════
# CITY CRAFTING BONUSES (Official Albion Online Resource Return Rate Bonuses)
# ═══════════════════════════════════════════════════════════════

CITY_CRAFTING_BONUSES = {
    "Bridgewatch": {
        "bonus_categories": [
            "crossbow", "dagger", "cursed_staff", "curse_staff",
            "plate_armor", "armor_plate",  # Chest piece only
            "cloth_shoes", "cloth_boots", "shoes_cloth"  # Sandals
        ],
        "refining_bonus": ["rock", "stone", "block", "stoneblock"],
    },
    "Martlock": {
        "bonus_categories": [
            "axe", "quarterstaff", "frost_staff",
            "plate_shoes", "plate_boots", "shoes_plate",  # Boots
            "offhand", "off_hand", "shield", "tome", "torch", "horn", "orb", "totem", "book"  # All off-hands
        ],
        "refining_bonus": ["hide", "leather"],
    },
    "Lymhurst": {
        "bonus_categories": [
            "sword", "bow", "arcane_staff",
            "leather_helmet", "leather_hood", "head_leather",  # Hood
            "leather_shoes", "leather_boots", "shoes_leather"  # Shoes
        ],
        "refining_bonus": ["fiber", "cloth"],
    },
    "Fort Sterling": {
        "bonus_categories": [
            "hammer", "spear", "holy_staff",
            "plate_helmet", "plate_headgear", "head_plate",  # Helmet
            "cloth_armor", "cloth_robe", "armor_cloth"  # Robe
        ],
        "refining_bonus": ["wood", "planks"],
    },
    "Thetford": {
        "bonus_categories": [
            "mace", "nature_staff", "fire_staff",
            "cloth_helmet", "cloth_headgear", "cloth_cowl", "head_cloth",  # Cowl
            "leather_armor", "leather_jacket", "armor_leather"  # Jacket
        ],
        "refining_bonus": ["ore", "bar", "metalbar"],
    },
    "Caerleon": {
        "bonus_categories": [
            "cooked_food", "food", "meal", "soup", "stew", "pie", "omelette", "roast", "sandwich",
            "war_gloves", "shapeshifter_staff", "shapeshifter",
            "gathering_gear", "gathering_tool", "tool"
        ],
        "refining_bonus": [],
    },
    "Brecilien": {
        "bonus_categories": ["potion", "potions", "bag", "cape", "capes"],
        "refining_bonus": [],
    },
}

# ═══════════════════════════════════════════════════════════════
# CITY ISLAND BIOME FARMING & BREEDING BONUSES (+10% Yield)
# Official Albion Online Foundations / Wild Blood Biome Specializations
# ═══════════════════════════════════════════════════════════════

CITY_ISLAND_FARMING_BONUSES = {
    "Bridgewatch": {
        "crops": ["_BEAN", "_CORN"],
        "herbs": ["_TEASEL"],
        "animals": ["_GOAT", "_HORSE", "_MILK_GOAT", "T4_MILK", "T4_MEAT"],
        "bonus_yield_pct": 10.0,
    },
    "Fort Sterling": {
        "crops": ["_TURNIP"],
        "herbs": ["_YARROW"],
        "animals": ["_CHICKEN", "_SHEEP", "_EGG", "_MILK_SHEEP", "T3_EGG", "T6_MILK", "T3_MEAT", "T6_MEAT", "_RAM"],
        "bonus_yield_pct": 10.0,
    },
    "Lymhurst": {
        "crops": ["_CARROT", "_PUMPKIN"],
        "herbs": ["_BURDOCK"],
        "animals": ["_GOOSE", "_GIANTSTAG", "_EGG_GOOSE", "T5_EGG", "T5_MEAT", "_HOUND"],
        "bonus_yield_pct": 10.0,
    },
    "Martlock": {
        "crops": ["_WHEAT", "_POTATO"],
        "herbs": ["_FOXGLOVE"],
        "animals": ["_COW", "_OX", "_MILK_COW", "T8_MILK", "T8_MEAT"],
        "bonus_yield_pct": 10.0,
    },
    "Thetford": {
        "crops": ["_CABBAGE"],
        "herbs": ["_AGARIC", "_MULLEIN"],
        "animals": ["_PIG", "T7_MEAT", "T7_FARM_PIG", "_TOAD", "_SALAMANDER"],
        "bonus_yield_pct": 10.0,
    },
    "Caerleon": {
        "crops": [],
        "herbs": ["_COMFREY", "_TEASEL", "_MULLEIN"],
        "animals": ["_WOLF", "_DIREWOLF", "_SHADOWWOLF"],
        "bonus_yield_pct": 10.0,
    },
    "Brecilien": {
        "crops": ["_CARROT", "_BEAN", "_WHEAT", "_TURNIP", "_CABBAGE", "_POTATO", "_CORN", "_PUMPKIN"],
        "herbs": ["_AGARIC", "_COMFREY", "_BURDOCK", "_TEASEL", "_FOXGLOVE", "_YARROW", "_MULLEIN"],
        "animals": ["_OWL"],
        "bonus_yield_pct": 10.0,
    },
}

# ═══════════════════════════════════════════════════════════════
# RESOURCE RETURN RATES (RRR) — Albion Online Mathematical Formulas
# RRR = LPB / (1.0 + LPB)  where LPB = Local Production Bonus
# ═══════════════════════════════════════════════════════════════

def calculate_rrr(lpb: float) -> float:
    """
    Derives Resource Return Rate (RRR) from Local Production Bonus (LPB).
    Formula: RRR = LPB / (1 + LPB)
    """
    if lpb <= 0:
        return 0.0
    return round(lpb / (1.0 + lpb), 5)


# Local Production Bonuses (LPB)
BASE_PRODUCTION_BONUS = 0.18        # 18% base LPB in Royal Cities
CRAFTING_SPECIALTY_LPB = 0.15       # +15% LPB for matching craft category
REFINING_SPECIALTY_LPB = 0.40       # +40% LPB for matching refining resource
FOCUS_CRAFTING_LPB = 0.59           # +59% LPB with Focus

# Derived RRR Constants
BASE_RESOURCE_RETURN_RATE = calculate_rrr(BASE_PRODUCTION_BONUS)  # 0.15254 (15.25%)
CITY_BONUS_RESOURCE_RETURN_RATE = calculate_rrr(BASE_PRODUCTION_BONUS + CRAFTING_SPECIALTY_LPB)  # 0.24812 (24.81%)
REFINING_BONUS_RRR = calculate_rrr(BASE_PRODUCTION_BONUS + REFINING_SPECIALTY_LPB)  # 0.36709 (36.71%)

# Focus RRR Constants
FOCUS_RESOURCE_RETURN_RATE = calculate_rrr(BASE_PRODUCTION_BONUS + FOCUS_CRAFTING_LPB)  # 0.43503 (43.50%)
FOCUS_CITY_BONUS_RRR = calculate_rrr(BASE_PRODUCTION_BONUS + CRAFTING_SPECIALTY_LPB + FOCUS_CRAFTING_LPB)  # 0.47917 (47.92%)
REFINING_FOCUS_RRR = calculate_rrr(BASE_PRODUCTION_BONUS + REFINING_SPECIALTY_LPB + FOCUS_CRAFTING_LPB)  # 0.53917 (53.92%)

# Islands & Hideouts
ISLAND_RESOURCE_RETURN_RATE = 0.00
ISLAND_FOCUS_RRR = calculate_rrr(FOCUS_CRAFTING_LPB)  # 0.37107 (37.11%)

# ═══════════════════════════════════════════════════════════════
# MARKET MECHANICS
# ═══════════════════════════════════════════════════════════════

SETUP_FEE = 0.025  # 2.5% setup fee (upfront listing)
PREMIUM_SALES_TAX = 0.04  # 4% sales tax (Premium)
NON_PREMIUM_SALES_TAX = 0.08  # 8% sales tax (Non-Premium)

# ═══════════════════════════════════════════════════════════════
# TRANSPORT DISTANCES
# ═══════════════════════════════════════════════════════════════

TRANSPORT_DISTANCES = {
    ("Bridgewatch", "Martlock"): 5,
    ("Bridgewatch", "Lymhurst"): 4,
    ("Bridgewatch", "Fort Sterling"): 6,
    ("Bridgewatch", "Thetford"): 5,
    ("Bridgewatch", "Caerleon"): 3,
    ("Bridgewatch", "Brecilien"): 6,
    ("Martlock", "Lymhurst"): 5,
    ("Martlock", "Fort Sterling"): 4,
    ("Martlock", "Thetford"): 6,
    ("Martlock", "Caerleon"): 3,
    ("Martlock", "Brecilien"): 6,
    ("Lymhurst", "Fort Sterling"): 5,
    ("Lymhurst", "Thetford"): 4,
    ("Lymhurst", "Caerleon"): 3,
    ("Lymhurst", "Brecilien"): 6,
    ("Fort Sterling", "Thetford"): 5,
    ("Fort Sterling", "Caerleon"): 3,
    ("Fort Sterling", "Brecilien"): 6,
    ("Thetford", "Caerleon"): 3,
    ("Thetford", "Brecilien"): 6,
    ("Caerleon", "Brecilien"): 4,
}


def get_distance(city_a: str, city_b: str) -> int:
    if city_a == city_b:
        return 0
    return TRANSPORT_DISTANCES.get((city_a, city_b), TRANSPORT_DISTANCES.get((city_b, city_a), 5))


DANGEROUS_ROUTES = {
    ("Bridgewatch", "Caerleon"),
    ("Caerleon", "Bridgewatch"),
    ("Martlock", "Caerleon"),
    ("Caerleon", "Martlock"),
    ("Lymhurst", "Caerleon"),
    ("Caerleon", "Lymhurst"),
    ("Fort Sterling", "Caerleon"),
    ("Caerleon", "Fort Sterling"),
    ("Thetford", "Caerleon"),
    ("Caerleon", "Thetford"),
    ("Bridgewatch", "Black Market"),
    ("Black Market", "Bridgewatch"),
    ("Martlock", "Black Market"),
    ("Black Market", "Martlock"),
    ("Lymhurst", "Black Market"),
    ("Black Market", "Lymhurst"),
    ("Fort Sterling", "Black Market"),
    ("Black Market", "Fort Sterling"),
    ("Thetford", "Black Market"),
    ("Black Market", "Thetford"),
    ("Brecilien", "Black Market"),
    ("Black Market", "Brecilien"),
    ("Brecilien", "Caerleon"),
    ("Caerleon", "Brecilien"),
}


def is_route_dangerous(city_a: str, city_b: str) -> bool:
    """Checks whether the travel route between two cities passes through red/black lethal zones."""
    return (city_a, city_b) in DANGEROUS_ROUTES or (city_b, city_a) in DANGEROUS_ROUTES


# ═══════════════════════════════════════════════════════════════
# JOURNALS - Updated May 2026
# ═══════════════════════════════════════════════════════════════
# GAME MECHANICS HELPERS
# ═══════════════════════════════════════════════════════════════

STATION_FEE_CONSTANT = 0.1125  # Updated May 2026 from 0.11
DEFAULT_STATION_FEE = 500  # Default percentage tax (e.g. 500%)


def calculate_station_fee(item_value: float, station_tax_percent: float) -> float:
    return (item_value * STATION_FEE_CONSTANT * station_tax_percent) / 100.0


# ═══════════════════════════════════════════════════════════════
# ITEM DATA
# ═══════════════════════════════════════════════════════════════

QUALITY_NAMES = {1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
TIERS = [4, 5, 6, 7, 8]
ENCHANTMENTS = [0, 1, 2, 3]


def item_weight(item_id: str) -> float:
    """
    Returns estimated weight in kg based on item slot/category if missing from DB metadata.
    """
    if not item_id:
        return 1.0
    item_upper = item_id.upper().split("@")[0]

    # 2H Weapons -> ~4.5 - 6.0 kg
    if any(k in item_upper for k in ["2H_", "_2H", "BOW", "WARBOW", "LONGBOW", "CROSSBOW", "STAFF", "CLAYMORE", "HALBERD", "SCYTHE", "POLEHAMMER"]):
        return 5.0
    # 1H Weapons -> ~2.5 - 3.5 kg
    if any(k in item_upper for k in ["MAIN_", "1H_", "SWORD", "AXE", "MACE", "HAMMER", "DAGGER", "SPEAR"]):
        return 3.0
    # Chest Armors -> ~7.0 - 10.0 kg for Plate, 5.0 for Leather, 3.0 for Cloth
    if "ARMOR_PLATE" in item_upper:
        return 9.0
    if "ARMOR_LEATHER" in item_upper or "JACKET" in item_upper:
        return 5.0
    if "ARMOR_CLOTH" in item_upper or "ROBE" in item_upper:
        return 3.0
    # Helmets / Hoods / Cowls -> ~1.5 - 2.5 kg
    if any(k in item_upper for k in ["HEAD_", "HELMET", "HOOD", "COWL"]):
        return 2.0
    # Boots / Shoes -> ~1.5 - 2.5 kg
    if any(k in item_upper for k in ["SHOES", "BOOTS"]):
        return 2.0
    # Off-hands / Shields -> ~2.0 - 4.0 kg
    if any(k in item_upper for k in ["OFF_", "SHIELD", "BOOK", "ORB", "TORCH", "TOTEM"]):
        return 2.5
    # Bags & Capes -> ~1.0 - 2.0 kg
    if any(k in item_upper for k in ["BAG", "CAPE"]):
        return 1.5
    # Raw / Refined Resources
    if any(k in item_upper for k in ["_PLANKS", "_BAR", "_LEATHER", "_CLOTH", "_STONE", "_BLOCK", "_ORE", "_WOOD", "_HIDE", "_FIBER", "_ROCK"]):
        return 1.0
    return 1.5
