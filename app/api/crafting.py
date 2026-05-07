"""
FastAPI routes for Crafting opportunities.
"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models import CraftingOpportunity
from app.db.session import get_db

router = APIRouter(prefix="/crafting", tags=["Crafting"])


@router.get("/top")
def get_top_crafting(
    limit: int = Query(default=20, le=100),
    sort_by: str = Query(default="profit_margin", enum=["profit_margin", "profit", "profit_per_focus"]),
    db: Session = Depends(get_db),
):
    """Get top crafting opportunities."""
    sort_col = {
        "profit_margin": CraftingOpportunity.profit_margin,
        "profit": CraftingOpportunity.profit,
        "profit_per_focus": CraftingOpportunity.profit_per_focus,
    }.get(sort_by, CraftingOpportunity.profit_margin)

    opps = (
        db.query(CraftingOpportunity)
        .filter(CraftingOpportunity.is_active == True)
        .order_by(desc(sort_col))
        .limit(limit)
        .all()
    )

    return {
        "count": len(opps),
        "sort_by": sort_by,
        "opportunities": [
            {
                "item_id": o.item_id,
                "item_name": o.item_name,
                "crafting_city": o.crafting_city,
                "sell_city": o.sell_city,
                "craft_cost": o.craft_cost,
                "sell_price": o.sell_price,
                "profit": o.profit,
                "profit_margin": o.profit_margin,
                "profit_per_focus": o.profit_per_focus,
                "ev_score": o.ev_score,
                "journal_profit": o.journal_profit,
                "daily_volume": o.daily_volume,
                "volatility": o.volatility,
                "ingredients": json.loads(o.ingredients_json) if o.ingredients_json else [],
                "path": json.loads(o.decision_log) if o.decision_log else [],
                "detected_at": o.detected_at.isoformat() if o.detected_at else None,
            }
            for o in opps
        ],
    }


@router.get("/item/{item_id}")
def get_item_crafting(
    item_id: str,
    db: Session = Depends(get_db),
):
    """Get crafting opportunities for a specific item."""
    opps = (
        db.query(CraftingOpportunity)
        .filter(
            CraftingOpportunity.item_id == item_id,
            CraftingOpportunity.is_active == True,
        )
        .order_by(desc(CraftingOpportunity.profit_margin))
        .all()
    )

    return {
        "item_id": item_id,
        "count": len(opps),
        "opportunities": [
            {
                "crafting_city": o.crafting_city,
                "sell_city": o.sell_city,
                "craft_cost": o.craft_cost,
                "sell_price": o.sell_price,
                "profit": o.profit,
                "profit_margin": o.profit_margin,
                "profit_per_focus": o.profit_per_focus,
                "detected_at": o.detected_at.isoformat() if o.detected_at else None,
            }
            for o in opps
        ],
    }
