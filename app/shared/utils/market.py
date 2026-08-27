"""
Market utility functions for Albion Online.
Delegates to the authoritative app.core.market_utils implementation to prevent logic divergence.
"""

from datetime import datetime

# Re-export authoritative bonus structures and math from core
from app.core.market_utils import (
    CITY_BONUS,
    BASE_CITY_PRODUCTION_BONUS,
    REFINING_SPECIALIZATION_BONUS,
    CRAFTING_SPECIALIZATION_BONUS,
    FOCUS_PRODUCTION_BONUS,
    calculate_rrr,
    calculate_liquidity_confidence,
    calculate_blended_price,
    calculate_z_score,
    get_refining_category,
    get_item_crafting_subcategory,
)


def calculate_net_material_cost(
    material_price: int,
    quantity: int,
    location: str,
    item_category: str,
    tier: int = 4,
    use_focus: bool = False,
    daily_bonus: int = 0,
) -> dict:
    """Effective material cost after resource returns."""
    rrr = calculate_rrr(location, item_category, tier, use_focus, daily_bonus)
    net_quantity = quantity * (1.0 - rrr)
    net_cost = round(material_price * net_quantity)

    return {
        "gross_quantity": quantity,
        "rrr": rrr,
        "net_quantity": round(net_quantity, 4),
        "material_price": material_price,
        "net_cost": net_cost,
    }


def get_bucket(dt: datetime, window_min: int = 5) -> datetime:
    """Rounds a datetime to the nearest window_min bucket."""
    minute = (dt.minute // window_min) * window_min
    return dt.replace(minute=minute, second=0, microsecond=0)


def parse_timestamp(ts: str | None) -> datetime | None:
    """Parses ISO timestamp string into datetime."""
    if not ts or ts.startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

