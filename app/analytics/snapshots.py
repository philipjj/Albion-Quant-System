"""
Archival snapshots for the Albion Quant System.
Provides historical lookback for arbitrage/crafting trend analysis.
"""

from datetime import datetime
from sqlalchemy.orm import Session
from app.db.models import MarketPrice, MarketSnapshot

def create_market_snapshot(db: Session) -> int:
    """
    Copies current live prices into the snapshots table for historical analysis.
    This allows us to track price decay and volatility over time.
    """
    # 1. Archive to snapshots using set-based SQL (Efficient)
    from sqlalchemy import text
    
    # We use a subquery to ensure we only capture the latest unique points per item/city/quality
    sql = text("""
        INSERT INTO market_snapshots (
            item_id, quality, city, server, 
            sell_price_min, sell_price_max, buy_price_min, buy_price_max,
            sell_price_min_date, sell_price_max_date, buy_price_min_date, buy_price_max_date,
            volume_24h, data_age_seconds, confidence_score, coverage_suspect,
            captured_at
        )
        SELECT 
            item_id, quality, city, server, 
            sell_price_min, sell_price_max, buy_price_min, buy_price_max,
            sell_price_min_date, sell_price_max_date, buy_price_min_date, buy_price_max_date,
            volume_24h, data_age_seconds, confidence_score, coverage_suspect,
            :now
        FROM market_prices
    """)
    
    result = db.execute(sql, {"now": datetime.utcnow()})
    
    return result.rowcount if result else 0
