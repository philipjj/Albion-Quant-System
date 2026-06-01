"""
Caravan Route Optimizer
Calculates the optimal mix of items to transport between two cities
to maximize profit within a given weight limit (Knapsack approach).
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.models import ArbitrageOpportunity, Item
from app.db.session import get_db_session


def optimize_caravan(
    source_city: str, dest_city: str, max_weight: float, min_profit_per_kg: float = 0.0
) -> dict:
    """
    Finds the optimal set of arbitrage opportunities for a transport run.
    Uses a greedy algorithm based on Profit-per-Kilogram.
    """
    with get_db_session() as db:
        # Get active opportunities between the two cities
        opps = (
            db.query(ArbitrageOpportunity, Item.weight)
            .join(Item, ArbitrageOpportunity.item_id == Item.item_id)
            .filter(
                ArbitrageOpportunity.source_city == source_city,
                ArbitrageOpportunity.destination_city == dest_city,
                ArbitrageOpportunity.is_active == True,
                ArbitrageOpportunity.estimated_profit > 0,
            )
            .all()
        )

    items_to_evaluate = []

    for opp, weight in opps:
        if weight <= 0:
            weight = 0.1  # Fallback to prevent division by zero

        profit = opp.estimated_profit
        profit_per_kg = profit / weight

        if profit_per_kg >= min_profit_per_kg:
            items_to_evaluate.append(
                {
                    "item_id": opp.item_id,
                    "item_name": opp.item_name,
                    "profit_per_unit": profit,
                    "weight_per_unit": weight,
                    "profit_per_kg": profit_per_kg,
                    "max_quantity": opp.safe_limit,
                    "buy_price": opp.buy_price,
                    "sell_price": opp.sell_price,
                }
            )

    # Sort by profit per kg (descending)
    items_to_evaluate.sort(key=lambda x: x["profit_per_kg"], reverse=True)

    total_weight = 0.0
    total_profit = 0.0
    total_investment = 0.0
    selected_items = []

    for item in items_to_evaluate:
        remaining_weight = max_weight - total_weight
        if remaining_weight <= 0:
            break

        # How many can we fit?
        max_fit = int(remaining_weight // item["weight_per_unit"])

        # How many should we take? (limited by safe_limit)
        qty_to_take = min(max_fit, item["max_quantity"])

        if qty_to_take > 0:
            item_weight = qty_to_take * item["weight_per_unit"]
            item_profit = qty_to_take * item["profit_per_unit"]
            item_cost = qty_to_take * item["buy_price"]

            total_weight += item_weight
            total_profit += item_profit
            total_investment += item_cost

            selected_items.append(
                {
                    "item_id": item["item_id"],
                    "item_name": item["item_name"],
                    "quantity": qty_to_take,
                    "total_weight": round(item_weight, 2),
                    "total_profit": round(item_profit, 2),
                    "total_cost": item_cost,
                    "profit_per_kg": round(item["profit_per_kg"], 2),
                }
            )

    return {
        "source": source_city,
        "destination": dest_city,
        "max_weight_capacity": max_weight,
        "used_weight": round(total_weight, 2),
        "total_expected_profit": round(total_profit, 2),
        "total_investment": total_investment,
        "items": selected_items,
    }
