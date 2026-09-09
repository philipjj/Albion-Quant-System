"""
Greedy knapsack caravan route optimizer for cargo capacity.
"""
from typing import Any
from app.db.session import get_db_session
from app.db.models import ArbitrageOpportunity, Item


def optimize_caravan(src_city: str, dst_city: str, max_weight: float = 1000.0) -> dict[str, Any]:
    """Greedy knapsack transport route optimizer based on profit per kg."""
    with get_db_session() as db:
        opps = (
            db.query(ArbitrageOpportunity)
            .filter(
                ArbitrageOpportunity.is_active == True,
                ArbitrageOpportunity.source_city == src_city,
                ArbitrageOpportunity.destination_city == dst_city,
                ArbitrageOpportunity.estimated_profit > 0,
            )
            .all()
        )

        item_weights = {}
        item_ids = [o.item_id for o in opps]
        if item_ids:
            for it in db.query(Item).filter(Item.item_id.in_(item_ids)).all():
                item_weights[it.item_id] = it.weight or 1.5

    # Compute profit_per_kg
    candidate_items = []
    for o in opps:
        base_id = o.item_id.split("@")[0]
        w = item_weights.get(o.item_id) or item_weights.get(base_id) or 1.5
        profit_per_unit = float(o.estimated_profit)
        profit_per_kg = profit_per_unit / max(w, 0.1)
        safe_qty = max(1, int(o.safe_limit or 1))

        candidate_items.append({
            "item_id": o.item_id,
            "item_name": o.item_name or o.item_id,
            "unit_cost": float(o.buy_price),
            "unit_profit": profit_per_unit,
            "unit_weight": w,
            "profit_per_kg": profit_per_kg,
            "max_qty": safe_qty,
        })

    # Sort descending by profit per kg (greedy knapsack)
    candidate_items.sort(key=lambda x: x["profit_per_kg"], reverse=True)

    remaining_weight = float(max_weight)
    packed_items = []
    total_profit = 0.0
    total_investment = 0.0

    for it in candidate_items:
        if remaining_weight <= 0:
            break
        w = it["unit_weight"]
        if w <= 0:
            continue
        possible_qty = int(remaining_weight // w)
        pack_qty = min(it["max_qty"], possible_qty)
        if pack_qty <= 0:
            continue

        item_weight_total = pack_qty * w
        item_profit_total = pack_qty * it["unit_profit"]
        item_cost_total = pack_qty * it["unit_cost"]

        remaining_weight -= item_weight_total
        total_profit += item_profit_total
        total_investment += item_cost_total

        packed_items.append({
            "item_id": it["item_id"],
            "item_name": it["item_name"],
            "quantity": pack_qty,
            "unit_profit": it["unit_profit"],
            "total_profit": item_profit_total,
            "profit_per_kg": it["profit_per_kg"],
            "weight": item_weight_total,
        })

    used_weight = round(float(max_weight) - remaining_weight, 1)

    return {
        "items": packed_items,
        "used_weight": used_weight,
        "max_weight_capacity": max_weight,
        "total_expected_profit": total_profit,
        "total_investment": total_investment,
    }
