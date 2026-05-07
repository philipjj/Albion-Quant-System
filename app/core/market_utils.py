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

def calculate_blended_price(sell_min: float, buy_max: float, item_value: float = 0) -> float:
    """
    Calculates a realistic execution price by blending Sell Orders and Buy Orders.
    Prevents relying solely on outliers or thin market listings.
    """
    if sell_min <= 0 and buy_max <= 0:
        return 0.0
    
    # If one is missing, use the other but with a liquidity penalty
    if buy_max <= 0: return sell_min * 0.95
    if sell_min <= 0: return buy_max * 1.05

    # Albion Economics: 
    # Sell Orders are the 'Ask' (highest potential)
    # Buy Orders are the 'Bid' (guaranteed liquidity)
    # We use a 70/30 blend to favor the sell price but respect the bid floor.
    blended = (sell_min * 0.7) + (buy_max * 0.3)
    
    # If the spread is insane (> 50%), the market is too thin to trust SellMin.
    # We pull the price closer to the Buy Order floor.
    spread = (sell_min - buy_max) / sell_min
    if spread > 0.50:
        blended = (sell_min * 0.4) + (buy_max * 0.6)
        
    return round(blended, 2)

def calculate_z_score(current_price: float, historical_prices: list[float]) -> float:
    """
    Calculates the Z-Score of the current price relative to history.
    Z = (P - Mean) / StdDev
    
    Z > 2.5 indicates a probable price spike/manipulation.
    """
    if not historical_prices or len(historical_prices) < 3:
        return 0.0
        
    import math
    mean = sum(historical_prices) / len(historical_prices)
    variance = sum((p - mean) ** 2 for p in historical_prices) / len(historical_prices)
    std_dev = math.sqrt(variance)
    
    if std_dev == 0:
        return 0.0
        
    return (current_price - mean) / std_dev

def calculate_absorption_coefficient(target_quantity: float, buy_side_depth: float) -> float:
    """
    Order Book Absorption Coefficient (OAC).
    Estimates what percentage of your inventory can be absorbed without a price collapse.
    """
    if target_quantity <= 0: return 1.0
    if buy_side_depth <= 0: return 0.01 # Extremely thin
    
    return min(1.0, buy_side_depth / target_quantity)
