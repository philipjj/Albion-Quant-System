"""
Constants for the Albion Quant Trading System.
Game mechanics, city data, transport routes, and item categories.
"""

# ═══════════════════════════════════════════════════════════════
# CITIES
# ═══════════════════════════════════════════════════════════════

ROYAL_CITIES = [
    "Bridgewatch",
    "Martlock",
    "Lymhurst",
    "Fort Sterling",
    "Thetford",
]

BLACK_MARKET_CITY = "Black Market"
CAERLEON = "Caerleon"

ALL_MARKET_CITIES = ROYAL_CITIES + [CAERLEON]
ALL_CITIES_WITH_BM = ALL_MARKET_CITIES + [BLACK_MARKET_CITY]

# API location strings
CITY_API_NAMES = {
    "Bridgewatch": "Bridgewatch",
    "Martlock": "Martlock",
    "Lymhurst": "Lymhurst",
    "Fort Sterling": "Fort Sterling",
    "Thetford": "Thetford",
    "Caerleon": "Caerleon",
    "Black Market": "Black Market",
}

# ═══════════════════════════════════════════════════════════════
# CITY CRAFTING BONUSES (resource return rate bonuses)
# ═══════════════════════════════════════════════════════════════

CITY_CRAFTING_BONUSES = {
    "Bridgewatch": {
        "bonus_categories": ["crossbow", "dagger", "curse_staff", "torch", "shield"],
        "refining_bonus": ["rock", "ore"],
    },
    "Martlock": {
        "bonus_categories": ["axe", "quarterstaff", "frost_staff", "off_hand"],
        "refining_bonus": ["hide", "rock"],
    },
    "Lymhurst": {
        "bonus_categories": ["sword", "bow", "fire_staff", "cape"],
        "refining_bonus": ["wood", "fiber"],
    },
    "Fort Sterling": {
        "bonus_categories": ["hammer", "spear", "holy_staff", "helmet", "armor"],
        "refining_bonus": ["wood", "ore"],
    },
    "Thetford": {
        "bonus_categories": ["mace", "nature_staff", "arcane_staff", "shoes"],
        "refining_bonus": ["fiber", "hide"],
    },
}

# ═══════════════════════════════════════════════════════════════
# RESOURCE RETURN RATES (RRR)
# ═══════════════════════════════════════════════════════════════

# Royal City RRR
RRR_ROYAL_BASE = 0.152
RRR_ROYAL_BONUS = 0.248
RRR_ROYAL_FOCUS = 0.435  # Base + Focus (Royal)
RRR_ROYAL_BONUS_FOCUS = 0.479  # Bonus + Focus (Royal)

# Refining RRR
RRR_REFINING_BASE = 0.152
RRR_REFINING_BONUS = 0.367
RRR_REFINING_BONUS_FOCUS = 0.539

# Islands & Hideouts (Varies by tier and quality)
RRR_ISLAND_BASE = 0.00
RRR_ISLAND_FOCUS = 0.37

# ═══════════════════════════════════════════════════════════════
# TRANSPORT DISTANCES (relative units, higher = more dangerous)
# ═══════════════════════════════════════════════════════════════

TRANSPORT_DISTANCES = {
    ("Bridgewatch", "Martlock"): 5,
    ("Bridgewatch", "Lymhurst"): 4,
    ("Bridgewatch", "Fort Sterling"): 6,
    ("Bridgewatch", "Thetford"): 5,
    ("Bridgewatch", "Caerleon"): 3,
    ("Martlock", "Lymhurst"): 5,
    ("Martlock", "Fort Sterling"): 4,
    ("Martlock", "Thetford"): 6,
    ("Martlock", "Caerleon"): 3,
    ("Lymhurst", "Fort Sterling"): 5,
    ("Lymhurst", "Thetford"): 4,
    ("Lymhurst", "Caerleon"): 3,
    ("Fort Sterling", "Thetford"): 5,
    ("Fort Sterling", "Caerleon"): 3,
    ("Thetford", "Caerleon"): 3,
}


def get_distance(city_a: str, city_b: str) -> int:
    """Get transport distance between two cities (symmetric)."""
    if city_a == city_b:
        return 0
    return TRANSPORT_DISTANCES.get(
        (city_a, city_b),
        TRANSPORT_DISTANCES.get((city_b, city_a), 5),
    )


# ═══════════════════════════════════════════════════════════════
# RISK FACTORS
# ═══════════════════════════════════════════════════════════════

