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
# RESOURCE RETURN RATES (RRR) - Updated May 2026
# ═══════════════════════════════════════════════════════════════

# Royal City RRR
BASE_RESOURCE_RETURN_RATE = 0.18        # Was 0.152
CITY_BONUS_RESOURCE_RETURN_RATE = 0.33  # Was 0.248
FOCUS_RESOURCE_RETURN_RATE = 0.48       # Base + Focus (Royal)
FOCUS_CITY_BONUS_RRR = 0.58             # Bonus + Focus (Royal)

# Refining RRR
REFINING_BASE_RRR = 0.18
REFINING_BONUS_RRR = 0.367
REFINING_FOCUS_RRR = 0.539

# Islands & Hideouts
ISLAND_RESOURCE_RETURN_RATE = 0.00
ISLAND_FOCUS_RRR = 0.37

# ═══════════════════════════════════════════════════════════════
# MARKET MECHANICS - Updated May 2026
# ═══════════════════════════════════════════════════════════════

SETUP_FEE = 0.025  # 2.5% setup fee (upfront)
PREMIUM_SALES_TAX = 0.04  # 4% sales tax
NON_PREMIUM_SALES_TAX = 0.08  # 8% sales tax

# ═══════════════════════════════════════════════════════════════
# TRANSPORT DISTANCES
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
    if city_a == city_b: return 0
    return TRANSPORT_DISTANCES.get((city_a, city_b), TRANSPORT_DISTANCES.get((city_b, city_a), 5))

DANGEROUS_ROUTES = {
    ("Bridgewatch", "Caerleon"), ("Martlock", "Caerleon"), ("Lymhurst", "Caerleon"),
    ("Fort Sterling", "Caerleon"), ("Thetford", "Caerleon"),
    ("Bridgewatch", "Black Market"), ("Martlock", "Black Market"), ("Lymhurst", "Black Market"),
    ("Fort Sterling", "Black Market"), ("Thetford", "Black Market"),
}

# ═══════════════════════════════════════════════════════════════
# JOURNALS - Updated May 2026
# ═══════════════════════════════════════════════════════════════

JOURNAL_MAPPING = {
    "armor": "BLACKSMITH", "helmet": "BLACKSMITH", "shoes": "BLACKSMITH",
    "weapon": "BLACKSMITH", "sword": "BLACKSMITH", "axe": "BLACKSMITH",
    "mace": "BLACKSMITH", "hammer": "BLACKSMITH", "crossbow": "BLACKSMITH",
    "shield": "BLACKSMITH", "bow": "FLETCHER", "dagger": "FLETCHER",
    "spear": "FLETCHER", "nature_staff": "FLETCHER", "torch": "FLETCHER",
    "fire_staff": "IMBUER", "holy_staff": "IMBUER", "arcane_staff": "IMBUER",
    "frost_staff": "IMBUER", "curse_staff": "IMBUER", "off_hand": "IMBUER",
    "furniture": "TINKER", "tool": "TINKER", "cape": "TINKER", "bag": "TINKER",
}

JOURNAL_FAME_REQUIRED = {4: 3600, 5: 7200, 6: 14400, 7: 28800, 8: 57600}
JOURNAL_YIELD_MULTIPLIER = 1.5

def get_journal_id(item_category: str, tier: int) -> str | None:
    base = JOURNAL_MAPPING.get(item_category.lower())
    if not base: return None
    return f"T{tier}_JOURNAL_{base}_EMPTY"

# ═══════════════════════════════════════════════════════════════
# GAME MECHANICS HELPERS
# ═══════════════════════════════════════════════════════════════

STATION_FEE_CONSTANT = 0.1125  # Updated May 2026 from 0.11
DEFAULT_STATION_FEE = 500  # Default percentage tax (e.g. 500%)

def calculate_station_fee(item_value: float, station_tax_percent: float) -> float:
    return (item_value * STATION_FEE_CONSTANT * station_tax_percent) / 100.0

# ═══════════════════════════════════════════════════════════════
# PRICE SANITY & OUTLIER DETECTION
# ═══════════════════════════════════════════════════════════════

def is_price_sane(price: float, item_value: float) -> bool:
    """
    Detect market manipulation, trolling, or API glitches.
    Uses ItemValue as an anchor for realism.
    """
    if price <= 0: return False
    if price > 500_000_000: return False # Hard cap for all items
    
    if item_value <= 0:
        # For items with missing metadata, use a conservative absolute cap
        return price < 5_000_000 
    
    # 2026 Economics: Realistic prices are usually 10x - 1000x ItemValue.
    # A T3 Horse (IV=112) @ 85M is ~750,000x -> Discard.
    # A rare artifact might be 2000x. We use 5000x as a safe threshold.
    ratio = price / item_value
    return ratio < 5000

# ═══════════════════════════════════════════════════════════════
# ITEM DATA
# ═══════════════════════════════════════════════════════════════

QUALITY_NAMES = {1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
TIERS = [4, 5, 6, 7, 8]
ENCHANTMENTS = [0, 1, 2, 3]
