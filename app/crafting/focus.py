"""
Focus Point Maximizer
Calculates the 'Profit per Focus Point' for all current crafting opportunities.
"""

from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.db.models import CraftingOpportunity, Item
from app.db.session import get_db_session

def optimize_focus(max_focus: int = 10000, spec_level: int = 0) -> dict:
    """
    Finds the most profitable items to craft with a given amount of Focus Points.
    Uses an estimated focus cost derived from the game's item_value and base RRR differences.
    """
    with get_db_session() as db:
        opps = db.query(CraftingOpportunity, Item.item_value).join(
            Item, CraftingOpportunity.item_id == Item.item_id
        ).filter(
            CraftingOpportunity.is_active == True,
            CraftingOpportunity.profit > 0
        ).all()
        
    if not opps:
        return {"total_profit_gained": 0, "focus_used": 0, "items": []}
        
    items_to_evaluate = []
    
    # Base RRR = 15.2%, Focus RRR = 43.5%
    # Using focus saves ~28.3% of the raw ingredient cost.
    # Craft_cost in DB is currently after 15.2% RRR, so:
    # raw_ingredient_cost = craft_cost / (1 - 0.152)
    # extra_profit_from_focus = raw_ingredient_cost * (0.435 - 0.152)
    
    for opp, item_value in opps:
        if item_value <= 0:
            item_value = 100 # safe fallback
            
        # Approximation of Albion focus cost based on item value and spec.
        # Max spec reduces focus cost by a factor of 2.5 (10,000 focus proficiency)
        # Base focus roughly equals item_value * 3 (approx synthetic scalar)
        base_focus_cost = item_value * 3.0
        
        # Spec level (0 to 100). Every 100 points reduces cost by 50%
        focus_efficiency = 0.5 ** (spec_level / 100.0)
        actual_focus_cost = max(base_focus_cost * focus_efficiency, 1.0)
        
        # Calculate extra profit from focus
        raw_ingredient_cost = opp.craft_cost / 0.848
        extra_profit = raw_ingredient_cost * 0.283
        
        total_profit_with_focus = opp.profit + extra_profit
        profit_per_focus = extra_profit / actual_focus_cost
        
        items_to_evaluate.append({
            "item_id": opp.item_id,
            "item_name": opp.item_name,
            "crafting_city": opp.crafting_city,
            "sell_city": opp.sell_city,
            "base_profit": opp.profit,
            "extra_profit_from_focus": extra_profit,
            "total_profit_with_focus": total_profit_with_focus,
            "focus_cost_per_item": actual_focus_cost,
            "profit_per_focus": profit_per_focus,
            "daily_volume": opp.daily_volume
        })
        
    # Sort by profit per focus (descending)
    items_to_evaluate.sort(key=lambda x: x["profit_per_focus"], reverse=True)
    
    focus_used = 0.0
    total_extra_profit = 0.0
    selected_items = []
    
    for item in items_to_evaluate:
        remaining_focus = max_focus - focus_used
        if remaining_focus <= 0:
            break
            
        # How many can we craft with remaining focus?
        max_craftable = int(remaining_focus // item["focus_cost_per_item"])
        
        # How many should we craft based on daily volume (cap at 20% of daily volume to be safe)
        safe_volume = max(int(item["daily_volume"] * 0.20), 1)
        qty_to_craft = min(max_craftable, safe_volume)
        
        if qty_to_craft > 0:
            used = qty_to_craft * item["focus_cost_per_item"]
            gained = qty_to_craft * item["extra_profit_from_focus"]
            
            focus_used += used
            total_extra_profit += gained
            
            selected_items.append({
                "item_id": item["item_id"],
                "item_name": item["item_name"],
                "quantity": qty_to_craft,
                "focus_used": round(used, 2),
                "extra_profit": round(gained, 2),
                "total_profit": round(qty_to_craft * item["total_profit_with_focus"], 2),
                "profit_per_focus": round(item["profit_per_focus"], 2)
            })
            
    return {
        "max_focus_allowance": max_focus,
        "focus_used": round(focus_used, 2),
        "total_extra_profit_gained": round(total_extra_profit, 2),
        "spec_level_used": spec_level,
        "items": selected_items
    }
