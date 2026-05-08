"""
Backtesting Strategies.
"""
from typing import Dict, Any
from research.backtesting.engine import Strategy

class SimpleArbitrageStrategy(Strategy):
    """
    Simple strategy that tracks prices across cities and identifies arbitrage.
    """
    def __init__(self):
        # item_id -> city -> price
        self.prices: Dict[str, Dict[str, float]] = {}
        
    def on_data(self, event: Dict[str, Any], engine: Any):
        """
        Called on each market event.
        """
        item_id = event.get("item_id")
        city = event.get("city")
        # Support both 'price' and 'sell_price_min' (common in AQS)
        price = event.get("price") or event.get("sell_price_min")
        
        if not item_id or not city or price is None:
            return
            
        if item_id not in self.prices:
            self.prices[item_id] = {}
            
        self.prices[item_id][city] = price
        
        # Check for arbitrage opportunity
        city_prices = self.prices[item_id]
        if len(city_prices) >= 2:
            min_city = min(city_prices, key=city_prices.get)
            max_city = max(city_prices, key=city_prices.get)
            
            spread = city_prices[max_city] - city_prices[min_city]
            
            if spread > 20.0:  # Heuristic threshold
                # If we are at the min city, buy!
                # If we are at the max city, sell!
                # But we need to know where we are!
                if city == min_city:
                    engine.execute_order(item_id, quantity=1, price=price, side="buy")
                elif city == max_city and engine.positions.get(item_id, 0) > 0:
                    engine.execute_order(item_id, quantity=1, price=price, side="sell")
