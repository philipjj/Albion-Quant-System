"""
Market utility functions for Albion Online.
Volume simulation and liquidity scoring.
"""

def simulate_daily_volume(item_id: str) -> int:
    """
    Simulate daily trade volume based on item tier, category, and enchantment.
    Includes high-velocity multipliers for consumables (Potions/Food).
    """
    # Base volume by tier
    base_vol = 50
    if "T4" in item_id:
        base_vol = 2500
    elif "T5" in item_id:
        base_vol = 1200
    elif "T6" in item_id:
        base_vol = 400
    elif "T7" in item_id:
        base_vol = 80
    elif "T8" in item_id:
        base_vol = 15

    # Category Multipliers
    multiplier = 1.0
    id_upper = item_id.upper()
    if "POTION" in id_upper:
        multiplier = 10.0
    elif "FOOD" in id_upper or "MEAL" in id_upper or "SOUP" in id_upper or "STEW" in id_upper:
        multiplier = 8.0
    elif "MOUNT" in id_upper or "HORSE" in id_upper or "OX" in id_upper:
        multiplier = 3.0
    elif "BAG" in id_upper or "CAPE" in id_upper:
        multiplier = 4.0
    elif any(res in id_upper for res in ["WOOD", "ORE", "FIBER", "HIDE", "ROCK", "BAR", "PLANK", "CLOTH", "LEATHER"]):
        multiplier = 15.0 # High volume for raw/refined materials

    final_vol = int(base_vol * multiplier)

    # Enchantment penalty
    if "@" in item_id:
        enchant_parts = item_id.split("@")
        if len(enchant_parts) > 1:
            try:
                enchant = int(enchant_parts[1])
                # .1 = 50%, .2 = 25%, .3 = 10% volume of base
                final_vol = int(final_vol / (2 ** enchant))
            except ValueError:
                pass

    return max(1, final_vol)