# Base risk per zone type
ZONE_RISK = {
    "blue": 0.01,
    "yellow": 0.05,
    "red": 0.15,
    "black": 0.35,
}

# Routes through red/black zones
DANGEROUS_ROUTES = {
    ("Bridgewatch", "Caerleon"),
    ("Martlock", "Caerleon"),
    ("Lymhurst", "Caerleon"),
    ("Fort Sterling", "Caerleon"),
    ("Thetford", "Caerleon"),
}

# ═══════════════════════════════════════════════════════════════
# MARKET MECHANICS
# ═══════════════════════════════════════════════════════════════

SETUP_FEE = 0.025  # 2.5% per order
PREMIUM_SALES_TAX = 0.04  # 4% with premium
NON_PREMIUM_SALES_TAX = 0.08  # 8% without premium

# Resource return rate (base, without focus)
BASE_RESOURCE_RETURN_RATE = RRR_ROYAL_BASE

# City Bonus RRR (without focus)
CITY_BONUS_RESOURCE_RETURN_RATE = RRR_ROYAL_BONUS

# With focus (City Bonus + Focus)
FOCUS_RESOURCE_RETURN_RATE = RRR_ROYAL_BONUS_FOCUS

# Refining Specific RRR
REFINING_BONUS_RESOURCE_RETURN_RATE = RRR_REFINING_BONUS
REFINING_FOCUS_RESOURCE_RETURN_RATE = RRR_REFINING_BONUS_FOCUS

# Default crafting station fee per 100 nutrition
DEFAULT_STATION_FEE = 1200  # silver per 100 nutrition (2026 average)

# ═══════════════════════════════════════════════════════════════
# ITEM CATEGORIES
# ═══════════════════════════════════════════════════════════════

EQUIPMENT_CATEGORIES = [
    "weapon",
    "armor",
    "offhand",
    "cape",
    "bag",
    "mount",
    "food",
    "potion",
    "accessory",
]

RESOURCE_CATEGORIES = [
    "wood",
    "ore",
    "fiber",
    "hide",
    "rock",
]

# ═══════════════════════════════════════════════════════════════
# QUALITY LEVELS
# ═══════════════════════════════════════════════════════════════

QUALITY_NAMES = {
    1: "Normal",
    2: "Good",
    3: "Outstanding",
    4: "Excellent",
    5: "Masterpiece",
}

# ═══════════════════════════════════════════════════════════════
# JOURNALS
# ═══════════════════════════════════════════════════════════════

JOURNAL_MAPPING = {
    "armor": "BLACKSMITH",
    "helmet": "BLACKSMITH",
    "shoes": "BLACKSMITH",
    "weapon": "BLACKSMITH",  # Simplification, some are fletcher/imbuer
    "sword": "BLACKSMITH",
    "axe": "BLACKSMITH",
    "mace": "BLACKSMITH",
    "hammer": "BLACKSMITH",
    "crossbow": "BLACKSMITH",
    "shield": "BLACKSMITH",
    "bow": "FLETCHER",
    "dagger": "FLETCHER",
    "spear": "FLETCHER",
    "nature_staff": "FLETCHER",
    "torch": "FLETCHER",
    "fire_staff": "IMBUER",
    "holy_staff": "IMBUER",
    "arcane_staff": "IMBUER",
    "frost_staff": "IMBUER",
    "curse_staff": "IMBUER",
    "off_hand": "IMBUER",
    "furniture": "TINKER",
    "tool": "TINKER",
    "cape": "TINKER",
    "bag": "TINKER",
}

def get_journal_id(item_category: str, tier: int) -> str | None:
    """Get the specific journal item ID (e.g., T4_JOURNAL_BLACKSMITH_EMPTY)."""
    base = JOURNAL_MAPPING.get(item_category.lower())
    if not base:
        return None
    return f"T{tier}_JOURNAL_{base}_EMPTY"

# ═══════════════════════════════════════════════════════════════
# GAME MECHANICS HELPERS
# ═══════════════════════════════════════════════════════════════

def calculate_station_fee(item_value: float, station_tax: float) -> float:
    """
    Calculate the silver fee at a crafting station.
    The formula is: (ItemValue * 0.11 * StationTax) / 100
    Note: 0.11 is a game constant for nutrition to silver conversion.
    """
    return (item_value * 0.11 * station_tax) / 100.0

# ═══════════════════════════════════════════════════════════════
# TIERS
# ═══════════════════════════════════════════════════════════════

TIERS = [4, 5, 6, 7, 8]
ENCHANTMENTS = [0, 1, 2, 3]
