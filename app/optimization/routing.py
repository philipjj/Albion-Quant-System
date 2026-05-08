"""
Route Optimization.
Optimizes transport routes based on risk and cost.
"""
from typing import List, Dict
from app.features.transport import calculate_transport_cost, calculate_route_danger_score

class RouteOptimizer:
    def optimize_route(self, possible_routes: List[Dict[str, any]], item_weight: float) -> List[Dict[str, any]]:
        """
        Ranks routes by a score that balances profit and risk.
        possible_routes is a list of dicts: {'source': str, 'target': str, 'spread': float, 'distance_zones': int, 'zone_type': str, 'killboard_activity': int}
        """
        results = []
        for route in possible_routes:
            cost = calculate_transport_cost(item_weight, route.get('distance_zones', 1))
            danger = calculate_route_danger_score(route.get('killboard_activity', 0), route.get('zone_type', 'blue'))
            
            net_profit = route.get('spread', 0) - cost
            
            # Risk-adjusted profit
            risk_adjusted_profit = net_profit * (1.0 - danger)
            
            results.append({
                'source': route.get('source'),
                'target': route.get('target'),
                'net_profit': net_profit,
                'danger_score': danger,
                'risk_adjusted_profit': risk_adjusted_profit
            })
            
        # Sort by risk-adjusted profit descending
        results.sort(key=lambda x: x['risk_adjusted_profit'], reverse=True)
        return results
