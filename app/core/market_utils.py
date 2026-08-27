import math
from datetime import datetime

from app.core.constants import CITY_CRAFTING_BONUSES, CITY_ISLAND_FARMING_BONUSES


def calculate_time_decay(age_seconds: float, half_life_hours: float = 6.0) -> float:
    """
    Computes smooth exponential decay factor:
    age = 0s -> 1.0
    age = half_life -> 0.5
    age = 2 * half_life -> 0.25
    Never produces an artificial hard cliff.
    """
    if age_seconds <= 0:
        return 1.0
    half_life_seconds = max(1.0, half_life_hours * 3600.0)
    return math.exp(-math.log(2.0) * (age_seconds / half_life_seconds))


def get_island_farming_bonus(island_city: str, item_id: str) -> float:
    """
    Returns the official Albion Online Island Biome yield bonus (+10% or 0.10)
    if the crop, herb, or animal matches the island's host city specialization.
    """
    if not island_city or not item_id:
        return 0.0

    # Normalize city name if formatted like "Bridgewatch Island" or "Personal Island (Bridgewatch)"
    clean_city = island_city.replace("Personal Island (", "").replace(")", "").replace(" Island", "").strip()
    bonuses = CITY_ISLAND_FARMING_BONUSES.get(clean_city)
    if not bonuses:
        return 0.0

    u = item_id.upper()
    all_bonus_keywords = bonuses.get("crops", []) + bonuses.get("herbs", []) + bonuses.get("animals", [])
    if any(k in u for k in all_bonus_keywords):
        return bonuses.get("bonus_yield_pct", 10.0) / 100.0

    return 0.0


# Derive city specialization bonuses from authoritative central constants
CITY_BONUS: dict[str, dict[str, list[str]]] = {
    city: {
        "refining": data["refining_bonus"],
        "crafting": data["bonus_categories"],
    }
    for city, data in CITY_CRAFTING_BONUSES.items()
}


# [CONFIRMED] Production bonus constants
BASE_CITY_PRODUCTION_BONUS = 18.0
REFINING_SPECIALIZATION_BONUS = 40.0
CRAFTING_SPECIALIZATION_BONUS = 15.0
FOCUS_PRODUCTION_BONUS = 59.0


def get_refining_category(item_id: str) -> str:
    """Extracts the refining category from the item_id for bonus calculation."""
    item_upper = item_id.upper()

    # Equipment items are NEVER refined resources
    if any(eq in item_upper for eq in [
        "ARMOR", "ROBE", "JACKET", "GARB", "HEAD", "HELMET", "COWL", "CAP", "SHOES", "BOOTS",
        "MAIN_", "2H_", "OFF_", "BAG", "CAPE", "MOUNT"
    ]):
        return ""

    if "PLANKS" in item_upper or "WOOD" in item_upper: return "planks"
    if "METALBAR" in item_upper or "ORE" in item_upper: return "metalbar"
    if "LEATHER" in item_upper or "HIDE" in item_upper: return "leather"
    if "CLOTH" in item_upper or "FIBER" in item_upper: return "cloth"
    if "STONEBLOCK" in item_upper or "ROCK" in item_upper: return "stoneblock"
    return ""

