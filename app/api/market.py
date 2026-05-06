"""
FastAPI routes for Market data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import MarketPrice, Item

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
            func.max(MarketPrice.fetched_at).label("latest"),
        )
        .filter(MarketPrice.item_id == item_id)
        .group_by(MarketPrice.city)
        .subquery()
    )

    prices = (
        db.query(MarketPrice)
        .join(subq, (MarketPrice.city == subq.c.city) & (MarketPrice.fetched_at == subq.c.latest))
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
                "fetched_at": p.fetched_at.isoformat() if p.fetched_at else None,
            }
            for p in prices
        ],
    }


@router.get("/top-volume")
def get_top_volume(
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """Get items with the most market activity (price data points)."""
    results = (
        db.query(
            MarketPrice.item_id,
            func.count(MarketPrice.id).label("data_points"),
            func.avg(MarketPrice.sell_price_min).label("avg_sell"),
        )
        .filter(MarketPrice.sell_price_min > 0)
        .group_by(MarketPrice.item_id)
        .order_by(desc("data_points"))
        .limit(limit)
        .all()
    )

    items = []
    for r in results:
        item = db.query(Item).filter_by(item_id=r[0]).first()
        items.append({
            "item_id": r[0],
            "item_name": item.name if item else r[0],
            "data_points": r[1],
            "avg_sell_price": round(r[2], 0) if r[2] else 0,
        })

    return {"top_volume_items": items}


@router.get("/trending")
def get_trending(
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """Get items with the highest price variance (potential opportunities)."""
    results = (
        db.query(
            MarketPrice.item_id,
            func.max(MarketPrice.sell_price_min).label("max_sell"),
            func.min(MarketPrice.sell_price_min).label("min_sell"),
            func.count(MarketPrice.id).label("count"),
        )
        .filter(MarketPrice.sell_price_min > 0)
        .group_by(MarketPrice.item_id)
        .having(func.count(MarketPrice.id) >= 2)
        .all()
    )

    trending = []
    for r in results:
        if r[2] > 0:
            spread = ((r[1] - r[2]) / r[2]) * 100
            item = db.query(Item).filter_by(item_id=r[0]).first()
            trending.append({
                "item_id": r[0],
                "item_name": item.name if item else r[0],
                "max_sell": r[1],
                "min_sell": r[2],
                "spread_pct": round(spread, 2),
                "data_points": r[3],
            })

    trending.sort(key=lambda x: x["spread_pct"], reverse=True)
    return {"trending_items": trending[:limit]}
