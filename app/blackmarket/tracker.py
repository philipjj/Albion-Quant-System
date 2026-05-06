from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import select, and_

from app.db.session import get_db_session
from app.db.models import MarketPrice, MarketSnapshot

class BlackMarketTracker:
    """
    Tracks Black Market specific metrics in Caerleon:
    - Current BM prices
    - Item shortages
    - Refill timing (how fast buy orders are stepping up)
    - Item sink velocity
    """
    def __init__(self):
        self.city_name = "Black Market"

    def get_latest_prices(self, limit: int = 100) -> pd.DataFrame:
        """Fetch the most recent Black Market buy prices."""
        with get_db_session() as db:
            # We care about what the BM is BUYING for (buy_price_max)
            query = select(MarketPrice).where(
                MarketPrice.city == self.city_name
            ).order_by(MarketPrice.fetched_at.desc()).limit(limit)
            
            records = db.execute(query).scalars().all()
            if not records:
                return pd.DataFrame()
                
            data = [{
                'item_id': r.item_id,
                'buy_price': r.buy_price_max,
                'quality': r.quality,
                'fetched_at': r.fetched_at
            } for r in records]
            
            return pd.DataFrame(data)

    def analyze_item_metrics(self, item_id: str, days_back: int = 3) -> dict:
        """
        Analyze shortage, refill timing, and sink velocity for a specific item.
        """
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=days_back)
            query = select(MarketSnapshot).where(
                and_(
                    MarketSnapshot.item_id == item_id,
                    MarketSnapshot.city == self.city_name,
                    MarketSnapshot.snapshot_at >= cutoff
                )
            ).order_by(MarketSnapshot.snapshot_at.asc())
            
            records = db.execute(query).scalars().all()
            
            if len(records) < 2:
                return {
                    "item_id": item_id,
                    "status": "INSUFFICIENT_DATA",
                    "shortage_level": 0.0,
                    "refill_velocity": 0.0,
                    "sink_velocity": 0.0
                }
                
            df = pd.DataFrame([{
                'timestamp': r.snapshot_at,
                'buy_price': r.buy_price_max
            } for r in records])
            
            df.set_index('timestamp', inplace=True)
            
            # 1. Refill Velocity: How fast is the BM buy price rising?
            # Positive value means the BM is getting desperate (price stepping up)
            price_change = df['buy_price'].diff().dropna()
            avg_price_step = price_change[price_change > 0].mean() if not price_change[price_change > 0].empty else 0
            
            # 2. Sink Velocity: How often does the price drop?
            # A price drop means someone fulfilled the order (item was sunk)
            sinks = price_change[price_change < 0]
            sink_count = len(sinks)
            sink_velocity = sink_count / days_back  # Sinks per day
            
            # 3. Shortage Level: If it's rarely sinking and price is stepping up rapidly
            shortage_level = 0.0
            if sink_velocity == 0:
                shortage_level = 1.0  # Total shortage
            elif avg_price_step > 0:
                # Higher steps relative to sink frequency = higher shortage
                shortage_level = min(1.0, (avg_price_step / 1000) / sink_velocity)
                
            return {
                "item_id": item_id,
                "status": "TRACKED",
                "current_bm_price": df['buy_price'].iloc[-1],
                "shortage_level": round(shortage_level, 4),      # 0.0 to 1.0
                "refill_velocity": round(avg_price_step, 2),     # Avg silver increase per step
                "sink_velocity": round(sink_velocity, 2)         # Fulfillments per day
            }
