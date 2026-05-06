"""
FastAPI routes for Arbitrage opportunities.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import ArbitrageOpportunity

router = APIRouter(prefix="/arbitrage", tags=["Arbitrage"])


@router.get("/top")
def get_top_arbitrage(
    limit: int = Query(default=20, le=100),
    min_margin: float = Query(default=12.0),
    db: Session = Depends(get_db),
):
    """Get top arbitrage opportunities by margin."""
    opps = (
        db.query(ArbitrageOpportunity)
        .filter(
            ArbitrageOpportunity.is_active == True,
            ArbitrageOpportunity.estimated_margin >= min_margin,
        )
        .order_by(desc(ArbitrageOpportunity.estimated_margin))
        .limit(limit)
        .all()
    )

    return {
        "count": len(opps),
        "opportunities": [
            {
                "item_id": o.item_id,
                "item_name": o.item_name,
                "source_city": o.source_city,
                "destination_city": o.destination_city,
                "buy_price": o.buy_price,
                "sell_price": o.sell_price,
                "estimated_profit": o.estimated_profit,
                "estimated_margin": o.estimated_margin,
                "risk_score": o.risk_score,
                "detected_at": o.detected_at.isoformat() if o.detected_at else None,
            }
            for o in opps
        ],
    }


@router.get("/item/{item_id}")
def get_item_arbitrage(
    item_id: str,
    db: Session = Depends(get_db),
):
    """Get arbitrage opportunities for a specific item."""
    opps = (
        db.query(ArbitrageOpportunity)
        .filter(
            ArbitrageOpportunity.item_id == item_id,
            ArbitrageOpportunity.is_active == True,
        )
        .order_by(desc(ArbitrageOpportunity.estimated_margin))
        .all()
    )

    return {
        "item_id": item_id,
        "count": len(opps),
        "opportunities": [
            {
                "source_city": o.source_city,
                "destination_city": o.destination_city,
                "buy_price": o.buy_price,
                "sell_price": o.sell_price,
                "estimated_profit": o.estimated_profit,
                "estimated_margin": o.estimated_margin,
                "risk_score": o.risk_score,
                "detected_at": o.detected_at.isoformat() if o.detected_at else None,
            }
            for o in opps
        ],
    }
