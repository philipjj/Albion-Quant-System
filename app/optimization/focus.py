"""
Focus Optimization.
Optimizes crafting operations based on silver per focus.
"""

from typing import Dict, List

from app.features.focus_efficiency import calculate_silver_per_focus


class FocusOptimizer:
    def optimize_crafting(self, options: list[dict[str, any]]) -> list[dict[str, any]]:
        """
        Ranks crafting options by silver per focus.
        options is a list of dicts: {'item_id': str, 'profit': float, 'focus_cost': int}
        """
        results = []
        for opt in options:
            spf = calculate_silver_per_focus(opt.get("profit", 0), opt.get("focus_cost", 0))
            results.append(
                {
                    "item_id": opt.get("item_id"),
                    "silver_per_focus": spf,
                    "profit": opt.get("profit"),
                    "focus_cost": opt.get("focus_cost"),
                }
            )

        # Sort by silver per focus descending
        results.sort(key=lambda x: x["silver_per_focus"], reverse=True)
        return results
