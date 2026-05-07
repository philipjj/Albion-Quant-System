from datetime import datetime, timedelta
from typing import Optional

from app.core.logging import log
from app.core.safe_ops import safe_int

# Freshness Thresholds (Seconds)
THRESHOLD_HIGH_VOLUME = 1800   # 30 Minutes
THRESHOLD_MED_VOLUME = 3600    # 60 Minutes
THRESHOLD_LOW_VOLUME = 10800   # 3 Hours

def is_market_data_fresh(
    item_id: str, 
    age_seconds: int | None, 
    volume_24h: int | None = 0,
    tier: int | None = 4
) -> bool:
    """
    Determines if market data is fresh enough to be used for scoring.
    Logic is dynamic based on liquidity and item tier.
    """
    if age_seconds is None:
        return False
        
    v24 = safe_int(volume_24h)
    t = safe_int(tier, default=4)

    # 1. Determine Threshold
    if v24 > 500:
        threshold = THRESHOLD_HIGH_VOLUME
    elif v24 > 50:
        threshold = THRESHOLD_MED_VOLUME
    else:
        threshold = THRESHOLD_LOW_VOLUME
        
    # 2. Tier-based adjustment
    if t >= 7:
        threshold += 1800 
        
    is_fresh = age_seconds <= threshold
    
    if not is_fresh:
        log.debug(f"🗑️ FRESHNESS: Rejected {item_id} (Age: {age_seconds}s, Threshold: {threshold}s)")
        
    return is_fresh
