"""
Transport features.
Calculates transport risk and cost.
"""

def calculate_transport_cost(weight: float, distance_zones: int, cost_per_weight_zone: float = 1.0) -> float:
    """
    Calculates transport cost based on weight and distance in zones.
    """
    return weight * distance_zones * cost_per_weight_zone

def calculate_route_danger_score(killboard_activity: int, zone_type: str) -> float:
    """
    Calculates a simple danger score for a route.
    zone_type can be 'blue', 'yellow', 'red', 'black'.
    """
    base_danger = {
        'blue': 0.0,
        'yellow': 0.2,
        'red': 0.7,
        'black': 1.0
    }
    
    return base_danger.get(zone_type, 0.0) * (1.0 + (killboard_activity / 100.0))
