"""
Focus Efficiency features.
Calculates silver per focus for crafting.
"""

def calculate_silver_per_focus(profit: float, focus_cost: int) -> float:
    """
    Calculates silver per focus.
    """
    if focus_cost == 0:
        return 0.0
    return profit / focus_cost

def calculate_marginal_focus_efficiency(profit_with_focus: float, profit_without_focus: float, focus_cost: int) -> float:
    """
    Calculates the marginal profit gained per focus spent.
    """
    if focus_cost == 0:
        return 0.0
    return (profit_with_focus - profit_without_focus) / focus_cost
