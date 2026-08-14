import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
import nats

from app.core.config import settings
from app.db.models import MarketPrice
from app.db.session import get_db_session

log = logging.getLogger(__name__)

class AlbionNatsClient:
    def __init__(self):
        self.nc = None
        self.sub = None
        # Buffer to group orders by (item_id, location_id, quality_level)
        self.order_buffer = defaultdict(list)
        self.flush_task = None
        self._running = False

    async def _error_callback(self, e):
        log.warning(f"[NATS] Client error: {e}")

    async def _disconnected_callback(self):
        log.warning("[NATS] Disconnected from server. Reconnecting...")

    async def _reconnected_callback(self):
        log.info("[NATS] Reconnected to NATS server.")

    async def _closed_callback(self):
        log.info("[NATS] Connection closed.")

    async def start(self):
        if not settings.enable_nats_ingestion:
            log.info("[NATS] NATS ingestion is disabled.")
            return

        self._running = True
        log.info(f"[NATS] Connecting to {settings.nats_url}...")
        try:
            self.nc = await nats.connect(
                settings.nats_url,
                connect_timeout=10.0,
                reconnect_time_wait=5.0,
                max_reconnect_attempts=60,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback,
            )
            log.info("[NATS] Connected successfully. Subscribing to marketorders.deduped")
            self.sub = await self.nc.subscribe("marketorders.deduped", cb=self.message_handler)
            
            # Start background task to flush buffer every 2 seconds
            self.flush_task = asyncio.create_task(self._buffer_flusher())
        except Exception as e:
            log.error(f"[NATS] Failed to connect: {e}")

    async def stop(self):
        self._running = False
        if self.flush_task:
            self.flush_task.cancel()
        if self.sub:
            try:
                await self.sub.unsubscribe()
            except Exception:
                pass
        if self.nc and not self.nc.is_closed:
            try:
                await self.nc.close()
            except Exception:
                pass
        log.info("[NATS] Disconnected.")

    async def message_handler(self, msg):
        try:
            data_str = msg.data.decode()
            order = json.loads(data_str)
            
            item_id = order.get("ItemTypeId")
            location_id = order.get("LocationId")
            quality = order.get("QualityLevel", 1)
            
            if item_id and location_id:
                key = (item_id, location_id, quality)
                self.order_buffer[key].append(order)
                
        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.error(f"[NATS] Error processing message: {e}")

    async def _buffer_flusher(self):
        """Periodically aggregates buffered orders and writes to the DB."""
        while self._running:
            await asyncio.sleep(2.0)
            if not self.order_buffer:
                continue
                
            # Take a snapshot and clear buffer
            snapshot = dict(self.order_buffer)
            self.order_buffer.clear()
            
            # Process in thread pool to avoid blocking async loop
            await asyncio.to_thread(self._process_buffer, snapshot)

    def _process_buffer(self, snapshot):
        from sqlalchemy import func

        location_mapping = {
            7: "Thetford", 
            1002: "Lymhurst", 
            2004: "Bridgewatch", 
            3003: "Martlock", 
            3005: "Caerleon",
            3008: "Black Market",
            4002: "Fort Sterling",
            4300: "Brecilien"
        }

        now = datetime.utcnow()
        bucket = now.replace(minute=0, second=0, microsecond=0)
        records_to_save = []

        for (item_id, location_id, quality), orders in snapshot.items():
            city = location_mapping.get(location_id)
            if not city:
                continue # Ignore unknown/hideout locations
            
            sell_orders = [o for o in orders if o.get("AuctionType") == "offer"]
            buy_orders = [o for o in orders if o.get("AuctionType") == "request"]
            
            sell_orders.sort(key=lambda x: x.get("UnitPriceSilver", 0))
            buy_orders.sort(key=lambda x: x.get("UnitPriceSilver", 0), reverse=True)
            
            # Calculate Anti-Bait True Sell Price via Depth Pooling
            true_sell_price = None
            cum_vol = 0
            min_vol_required = 1 if city == "Black Market" else settings.anti_bait_min_volume
            is_suspect = False
            
            for order in sell_orders:
                cum_vol += order.get("Amount", 0)
                if cum_vol >= min_vol_required:
                    true_sell_price = order.get("UnitPriceSilver")
                    break
            
            if true_sell_price is None and sell_orders:
                # Thin liquidity: use volume-weighted price of available orders rather than troll order
                total_val = sum(o.get("UnitPriceSilver", 0) * o.get("Amount", 1) for o in sell_orders)
                total_amt = sum(o.get("Amount", 1) for o in sell_orders)
                true_sell_price = total_val / total_amt if total_amt > 0 else sell_orders[0].get("UnitPriceSilver")
                is_suspect = True
                
            # Calculate Anti-Bait True Buy Price via Depth Pooling
            true_buy_price = None
            cum_vol_buy = 0
            for order in buy_orders:
                cum_vol_buy += order.get("Amount", 0)
                if cum_vol_buy >= min_vol_required:
                    true_buy_price = order.get("UnitPriceSilver")
                    break
            
            if true_buy_price is None and buy_orders:
                total_val = sum(o.get("UnitPriceSilver", 0) * o.get("Amount", 1) for o in buy_orders)
                total_amt = sum(o.get("Amount", 1) for o in buy_orders)
                true_buy_price = total_val / total_amt if total_amt > 0 else buy_orders[0].get("UnitPriceSilver")
                is_suspect = True
            
            if true_sell_price is None and true_buy_price is None:
                continue
            
            item_dict = {
                "item_id": item_id,
                "city": city,
                "server": settings.albion_api_server,
                "quality": quality,
                "captured_at": now,
                "captured_at_bucket": bucket,
                "data_age_seconds": 0.0,
                "confidence_score": 0.7 if is_suspect else 1.0,
                "coverage_suspect": is_suspect,
                "volume_24h": 0,
                "sell_price_min": true_sell_price / 10000.0 if true_sell_price is not None else None,
                "sell_price_min_date": now if true_sell_price is not None else None,
                "buy_price_max": true_buy_price / 10000.0 if true_buy_price is not None else None,
                "buy_price_max_date": now if true_buy_price is not None else None,
            }
            records_to_save.append(item_dict)

        if not records_to_save:
            return

        # Deduplicate in-memory by primary index key to avoid conflicting rows in same batch
        deduped = {}
        for item in records_to_save:
            key = (item["item_id"], item["city"], item["quality"], item["captured_at_bucket"])
            if key not in deduped:
                deduped[key] = item
            else:
                if item["sell_price_min"] is not None:
                    deduped[key]["sell_price_min"] = item["sell_price_min"]
                    deduped[key]["sell_price_min_date"] = item["sell_price_min_date"]
                if item["buy_price_max"] is not None:
                    deduped[key]["buy_price_max"] = item["buy_price_max"]
                    deduped[key]["buy_price_max_date"] = item["buy_price_max_date"]

        clean_records = list(deduped.values())
        updates = len(clean_records)
        CHUNK_SIZE = 200

        with get_db_session() as db:
            try:
                for j in range(0, len(clean_records), CHUNK_SIZE):
                    chunk = clean_records[j : j + CHUNK_SIZE]

                    if settings.database_url.startswith("sqlite"):
                        from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

                        stmt = sqlite_upsert(MarketPrice).values(chunk)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["item_id", "city", "quality", "captured_at_bucket"],
                            set_={
                                "captured_at": stmt.excluded.captured_at,
                                "data_age_seconds": 0.0,
                                "sell_price_min": func.coalesce(stmt.excluded.sell_price_min, MarketPrice.sell_price_min),
                                "sell_price_min_date": func.coalesce(stmt.excluded.sell_price_min_date, MarketPrice.sell_price_min_date),
                                "buy_price_max": func.coalesce(stmt.excluded.buy_price_max, MarketPrice.buy_price_max),
                                "buy_price_max_date": func.coalesce(stmt.excluded.buy_price_max_date, MarketPrice.buy_price_max_date),
                            },
                        )
                    else:
                        from sqlalchemy.dialects.postgresql import insert as pg_upsert

                        stmt = pg_upsert(MarketPrice).values(chunk)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["item_id", "city", "quality", "captured_at_bucket"],
                            set_={
                                "captured_at": stmt.excluded.captured_at,
                                "data_age_seconds": 0.0,
                                "sell_price_min": func.coalesce(stmt.excluded.sell_price_min, MarketPrice.sell_price_min),
                                "sell_price_min_date": func.coalesce(stmt.excluded.sell_price_min_date, MarketPrice.sell_price_min_date),
                                "buy_price_max": func.coalesce(stmt.excluded.buy_price_max, MarketPrice.buy_price_max),
                                "buy_price_max_date": func.coalesce(stmt.excluded.buy_price_max_date, MarketPrice.buy_price_max_date),
                            },
                        )

                    db.execute(stmt)

                db.commit()
                log.info(f"[NATS] Processed and saved {updates} True Price updates (anti-bait applied).")
            except Exception as e:
                db.rollback()
                log.error(f"[NATS] Error saving to DB: {e}")

nats_client = AlbionNatsClient()
