"""
Elite Tier-Based Market Freshness & Materials Synchronization Engine
====================================================================
Precision-calibrated age limits and multi-leg synchronization across all Albion Online items.

Features:
1. Tier × Enchant progressive freshness ladders for raw/refined materials, enchanting materials,
   artifacts, equipment, consumables, and specialty goods.
2. Multi-Leg Desynchronization Guard (calculates time delta between input costs & finished product revenue).
3. Transport Route Travel-Time Expiration Buffers.
4. Continuous volume/velocity scaling to prevent phantom profits on high-turnover commodities.
5. Dynamic tier-aware scoring half-lives.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence

from app.core.logging import log


def safe_int(val, default: int = 0) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════════════
# TIER × ENCHANT FRESHNESS LADDERS (seconds)
# ═══════════════════════════════════════════════════════════════

# Raw / Refined Crafting Materials (Ore, Bar, Hide, Leather, Fiber, Cloth, Wood, Planks, Rock, Stoneblock)
# Calibrated for realistic Albion online market activity and liquidity
MATERIAL_AGE_LIMITS = {
    (2, 0): 43_200,    # T2.0: 12.0h
    (3, 0): 43_200,    # T3.0: 12.0h
    (4, 0): 28_800,    # T4.0: 8.0h
    (4, 1): 43_200,    # T4.1: 12.0h
    (4, 2): 57_600,    # T4.2: 16.0h
    (4, 3): 86_400,    # T4.3: 24.0h
    (5, 0): 36_000,    # T5.0: 10.0h
    (5, 1): 50_400,    # T5.1: 14.0h
    (5, 2): 86_400,    # T5.2: 24.0h
    (5, 3): 129_600,   # T5.3: 36.0h
    (6, 0): 43_200,    # T6.0: 12.0h
    (6, 1): 64_800,    # T6.1: 18.0h
    (6, 2): 100_800,   # T6.2: 28.0h
    (6, 3): 172_800,   # T6.3: 48.0h
    (7, 0): 57_600,    # T7.0: 16.0h
    (7, 1): 86_400,    # T7.1: 24.0h
    (7, 2): 172_800,   # T7.2: 48.0h
    (7, 3): 259_200,   # T7.3: 72.0h
    (8, 0): 86_400,    # T8.0: 24.0h
    (8, 1): 172_800,   # T8.1: 48.0h
    (8, 2): 259_200,   # T8.2: 72.0h
    (8, 3): 432_000,   # T8.3: 120.0h
    (8, 4): 622_080,   # T8.4: 172.8h — Whale tier, extremely illiquid
}

# Enchantment Materials (Runes, Souls, Relics, Avalonian Shards)
# High-volume commodities (Runes/Souls) have strict freshness (1.5h-2.0h) to protect multi-stack profit margins
ENCHANT_MATERIAL_AGE_LIMITS = {
    # Runes (high volume commodity)
    (4, "RUNE"): 5_400,       # 1.5h
    (5, "RUNE"): 5_400,       # 1.5h
    (6, "RUNE"): 7_200,       # 2.0h
    (7, "RUNE"): 7_200,       # 2.0h
    (8, "RUNE"): 10_800,      # 3.0h
    # Souls (mid volume commodity)
    (4, "SOUL"): 5_400,       # 1.5h
    (5, "SOUL"): 5_400,       # 1.5h
    (6, "SOUL"): 7_200,       # 2.0h
    (7, "SOUL"): 7_200,       # 2.0h
    (8, "SOUL"): 14_400,      # 4.0h
    # Relics (low volume, expensive)
    (4, "RELIC"): 7_200,      # 2.0h
    (5, "RELIC"): 7_200,      # 2.0h
    (6, "RELIC"): 10_800,     # 3.0h
    (7, "RELIC"): 21_600,     # 6.0h
    (8, "RELIC"): 43_200,     # 12.0h
    # Avalonian Shards & Tokens
    (4, "SHARD"): 14_400,     # 4.0h
    (5, "SHARD"): 14_400,     # 4.0h
    (6, "SHARD"): 21_600,     # 6.0h
    (7, "SHARD"): 43_200,     # 12.0h
    (8, "SHARD"): 86_400,     # 24.0h
}

# Crafting Artifacts (Rune, Soul, Relic, Hell & Avalonian Artifacts)
ARTIFACT_AGE_LIMITS = {
    (4, 0): 7_200,      # 2.0h
    (5, 0): 10_800,     # 3.0h
    (6, 0): 14_400,     # 4.0h
    (7, 0): 21_600,     # 6.0h
    (8, 0): 43_200,     # 12.0h
}

# Equipment / Finished Goods (weapons, armor, off-hands, bags, capes)
# Base items and low-tier gear have fast freshness; high tier/enchantments scale progressively
EQUIPMENT_AGE_LIMITS = {
    (4, 0): 7_200,      # 2.0h
    (4, 1): 10_800,     # 3.0h
    (4, 2): 14_400,     # 4.0h
    (4, 3): 21_600,     # 6.0h
    (5, 0): 9_000,      # 2.5h
    (5, 1): 14_400,     # 4.0h
    (5, 2): 21_600,     # 6.0h
    (5, 3): 28_800,     # 8.0h
    (6, 0): 10_800,     # 3.0h
    (6, 1): 18_000,     # 5.0h
    (6, 2): 28_800,     # 8.0h
    (6, 3): 43_200,     # 12.0h
    (7, 0): 14_400,     # 4.0h
    (7, 1): 21_600,     # 6.0h
    (7, 2): 43_200,     # 12.0h
    (7, 3): 86_400,     # 24.0h
    (8, 0): 21_600,     # 6.0h
    (8, 1): 43_200,     # 12.0h
    (8, 2): 86_400,     # 24.0h
    (8, 3): 172_800,    # 48.0h (2 days)
    (8, 4): 345_600,    # 96.0h (4 days)
}

# Consumables (Food, Potions)
CONSUMABLE_AGE_LIMITS = {
    (1, 0): 3_600,      # 1.0h
    (2, 0): 3_600,      # 1.0h
    (3, 0): 3_600,      # 1.0h
    (4, 0): 3_600,      # 1.0h   — High volume staples
    (4, 1): 5_400,      # 1.5h
    (4, 2): 7_200,      # 2.0h
    (4, 3): 10_800,     # 3.0h
    (5, 0): 5_400,      # 1.5h
    (5, 1): 7_200,      # 2.0h
    (5, 2): 10_800,     # 3.0h
    (5, 3): 14_400,     # 4.0h
    (6, 0): 7_200,      # 2.0h
    (6, 1): 10_800,     # 3.0h
    (6, 2): 14_400,     # 4.0h
    (6, 3): 21_600,     # 6.0h
    (7, 0): 14_400,     # 4.0h
    (7, 1): 21_600,     # 6.0h
    (7, 2): 28_800,     # 8.0h
    (7, 3): 43_200,     # 12.0h
    (8, 0): 21_600,     # 6.0h
    (8, 1): 43_200,     # 12.0h
    (8, 2): 43_200,     # 12.0h
    (8, 3): 86_400,     # 24.0h
}

# Mounts, Journals, Gathering Gear, Furniture, Trophies
SPECIALTY_AGE_LIMITS = {
    (1, 0): 14_400,     # 4.0h
    (2, 0): 14_400,     # 4.0h
    (3, 0): 14_400,     # 4.0h
    (4, 0): 14_400,     # 4.0h
    (4, 1): 21_600,     # 6.0h
    (4, 2): 28_800,     # 8.0h
    (4, 3): 43_200,     # 12.0h
    (5, 0): 21_600,     # 6.0h
    (5, 1): 28_800,     # 8.0h
    (5, 2): 43_200,     # 12.0h
    (5, 3): 86_400,     # 24.0h
    (6, 0): 43_200,     # 12.0h
    (6, 1): 86_400,     # 24.0h
    (6, 2): 86_400,     # 24.0h
    (6, 3): 172_800,    # 48.0h
    (7, 0): 86_400,     # 24.0h
    (7, 1): 172_800,    # 48.0h
    (7, 2): 172_800,    # 48.0h
    (7, 3): 259_200,    # 72.0h
    (8, 0): 172_800,    # 48.0h
    (8, 1): 259_200,    # 72.0h
    (8, 2): 345_600,    # 96.0h
    (8, 3): 604_800,    # 168.0h (7 days)
    (8, 4): 604_800,    # 168.0h (7 days)
}

# Market Making — tight limits since MM depends on live spread capture
MARKET_MAKING_AGE_LIMITS = {
    (4, 0): 3_600,      # 1.0h
    (4, 1): 5_400,      # 1.5h
    (4, 2): 7_200,      # 2.0h
    (4, 3): 10_800,     # 3.0h
    (5, 0): 5_400,      # 1.5h
    (5, 1): 7_200,      # 2.0h
    (5, 2): 10_800,     # 3.0h
    (5, 3): 14_400,     # 4.0h
    (6, 0): 7_200,      # 2.0h
    (6, 1): 10_800,     # 3.0h
    (6, 2): 14_400,     # 4.0h
    (6, 3): 21_600,     # 6.0h
    (7, 0): 10_800,     # 3.0h
    (7, 1): 14_400,     # 4.0h
    (7, 2): 21_600,     # 6.0h
    (7, 3): 43_200,     # 12.0h
    (8, 0): 14_400,     # 4.0h
    (8, 1): 21_600,     # 6.0h
    (8, 2): 43_200,     # 12.0h
    (8, 3): 86_400,     # 24.0h
    (8, 4): 172_800,    # 48.0h
}

# Maximum Allowed Multi-Leg Desynchronization (seconds)
# Max time gap between input cost data (materials/base) and finished product sell order data
MAX_LEG_DESYNC_SECONDS = {
    1: 3_600,       # 1.0h
    2: 3_600,       # 1.0h
    3: 3_600,       # 1.0h
    4: 5_400,       # 1.5h
    5: 7_200,       # 2.0h
    6: 10_800,      # 3.0h
    7: 18_000,      # 5.0h
    8: 28_800,      # 8.0h
}

# ═══════════════════════════════════════════════════════════════
# ITEM CLASSIFICATION KEYWORDS
# ═══════════════════════════════════════════════════════════════

RAW_REFINED_KEYWORDS = (
    "_ORE", "_HIDE", "_FIBER", "_WOOD", "_ROCK",
    "_BAR", "_LEATHER", "_CLOTH", "_PLANKS", "_STONEBLOCK", "_BLOCK",
    "_METALBAR",
)

ENCHANT_MATERIAL_KEYWORDS = {
    "RUNE": ("_RUNE",),
    "SOUL": ("_SOUL",),
    "RELIC": ("_RELIC",),
    "SHARD": ("_SHARD_AVALONIAN", "QUESTITEM_TOKEN_AVALON"),
}

ARTIFACT_KEYWORDS = (
    "ARTEFACT_", "ARTIFACT_",
    "_ARTEFACT", "_ARTIFACT",
    "_BP",
)

CONSUMABLE_KEYWORDS = (
    "MEAL", "SOUP", "STEW", "PIE", "OMELETTE", "ROAST", "SANDWICH",
    "COOKED", "POTION", "POTION_", "FOOD_",
)

SPECIALTY_KEYWORDS = (
    "MOUNT_", "JOURNAL_", "UNIQUE_", "FURNITURE", "TROPHY_",
    "TOOL_", "GATHERING_", "FARM_", "SEED_",
    "QUESTITEM_", "TOKEN_", "PLAYERISLAND_",
    "SKILLBOOK_", "SKIN_", "TREASURE_",
)

EQUIPMENT_KEYWORDS = (
    "MAIN_", "2H_", "1H_", "OFF_",
    "HEAD_", "ARMOR_", "SHOES_",
    "CAPE", "BAG", "SHIELD",
    "SWORD", "AXE", "MACE", "HAMMER", "DAGGER", "SPEAR",
    "BOW", "CROSSBOW", "STAFF",
    "GLOVES", "WARGLOVES",
)


def _extract_tier_enchant(item_id: str) -> tuple[int, int]:
    """Extract tier (1-8) and enchantment (0-4) from an item_id string like T5_PLANKS@2 or QUESTITEM_TOKEN_ROYAL_T6."""
    tier = 4  # default
    enchant = 0
    if not item_id:
        return tier, enchant

    upper = item_id.upper()
    # Tier: T4_... or ..._T4
    if upper.startswith("T") and len(upper) > 1 and upper[1].isdigit():
        try:
            tier = int(upper[1])
        except ValueError:
            pass
    elif "_T" in upper:
        try:
            idx = upper.rindex("_T") + 2
            if idx < len(upper) and upper[idx].isdigit():
                tier = int(upper[idx])
        except (ValueError, IndexError):
            pass
    # Enchantment: @1, @2, @3, @4 or _LEVEL1, _LEVEL2, etc.
    if "@" in item_id:
        try:
            enchant = int(item_id.split("@")[1])
        except (ValueError, IndexError):
            pass
    elif "_LEVEL" in upper:
        try:
            idx = upper.index("_LEVEL") + 6
            enchant = int(upper[idx])
        except (ValueError, IndexError):
            pass

    return max(1, min(tier, 8)), max(0, min(enchant, 4))


def _classify_item(item_id: str) -> str:
    """
    Classify an item into one of: 'enchant_material', 'artifact', 'specialty',
    'consumable', 'equipment', 'material', or 'unknown'.
    """
    if not item_id:
        return "unknown"

    upper = item_id.upper()

    # 1. Enchantment materials (Runes, Souls, Relics, Shards)
    for mat_type, keywords in ENCHANT_MATERIAL_KEYWORDS.items():
        if any(kw in upper for kw in keywords):
            return "enchant_material"

    # 2. Crafting Artifacts
    if any(kw in upper for kw in ARTIFACT_KEYWORDS):
        return "artifact"

    # 3. Specialty (mounts, journals, tools, gathering gear, furniture)
    if any(kw in upper for kw in SPECIALTY_KEYWORDS):
        return "specialty"

    # 4. Consumables (food, potions)
    if any(kw in upper for kw in CONSUMABLE_KEYWORDS):
        return "consumable"

    # 5. Equipment (weapons, armor, off-hands, bags, capes)
    if any(kw in upper for kw in EQUIPMENT_KEYWORDS):
        return "equipment"

    # 6. Raw / Refined materials (Planks, Bars, Leather, Cloth, Ores, etc.)
    if any(kw in upper for kw in RAW_REFINED_KEYWORDS):
        return "material"

    # 7. Default to equipment for anything with a tier prefix
    if upper.startswith("T") and len(upper) > 2 and upper[1].isdigit() and upper[2] == "_":
        return "equipment"

    return "unknown"


def _get_enchant_material_type(item_id: str) -> str:
    """Returns 'RUNE', 'SOUL', 'RELIC', or 'SHARD' for enchantment materials."""
    upper = item_id.upper()
    for mat_type, keywords in ENCHANT_MATERIAL_KEYWORDS.items():
        if any(kw in upper for kw in keywords):
            return mat_type
    return "RUNE"  # default fallback


def _lookup_with_fallback(table: dict, tier: int, enchant: int, absolute_ceiling: int = 604_800) -> int:
    """
    Look up age limit from a tier×enchant table with intelligent fallback.
    """
    # 1. Exact match
    if (tier, enchant) in table:
        return table[(tier, enchant)]

    # 2. Same tier, lower enchant
    for e in range(enchant - 1, -1, -1):
        if (tier, e) in table:
            base = table[(tier, e)]
            scale = 1.0 + (enchant - e) * 0.5
            return min(int(base * scale), absolute_ceiling)

    # 3. Nearest tier at same enchant level
    for t in range(tier - 1, 0, -1):
        if (t, enchant) in table:
            base = table[(t, enchant)]
            scale = 1.0 + (tier - t) * 0.5
            return min(int(base * scale), absolute_ceiling)

    # 4. Nearest tier at enchant 0
    for t in range(tier - 1, 0, -1):
        if (t, 0) in table:
            base = table[(t, 0)]
            tier_scale = 1.0 + (tier - t) * 0.5
            enchant_scale = 1.0 + enchant * 0.5
            return min(int(base * tier_scale * enchant_scale), absolute_ceiling)

    return absolute_ceiling


def get_max_material_age_seconds(
    item_id: str,
    tier: int = None,
    enchant: int = None,
    volume_24h: int = 0,
    context: str = "default",
    scan_elapsed_seconds: int = 0,
) -> int:
    """
    Returns the maximum allowed data age (seconds) for ANY item in Albion Online.
    Includes continuous velocity/volume scaling and scan elapsed time allowance.
    """
    # Auto-extract tier and enchant from item_id if not provided
    if tier is None or enchant is None:
        auto_tier, auto_enchant = _extract_tier_enchant(item_id)
        if tier is None:
            tier = auto_tier
        if enchant is None:
            enchant = auto_enchant

    # Classify the item
    category = _classify_item(item_id)

    # Select the appropriate ladder
    if context == "market_making":
        age_limit = _lookup_with_fallback(MARKET_MAKING_AGE_LIMITS, tier, enchant)
    elif category == "material":
        age_limit = _lookup_with_fallback(MATERIAL_AGE_LIMITS, tier, enchant)
    elif category == "enchant_material":
        mat_type = _get_enchant_material_type(item_id)
        key = (tier, mat_type)
        if key in ENCHANT_MATERIAL_AGE_LIMITS:
            age_limit = ENCHANT_MATERIAL_AGE_LIMITS[key]
        else:
            rune_key = (tier, "RUNE")
            base = ENCHANT_MATERIAL_AGE_LIMITS.get(rune_key, 21_600)
            type_multipliers = {"RUNE": 1.0, "SOUL": 2.0, "RELIC": 4.0, "SHARD": 4.0}
            age_limit = int(base * type_multipliers.get(mat_type, 2.0))
    elif category == "artifact":
        age_limit = _lookup_with_fallback(ARTIFACT_AGE_LIMITS, tier, 0)
    elif category == "consumable":
        age_limit = _lookup_with_fallback(CONSUMABLE_AGE_LIMITS, tier, enchant)
    elif category == "specialty":
        age_limit = _lookup_with_fallback(SPECIALTY_AGE_LIMITS, tier, enchant)
    elif category == "equipment":
        age_limit = _lookup_with_fallback(EQUIPMENT_AGE_LIMITS, tier, enchant)
    else:
        age_limit = _lookup_with_fallback(EQUIPMENT_AGE_LIMITS, tier, enchant)

    # Continuous Volume Scaling: High-velocity market items reprice faster
    v24 = safe_int(volume_24h)
    if v24 >= 5_000:
        age_limit = max(1_500, int(round(age_limit * 0.35)))   # 35% of TTL, floor 25 min
    elif v24 >= 1_000:
        age_limit = max(1_800, int(round(age_limit * 0.55)))   # 55% of TTL, floor 30 min
    elif v24 >= 200:
        age_limit = max(2_400, int(round(age_limit * 0.80)))   # 80% of TTL, floor 40 min

    return age_limit + max(0, safe_int(scan_elapsed_seconds, default=0))


def get_max_allowed_leg_desync_seconds(
    tier: int = 4,
    enchant: int = 0,
    scan_elapsed_seconds: int = 0,
) -> int:
    """
    Returns the maximum allowable time delta (seconds) between input costs (materials/base item)
    and output revenue (finished product sell price) for multi-leg operations.
    Supports tier, enchantment level scaling, and scan sweep elapsed time allowance.
    """
    t = max(1, min(8, safe_int(tier, default=4)))
    e = max(0, min(4, safe_int(enchant, default=0)))
    base_desync = MAX_LEG_DESYNC_SECONDS.get(t, 9_000)
    if t >= 7 and e >= 2:
        desync = int(base_desync * (1.0 + e * 0.25))
    else:
        desync = base_desync
    return desync + max(0, safe_int(scan_elapsed_seconds, default=0))


def calculate_leg_sync_score(
    output_age: float,
    input_ages: Sequence[float] | float,
    tier: int = 4,
) -> float:
    """
    Computes a 0.1 -> 1.0 synchronization confidence score based on the time delta
    between input material costs and output finished product revenue.
    """
    if isinstance(input_ages, (int, float)):
        max_input_age = float(input_ages)
    elif input_ages:
        max_input_age = float(max(input_ages))
    else:
        max_input_age = float(output_age)

    delta = abs(float(output_age) - max_input_age)
    max_allowed = float(get_max_allowed_leg_desync_seconds(tier))

    if delta <= 0:
        return 1.0

    # Smooth linear-to-decay penalty
    sync_factor = max(0.1, 1.0 - (delta / max_allowed))
    return round(sync_factor, 4)


def calculate_route_travel_buffer(source_city: str, dest_city: str) -> int:
    """
    Estimates the travel time (seconds) required for a player to pack, travel across zones,
    and arrive at the destination market.
    """
    if source_city == dest_city:
        return 0

    from app.core.constants import get_distance, is_route_dangerous

    dist = get_distance(source_city, dest_city)
    is_danger = is_route_dangerous(source_city, dest_city)

    # 180 seconds per zone + 300s prep/cautious travel buffer for dangerous zones
    travel_seconds = (dist * 180) + (300 if is_danger else 60)
    return travel_seconds


def is_market_data_fresh(
    item_id: str,
    age_seconds: int | None,
    volume_24h: int | None = 0,
    tier: int | None = None,
    scan_elapsed_seconds: int = None,
) -> bool:
    """
    Determines if market data is fresh enough to be ingested into the database.
    Includes scan sweep elapsed time allowance to prevent borderline records from being discarded.
    """
    if age_seconds is None:
        return False

    if scan_elapsed_seconds is None:
        from app.core.config import settings
        scan_elapsed_seconds = getattr(settings, "scan_elapsed_buffer_seconds", 300)

    threshold = get_max_material_age_seconds(
        item_id,
        tier=tier,
        volume_24h=safe_int(volume_24h),
        scan_elapsed_seconds=scan_elapsed_seconds,
    )

    is_fresh = age_seconds <= threshold

    if not is_fresh:
        log.debug(f"🗑️ FRESHNESS: Rejected {item_id} (Age: {age_seconds}s, Threshold: {threshold}s)")

    return is_fresh


def get_tier_based_half_life_hours(item_id: str, tier: int = None, enchant: int = None) -> float:
    """
    Returns the appropriate time-decay half-life for scoring, scaled by tier and enchantment.
    """
    if tier is None or enchant is None:
        auto_tier, auto_enchant = _extract_tier_enchant(item_id)
        if tier is None:
            tier = auto_tier
        if enchant is None:
            enchant = auto_enchant

    tier_half_lives = {
        1: 2.0,
        2: 2.0,
        3: 2.5,
        4: 3.5,
        5: 5.0,
        6: 7.0,
        7: 10.0,
        8: 14.0,
    }
    base = tier_half_lives.get(tier, 5.0)

    # Enchant bonus: +1.5h per enchant level
    enchant_bonus = enchant * 1.5

    return min(24.0, base + enchant_bonus)
