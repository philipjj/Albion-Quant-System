"""
Data quality metrics for the Albion Quant system.

Goal: make every output defensible by exposing freshness/coverage signals rather
than claiming "real-time" data from a player-sourced API.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MarketPrice
from app.core.config import settings


def quality_snapshot(db: Session, lookback_hours: int = 2) -> dict[str, Any]:
    """
    Compute a lightweight view of data freshness and city coverage.

    The scanner/engine use a 2h window for "recent enough" prices, so this aligns
    operational metrics with decision logic.
    """
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
    server = settings.active_server.value

    last_fetch = db.query(func.max(MarketPrice.captured_at)).filter(MarketPrice.server == server).scalar()
    recent_points = (
        db.query(func.count(MarketPrice.id))
        .filter(MarketPrice.captured_at >= cutoff, MarketPrice.server == server)
        .scalar()
        or 0
    )

    by_city = (
        db.query(MarketPrice.city, func.count(MarketPrice.id).label("points"))
        .filter(MarketPrice.captured_at >= cutoff, MarketPrice.server == server)
        .group_by(MarketPrice.city)
        .all()
    )

    # Normalize to a dict for easy rendering in API/Discord.
    city_points = {city: int(points) for city, points in by_city}

    age_minutes = None
    if last_fetch:
        age_minutes = round((datetime.utcnow() - last_fetch).total_seconds() / 60.0, 2)

    return {
        "window_hours": lookback_hours,
        "server": server,
        "last_fetched_at": last_fetch.isoformat() if last_fetch else None,
        "age_minutes": age_minutes,
        "recent_points": int(recent_points),
        "points_by_city": city_points,
    }