def get_item_crafting_subcategory(item_id: str, category: str = "") -> str:
    """
    Extracts the crafting subcategory for city crafting bonus matching.
    Matches against CITY_CRAFTING_BONUSES categories.
    """
    u = item_id.upper()
    cat_lower = (category or "").lower()

    # Gathering Tools (Caerleon Toolmaker Bonus) - check BEFORE weapons to avoid false "axe"/"hammer" matches
    if any(k in u for k in ["_TOOL_AXE", "_TOOL_PICK", "_TOOL_SICKLE", "_TOOL_KNIFE", "_TOOL_HAMMER", "_TOOL_FISHINGROD", "_TOOL_SIEGE"]):
        return "gathering_tool"
    if "GATHERER" in u or "GATHERING" in u:
        return "gathering_gear"

    # Consumables: Potions & Food
    if "POTION" in u or "potion" in cat_lower or "alchemy" in cat_lower:
        return "potion"
    if any(k in u for k in ["_MEAL_", "_STEW", "_SOUP", "_PIE", "_OMELETTE", "_ROAST", "_SANDWICH", "_SALAD", "_BREAD", "_FISHSAUCE"]) or "cooking" in cat_lower or "food" in cat_lower:
        return "cooked_food"

    # Off-hands
    if any(k in u for k in ["_OFF_", "_SHIELD", "_TOME", "_TORCH", "_HORN", "_ORB", "_TOTEM", "_BOOK", "_LAMP", "_CANE", "_EYE", "_TALISMAN"]):
        return "offhand"

    # Weapons
    if "SWORD" in u or "DUALSWORD" in u or "CLAYMORE" in u or "SCIMITAR" in u:
        return "sword"
    if "CROSSBOW" in u:
        return "crossbow"
    if "BOW" in u:
        return "bow"
    if "AXE" in u or "SCYTHE" in u or "HALBERD" in u:
        return "axe"
    if "HAMMER" in u:
        return "hammer"
    if "MACE" in u or "FLAIL" in u:
        return "mace"
    if "DAGGER" in u or "CLAW" in u or "PAIR_DAGGER" in u:
        return "dagger"
    if "SPEAR" in u or "PIKE" in u or "GLAIVE" in u or "TRIDENT" in u:
        return "spear"
    if "QUARTERSTAFF" in u or "IRONCLAD" in u or "STAFF_QUARTER" in u or "COMBATSTAFF" in u:
        return "quarterstaff"
    if "HOLYSTAFF" in u or "HOLY_STAFF" in u or "MAIN_HOLY" in u or "2H_HOLY" in u:
        return "holy_staff"
    if "FIRESTAFF" in u or "FIRE_STAFF" in u or "MAIN_FIRE" in u or "2H_FIRE" in u:
        return "fire_staff"
    if "ARCANESTAFF" in u or "ARCANE_STAFF" in u or "MAIN_ARCANE" in u or "2H_ARCANE" in u:
        return "arcane_staff"
    if "FROSTSTAFF" in u or "FROST_STAFF" in u or "MAIN_FROST" in u or "2H_FROST" in u or "ICICLE" in u:
        return "frost_staff"
    if "CURSEDSTAFF" in u or "CURSE_STAFF" in u or "CURSED_STAFF" in u or "MAIN_CURSED" in u or "2H_CURSED" in u:
        return "cursed_staff"
    if "NATURESTAFF" in u or "NATURE_STAFF" in u or "MAIN_NATURE" in u or "2H_NATURE" in u or "WILDSTAFF" in u:
        return "nature_staff"
    if "SHAPESHIFTER" in u:
        return "shapeshifter_staff"
    if "KNUCKLES" in u or "WARGLOVES" in u or "WAR_GLOVES" in u or "GLOVES" in u:
        return "war_gloves"

    # Chest Armor
    if "ARMOR_PLATE" in u or "PLATE_ARMOR" in u:
        return "plate_armor"
    if "ARMOR_LEATHER" in u or "LEATHER_ARMOR" in u or "JACKET" in u:
        return "leather_armor"
    if "ARMOR_CLOTH" in u or "CLOTH_ARMOR" in u or "ROBE" in u:
        return "cloth_armor"

    # Helmets / Headgear
    if "HEAD_PLATE" in u or "PLATE_HEAD" in u or "PLATE_HELMET" in u or "HELMET_PLATE" in u:
        return "plate_helmet"
    if "HEAD_LEATHER" in u or "LEATHER_HEAD" in u or "LEATHER_HOOD" in u or "HOOD_LEATHER" in u:
        return "leather_helmet"
    if "HEAD_CLOTH" in u or "CLOTH_HEAD" in u or "CLOTH_COWL" in u or "COWL_CLOTH" in u:
        return "cloth_cowl"

    # Shoes / Boots / Sandals
    if "SHOES_PLATE" in u or "PLATE_SHOES" in u or "PLATE_BOOTS" in u or "BOOTS_PLATE" in u:
        return "plate_shoes"
    if "SHOES_LEATHER" in u or "LEATHER_SHOES" in u or "LEATHER_BOOTS" in u:
        return "leather_shoes"
    if "SHOES_CLOTH" in u or "CLOTH_SHOES" in u or "CLOTH_BOOTS" in u or "SANDALS_CLOTH" in u:
        return "cloth_shoes"

    # Bags & Capes
    if "BAG" in u:
        return "bag"
    if "CAPE" in u:
        return "cape"
    if "MOUNT" in u:
        return "mounts"

    return cat_lower


def calculate_rrr(
    location: str,
    item_category: str,
    tier: int = 4,
    use_focus: bool = False,
    daily_bonus: int = 0,
) -> float:
    """
    Calculates Resource Return Rate (RRR) using the verified formula:
    RRR = 1 - 1 / (1 + production_bonus / 100)
    """
    if daily_bonus not in (0, 10, 20):
        # Fallback for old callers passing bool
        if isinstance(daily_bonus, bool):
            daily_bonus = 10 if daily_bonus else 0
        else:
            daily_bonus = 0

    production_bonus = BASE_CITY_PRODUCTION_BONUS

    city_data = CITY_BONUS.get(location, {})
    craft_bonus_list = city_data.get("crafting", [])
    refine_bonus_list = city_data.get("refining", [])

    if item_category in refine_bonus_list:
        production_bonus += REFINING_SPECIALIZATION_BONUS
    elif item_category in craft_bonus_list:
        production_bonus += CRAFTING_SPECIALIZATION_BONUS
    else:
        # Check subcategory resolution
        subcat = get_item_crafting_subcategory(item_category)
        if subcat in craft_bonus_list:
            production_bonus += CRAFTING_SPECIALIZATION_BONUS
        elif subcat in refine_bonus_list:
            production_bonus += REFINING_SPECIALIZATION_BONUS

    if use_focus:
        production_bonus += FOCUS_PRODUCTION_BONUS

    production_bonus += daily_bonus

    rrr = 1.0 - (1.0 / (1.0 + production_bonus / 100.0))
    return min(0.99, round(rrr, 4))


