"""
Portfolio Optimization.
Combines cargo and capital optimization.
"""

from typing import Dict, List

from app.optimization.capital import CapitalOptimizer
from app.optimization.cargo import CargoOptimizer


class PortfolioOptimizer:
    def __init__(self):
        self.cargo_optimizer = CargoOptimizer()
        self.capital_optimizer = CapitalOptimizer()

    def optimize_portfolio(
        self, opportunities: list[dict[str, any]], max_weight: float, max_capital: float
    ) -> list[dict[str, any]]:
        """
        Optimizes a portfolio of opportunities subject to both weight and capital constraints.
        This is a multi-constraint knapsack problem.
        We'll use a simple heuristic: filter by capital first, then by weight.
        """
        # 1. Optimize by capital
        capital_selected = self.capital_optimizer.optimize_capital(opportunities, max_capital)

        # 2. Optimize by weight among the capital-selected ones
        final_selected = self.cargo_optimizer.optimize_allocation(capital_selected, max_weight)

        return final_selected
