import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.logging import log


def validate_item_id(item_id: str) -> bool:
    """
    Ensures an item ID follows Albion Online naming conventions.
    Rejects malformed strings like 'ARTEFACTT' or double underscores.
    """
    if not item_id or len(item_id) < 2:
        return False
        
    # Pattern: Usually Starts with T1-T8, has underscores, no double underscores, no triple letters like TTT
    # Common typo: ARTEFACTT
    if "ARTEFACTT" in item_id.upper():
        log.warning(f"🛡️ ID_VALIDATOR: Malformed ID detected (ARTEFACTT): {item_id}")
        return False
        
    if "__" in item_id:
        log.warning(f"🛡️ ID_VALIDATOR: Malformed ID detected (Double Underscore): {item_id}")
        return False
        
    # Basic regex for T[1-8]_
    if not re.match(r"^T[1-8]_", item_id.upper()):
        # Some items don't have T prefix (like quest items or tokens), 
        # but for market data we mostly care about T4+
        pass

    return True

def validate_market_record(r: dict[str, Any]) -> bool:
    """
    Validates a raw market record before it hits the database.
    Returns True if valid, False to reject.
    """
    try:
        # 1. Basic Structural Integrity
        item_id = r.get("item_id")
        city = r.get("city")
        if not item_id or not city:
            return False
            
        # 1.1 Canonical ID Check
        if not validate_item_id(item_id):
            return False
            
        sell_price = r.get("sell_price_min", 0) or 0
        buy_price = r.get("buy_price_max", 0) or 0
        
        # 2. Impossible Prices (Zero or Negative)
        if sell_price <= 0 and buy_price <= 0:
            return False # Completely dead data
            
        if sell_price < 0 or buy_price < 0:
            return False
            
        # 3. Quality Validation
        if not (1 <= r.get("quality", 1) <= 5):
            return False
            
        # 4. Strict Spread / Anomaly Detection (Priority 8)
        if sell_price > 0 and buy_price > 0:
            spread_ratio = sell_price / buy_price
            # Hard cap of 25x (2500% spread)
            if spread_ratio > 25 or spread_ratio < 0.01:
                return False

        # 5. Impossible BM Margins
        # If this is a BM virtual record, check if buy_price is sane
        if r["city"] == "Black Market":
            if buy_price > 500_000_000: # 500M silver limit per item
                log.warning(f"🛡️ VALIDATOR: Impossible BM price ({buy_price}) for {r['item_id']}")
                return False

        # 6. Timestamp Validation
        captured_at = r.get("captured_at")
        if captured_at and captured_at > datetime.utcnow():
            log.warning(f"🛡️ VALIDATOR: Future timestamp rejected for {r['item_id']}")
            return False

        return True
        
    except Exception as e:
        log.error(f"🛡️ VALIDATOR: Error during validation: {e}")
        return False

def detect_anomaly(current_price: int, historical_avg: float | None) -> bool:
    """
    Flags sudden price spikes (>5000% change).
    """
    if not historical_avg or historical_avg == 0:
        return False
        
    deviation = abs(current_price - historical_avg) / historical_avg
    if deviation > 50.0: # 5000%
        return True
        
    return False