def calculate_liquidity_confidence(
    update_freq_h: float,
    age_sec: float,
    spread_pct: float | None,
    volume_24h: int,
    stability_7d: float | None,
    zero_volume_gap: bool = False,
) -> tuple[float, bool]:
    """
    Returns (confidence_score, encryption_penalised).
    """
    freq_score = min(1.0, 24.0 / max(update_freq_h, 0.1))
    age_score = max(0.0, 1.0 - (age_sec / 3600))
    spread_score = 1.0 if spread_pct is None else max(0.0, 1.0 - (spread_pct / 0.5))
    volume_score = min(1.0, volume_24h / 10000)
    stability_score = 1.0 if stability_7d is None else max(0.0, 1.0 - (stability_7d / 0.3))

    confidence = (
        0.25 * freq_score
        + 0.30 * age_score
        + 0.20 * spread_score
        + 0.15 * volume_score
        + 0.10 * stability_score
    )

    encryption_penalised = False
    if zero_volume_gap:
        confidence *= 0.5
        encryption_penalised = True

    return round(confidence, 3), encryption_penalised


def calculate_net_material_cost(
    material_price: int,
    quantity: int,
    location: str,
    item_category: str,
    tier: int,
    use_focus: bool = False,
    daily_bonus: int = 0,
) -> dict:
    """Effective material cost after resource returns."""
    rrr = calculate_rrr(location, item_category, tier, use_focus, daily_bonus)
    net_quantity = quantity * (1.0 - rrr)
    net_cost = round(material_price * net_quantity)

    return {
        "gross_quantity": quantity,
        "rrr": rrr,
        "net_quantity": round(net_quantity, 4),
        "material_price": material_price,
        "net_cost": net_cost,
    }


def calculate_blended_price(sell_min: float, buy_max: float) -> float:
    """Calculates a realistic execution price by blending Sell Orders and Buy Orders."""
    if sell_min <= 0 and buy_max <= 0:
        return 0.0
    if buy_max <= 0:
        return sell_min * 0.95
    if sell_min <= 0:
        return buy_max * 1.05

    blended = (sell_min * 0.7) + (buy_max * 0.3)
    spread = (sell_min - buy_max) / sell_min if sell_min > 0 else 0
    if spread > 0.50:
        blended = (sell_min * 0.4) + (buy_max * 0.6)
    return round(blended, 2)


def calculate_z_score(current_price: float, historical_prices: list[float]) -> float:
    """Calculates the Z-Score of the current price relative to history."""
    if not historical_prices or len(historical_prices) < 3:
        return 0.0
    import math

    mean = sum(historical_prices) / len(historical_prices)
    variance = sum((p - mean) ** 2 for p in historical_prices) / len(historical_prices)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0
    return (current_price - mean) / std_dev


def apply_enchantment_ceiling_scanner(prices: dict) -> None:
    """
    Applies price ceiling so lower enchantments cannot be priced higher than higher enchantments.
    prices format: dict[(item_id, quality)][city] = {"sell_price_min": X, ...}
    """
    from collections import defaultdict
    grouped = defaultdict(list)
    for (item_id, quality), city_data in prices.items():
        if '@' in item_id:
            base_item, ench = item_id.split('@')
            try: ench_level = int(ench)
            except ValueError: ench_level = 0
        else:
            base_item = item_id
            ench_level = 0
        for city, p_data in city_data.items():
            grouped[(base_item, quality, city)].append((ench_level, item_id, p_data))
            
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: x[0], reverse=True)
        current_ceiling = float('inf')
        for ench_level, item_id, p_data in items:
            sell = p_data.get("sell_price_min", 0)
            if sell > 0:
                if sell >= current_ceiling:
                    new_price = max(1, int(current_ceiling - 1))
                    p_data["sell_price_min"] = new_price
                    current_ceiling = new_price
                else:
                    current_ceiling = sell

def apply_enchantment_ceiling_crafting(prices: dict) -> None:
    """
    prices format: dict[item_id][city][quality] = {"sell_price_min": X, ...}
    """
    from collections import defaultdict
    grouped = defaultdict(list)
    for item_id, city_data in prices.items():
        if '@' in item_id:
            base_item, ench = item_id.split('@')
            try: ench_level = int(ench)
            except ValueError: ench_level = 0
        else:
            base_item = item_id
            ench_level = 0
        for city, q_data in city_data.items():
            for quality, p_data in q_data.items():
                grouped[(base_item, city, quality)].append((ench_level, item_id, p_data))
                
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: x[0], reverse=True)
        current_ceiling = float('inf')
        for ench_level, item_id, p_data in items:
            sell = p_data.get("sell_price_min", 0)
            if sell > 0:
                if sell >= current_ceiling:
                    new_price = max(1, int(current_ceiling - 1))
                    p_data["sell_price_min"] = new_price
                    current_ceiling = new_price
                else:
                    current_ceiling = sell
