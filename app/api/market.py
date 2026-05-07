"""
FastAPI routes for Market data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db.models import Item, MarketPrice
from app.db.session import get_db

router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/item/{item_id}")
def get_item_prices(
    item_id: str,
    db: Session = Depends(get_db),
):
    """Get latest market prices for an item across all cities."""
    subq = (
        db.query(
            MarketPrice.city,
            func.max(MarketPrice.captured_at).label("latest"),
        )
        .filter(MarketPrice.item_id == item_id)
        .group_by(MarketPrice.city)
        .subquery()
    )

    prices = (
        db.query(MarketPrice)
        .join(subq, (MarketPrice.city == subq.c.city) & (MarketPrice.captured_at == subq.c.latest))
        .filter(MarketPrice.item_id == item_id)
        .all()
    )

    item = db.query(Item).filter_by(item_id=item_id).first()
    item_name = item.name if item else item_id

    return {
        "item_id": item_id,
        "item_name": item_name,
        "prices": [
            {
                "city": p.city,
                "sell_price_min": p.sell_price_min,
                "buy_price_max": p.buy_price_max,
                "quality": p.quality,
                "volume_24h": p.volume_24h,
                "captured_at": p.captured_at,
                "server": p.server,
            }
            for p in prices
        ],
    }


@router.get("/latest")
def get_latest_updates(
    limit: int = Query(default=50, le=500),
    db: Session = Depends(get_db),
):
    """Get most recently captured price records."""
    prices = (
        db.query(MarketPrice)
        .order_by(desc(MarketPrice.captured_at))
        .limit(limit)
        .all()
    )
    return prices
