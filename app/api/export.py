"""
Export routes (CSV) for workflow integration.

Competing tools often expose CSV exports; this makes it easy to push results into
Sheets/Excel without scraping the UI.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models import ArbitrageOpportunity, CraftingOpportunity
from app.db.session import get_db

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/arbitrage.csv")
def export_arbitrage_csv(
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ArbitrageOpportunity)
        .filter(ArbitrageOpportunity.is_active == True)
        .order_by(desc(ArbitrageOpportunity.ev_score), desc(ArbitrageOpportunity.estimated_profit))
        .limit(limit)
        .all()
    )

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "item_id",
            "item_name",
            "source_city",
            "destination_city",
            "buy_price",
            "sell_price",
            "estimated_profit",
            "estimated_margin",
            "ev_score",
            "daily_volume",
            "volume_source",
            "risk_score",
            "volatility",
            "persistence",
            "detected_at",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.item_id,
                r.item_name,
                r.source_city,
                r.destination_city,
                r.buy_price,
                r.sell_price,
                r.estimated_profit,
                r.estimated_margin,
                r.ev_score,
                r.daily_volume,
                r.volume_source,
                r.risk_score,
                r.volatility,
                r.persistence,
                r.detected_at.isoformat() if r.detected_at else "",
            ]
        )

    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=arbitrage.csv"},
    )


@router.get("/crafting.csv")
def export_crafting_csv(
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CraftingOpportunity)
        .filter(CraftingOpportunity.is_active == True)
        .order_by(desc(CraftingOpportunity.ev_score), desc(CraftingOpportunity.profit))
        .limit(limit)
        .all()
    )

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "item_id",
            "item_name",
            "crafting_city",
            "sell_city",
            "craft_cost",
            "sell_price",
            "profit",
            "profit_margin",
            "profit_per_focus",
            "ev_score",
            "daily_volume",
            "volume_source",
            "volatility",
            "persistence",
            "detected_at",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.item_id,
                r.item_name,
                r.crafting_city,
                r.sell_city,
                r.craft_cost,
                r.sell_price,
                r.profit,
                r.profit_margin,
                r.profit_per_focus,
                r.ev_score,
                r.daily_volume,
                r.volume_source,
                r.volatility,
                r.persistence,
                r.detected_at.isoformat() if r.detected_at else "",
            ]
        )

    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=crafting.csv"},
    )

