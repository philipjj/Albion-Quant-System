from sqlalchemy.orm import Session
from app.db.session import get_db_session
from app.db.models import MarketPrice
from app.core.config import settings
from app.shared.domain.repository import IMarketDataRepository
from app.shared.domain.market_snapshot import MarketSnapshot
from app.shared.utils.market import get_bucket

class SQLiteMarketDataRepository(IMarketDataRepository):
    async def save_snapshots(self, snapshots: list[MarketSnapshot]) -> None:
        if not snapshots:
            return
            
        market_to_save = []
        for s in snapshots:
            bucket = get_bucket(s.timestamp)
            market_to_save.append({
                "item_id": s.item_id,
                "city": s.city,
                "quality": s.quality,
                "server": settings.active_server.value,
                "sell_price_min": int(s.best_ask) if s.best_ask else 0,
                "buy_price_max": int(s.best_bid) if s.best_bid else 0,
                "volume_24h": s.rolling_volume,
                "captured_at": s.timestamp,
                "captured_at_bucket": bucket,
                "data_age_seconds": 0.0,
                "confidence_score": 1.0,
                "coverage_suspect": False
            })
            
        # Deduplicate to avoid "ON CONFLICT DO UPDATE command cannot affect row a second time"
        # We keep the latest one if there are duplicates in the same batch
        deduped = {}
        for item in market_to_save:
            key = (item["item_id"], item["city"], item["quality"], item["captured_at_bucket"])
            if key not in deduped or item["captured_at"] > deduped[key]["captured_at"]:
                deduped[key] = item
                
        market_to_save = list(deduped.values())
            
        CHUNK_SIZE = 200
        with get_db_session() as db:
            for j in range(0, len(market_to_save), CHUNK_SIZE):
                chunk = market_to_save[j : j + CHUNK_SIZE]
                
                if settings.database_url.startswith("sqlite"):
                    from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
                    stmt = sqlite_upsert(MarketPrice).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['item_id', 'city', 'quality', 'captured_at_bucket'],
                        set_={
                            "sell_price_min": stmt.excluded.sell_price_min, 
                            "buy_price_max": stmt.excluded.buy_price_max, 
                            "volume_24h": stmt.excluded.volume_24h,
                            "captured_at": stmt.excluded.captured_at
                        }
                    )
                else:
                    from sqlalchemy.dialects.postgresql import insert as pg_upsert
                    stmt = pg_upsert(MarketPrice).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['item_id', 'city', 'quality', 'captured_at_bucket'],
                        set_={
                            "sell_price_min": stmt.excluded.sell_price_min, 
                            "buy_price_max": stmt.excluded.buy_price_max, 
                            "volume_24h": stmt.excluded.volume_24h,
                            "captured_at": stmt.excluded.captured_at
                        }
                    )
                
                db.execute(stmt)
                
    async def get_latest_snapshot(self, item_id: str, city: str) -> MarketSnapshot | None:
        with get_db_session() as db:
            row = (
                db.query(MarketPrice)
                .filter(
                    MarketPrice.item_id == item_id,
                    MarketPrice.city == city
                )
                .order_by(MarketPrice.captured_at.desc())
                .first()
            )
            
            if not row:
                return None
                
            return MarketSnapshot(
                item_id=row.item_id,
                city=row.city,
                quality=row.quality,
                timestamp=row.captured_at,
                best_bid=float(row.buy_price_max or 0),
                best_ask=float(row.sell_price_min or 0),
                bid_depth=0, # Not stored in DB
                ask_depth=0, # Not stored in DB
                spread=float((row.sell_price_min or 0) - (row.buy_price_max or 0)),
                midprice=float(((row.sell_price_min or 0) + (row.buy_price_max or 0)) / 2),
                rolling_volume=row.volume_24h or 0,
                volatility=0.0 # Not stored in DB
            )
            
    async def get_historical_prices(self, item_id: str, city: str, limit: int = 100, quality: int = 1) -> list[float]:
        with get_db_session() as db:
            rows = (
                db.query(MarketPrice)
                .filter(
                    MarketPrice.item_id == item_id,
                    MarketPrice.city == city,
                    MarketPrice.quality == quality
                )
                .order_by(MarketPrice.captured_at.desc())
                .limit(limit)
                .all()
            )
            
            # Reverse to get chronological order
            rows.reverse()
            
            prices = []
            for row in rows:
                sell = row.sell_price_min or 0
                buy = row.buy_price_max or 0
                if sell > 0 and buy > 0:
                    prices.append((sell + buy) / 2.0)
                elif sell > 0:
                    prices.append(float(sell))
                elif buy > 0:
                    prices.append(float(buy))
                    
            return prices
            
    async def update_volume(self, item_id: str, city: str, quality: int, volume: int) -> None:
        with get_db_session() as db:
            record = db.query(MarketPrice).filter(
                MarketPrice.item_id == item_id,
                MarketPrice.city == city,
                MarketPrice.quality == quality
            ).order_by(MarketPrice.captured_at.desc()).first()
            
            if record:
                record.volume_24h = volume
