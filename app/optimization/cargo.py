"""
Cargo Optimization.
Optimizes cargo allocation based on weight and value (Knapsack problem).
"""
from typing import List, Dict

class CargoOptimizer:
    def optimize_allocation(self, items: List[Dict[str, any]], max_weight: float) -> List[Dict[str, any]]:
        """
        A simple greedy approach to the Knapsack problem for cargo allocation.
        Items are sorted by value/weight ratio.
        items is a list of dicts: {'item_id': str, 'value': float, 'weight': float}
        """
        # Calculate ratio
        for item in items:
            if item.get('weight', 0) == 0:
                item['ratio'] = float('inf')
            else:
                item['ratio'] = item.get('value', 0) / item.get('weight', 0)
                
        # Sort by ratio descending
        sorted_items = sorted(items, key=lambda x: x.get('ratio', 0), reverse=True)
        
        selected_items = []
        current_weight = 0.0
        
        for item in sorted_items:
            if current_weight + item.get('weight', 0) <= max_weight:
                selected_items.append(item)
                current_weight += item.get('weight', 0)
                
        return selected_items
