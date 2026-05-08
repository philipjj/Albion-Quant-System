"""
Market utility functions for Albion Online.
Moved from app/core/market_utils.py to shared/utils/market.py.
"""
from datetime import datetime

# City specialization bonuses
CITY_BONUS: dict[str, dict[str, list[str]]] = {
    "Martlock":    {"refining": ["hide"],  "crafting": ["axe", "quarterstaff", "frost_staff", "plate_shoes", "offhand"]},
    "Bridgewatch": {"refining": ["rock"],  "crafting": ["crossbow", "dagger", "cursed_staff", "plate_helmet", "leather_shoes"]},
    "Thetford":    {"refining": ["ore"],   "crafting": ["mace", "nature_staff", "fire_staff", "leather_armor", "cloth_headgear"]},
    "Lymhurst":    {"refining": ["fiber"], "crafting": ["sword", "bow", "arcane_staff", "leather_helmet", "cloth_armor"]},
    "Fort Sterling":{"refining": ["wood"], "crafting": ["spear", "holy_staff", "plate_armor", "cloth_shoes", "offhand"]},
}

# Production bonus constants
BASE_CITY_PRODUCTION_BONUS   = 18.0
REFINING_SPECIALIZATION_BONUS = 40.0
CRAFTING_SPECIALIZATION_BONUS = 15.0
FOCUS_PRODUCTION_BONUS        = 59.0

def calculate_rrr(
    location:     str,
    item_category: str,
    tier:          int,
    use_focus:     bool = False,
    daily_bonus:   int  = 0,
) -> float:
    """Calculates Resource Return Rate (RRR)."""
    if daily_bonus not in (0, 10, 20):
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
    update_freq_h:   float,
    age_sec:         float,
    spread_pct:      float | None,
    volume_24h:      int,
    stability_7d:    float | None,
    zero_volume_gap: bool = False,
) -> tuple[float, bool]:
    """Returns (confidence_score, encryption_penalised)."""
    freq_score      = min(1.0, 24.0 / max(update_freq_h, 0.1))
    age_score       = max(0.0, 1.0 - (age_sec / 3600))
    spread_score    = 1.0 if spread_pct is None else max(0.0, 1.0 - (spread_pct / 0.5))
    volume_score    = min(1.0, volume_24h / 10000)
    stability_score = 1.0 if stability_7d is None else max(0.0, 1.0 - (stability_7d / 0.3))

    confidence = (
        0.25 * freq_score    +
        0.30 * age_score     +
        0.20 * spread_score  +
        0.15 * volume_score  +
        0.10 * stability_score
    )

    encryption_penalised = False
    if zero_volume_gap:
        confidence *= 0.5
        encryption_penalised = True

    return round(confidence, 3), encryption_penalised

def calculate_net_material_cost(
    material_price: int,
    quantity:       int,
    location:       str,
    item_category:  str,
    tier:           int,
    use_focus:      bool = False,
    daily_bonus:    int  = 0,
) -> dict:
    """Effective material cost after resource returns."""
    rrr          = calculate_rrr(location, item_category, tier, use_focus, daily_bonus)
    net_quantity = quantity * (1.0 - rrr)
    net_cost     = round(material_price * net_quantity)

    return {
        "gross_quantity":  quantity,
        "rrr":             rrr,
        "net_quantity":    round(net_quantity, 4),
        "material_price":  material_price,
        "net_cost":        net_cost,
    }

def calculate_blended_price(sell_min: float, buy_max: float) -> float:
    """Calculates a realistic execution price by blending Sell Orders and Buy Orders."""
    if sell_min <= 0 and buy_max <= 0:
        return 0.0
    if buy_max <= 0: return sell_min * 0.95
    if sell_min <= 0: return buy_max * 1.05

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
