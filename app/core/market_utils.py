"""
Market utility functions for Albion Online.
Volume simulation, liquidity scoring, and RRR calculation.
"""

from datetime import datetime

from app.core.constants import CITY_CRAFTING_BONUSES

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

def calculate_rrr(
    location: str,
    item_category: str,
    tier: int,
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
    if item_category in city_data.get("refining", []):
        production_bonus += REFINING_SPECIALIZATION_BONUS
    elif item_category in city_data.get("crafting", []):
        production_bonus += CRAFTING_SPECIALIZATION_BONUS

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
