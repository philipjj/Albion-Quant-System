from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/fees", tags=["Market Fees"])

@router.get("/")
async def get_market_fees():
    """Returns the current market fee constants used by the AQS engines."""
    return {
        "setup_fee_pct": settings.market_setup_fee_pct * 100,
        "transaction_tax_premium_pct": settings.market_tax_premium_pct * 100,
        "transaction_tax_non_premium_pct": settings.market_tax_non_premium_pct * 100,
        "crafting_station_fee_default_pct": settings.crafting_station_fee_default * 100,
        "note": "Setup fee applies on order creation/edit. Transaction tax applies on sale completion."
    }
