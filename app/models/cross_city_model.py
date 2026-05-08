"""
Cross-City Model.
Identifies statistical arbitrage opportunities between cities.
"""
from datetime import datetime
from typing import List, Dict
from app.features.spread import calculate_absolute_spread
from app.features.transport import calculate_transport_cost, calculate_route_danger_score
from app.shared.domain.signal import Signal

class CrossCityModel:
    def __init__(self, min_profit_threshold: float = 1000.0, max_danger_threshold: float = 0.5):
        self.min_profit_threshold = min_profit_threshold
        self.max_danger_threshold = max_danger_threshold

    def evaluate(self, item_id: str, city_prices: Dict[str, float], item_weight: float, route_info: Dict[str, Dict[str, any]]) -> List[Signal]:
        """
        Evaluates price differences between cities.
        city_prices is a dict: {city_name: price}
        route_info is a dict of dicts: {source_city: {target_city: {distance_zones: int, zone_type: str, killboard_activity: int}}}
        """
        signals = []
        cities = list(city_prices.keys())
        
        for i in range(len(cities)):
            for j in range(len(cities)):
                if i == j:
                    continue
                    
                src = cities[i]
                dst = cities[j]
                
                src_price = city_prices[src]
                dst_price = city_prices[dst]
                
                # We buy at src and sell at dst
                spread = dst_price - src_price
                
                if spread <= 0:
                    continue
                    
                # Get route info
                route = route_info.get(src, {}).get(dst, {})
                if not route:
                    continue
                    
                distance = route.get('distance_zones', 1)
                zone_type = route.get('zone_type', 'blue')
                killboard = route.get('killboard_activity', 0)
                
                transport_cost = calculate_transport_cost(item_weight, distance)
                danger_score = calculate_route_danger_score(killboard, zone_type)
                
                if danger_score > self.max_danger_threshold:
                    continue
                    
                net_profit = spread - transport_cost
                
                if net_profit > self.min_profit_threshold:
                    signals.append(Signal(
                        item_id=item_id,
                        city=dst, # Signal is actionable at destination where we sell
                        timestamp=datetime.utcnow(),
                        signal_type="cross_city_arb",
                        strength=min(1.0, net_profit / 10000.0), # Arbitrary scaling
                        metadata={
                            "source_city": src,
                            "target_city": dst,
                            "spread": spread,
                            "transport_cost": transport_cost,
                            "danger_score": danger_score,
                            "net_profit": net_profit
                        }
                    ))
                
        return signals
