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

    async def start(self):
        if not settings.enable_nats_ingestion:
            log.info("[NATS] NATS ingestion is disabled.")
            return

        self._running = True
        log.info(f"[NATS] Connecting to {settings.nats_url}...")
        try:
            self.nc = await nats.connect(settings.nats_url)
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
            await self.sub.unsubscribe()
        if self.nc and not self.nc.is_closed:
            await self.nc.close()
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

        updates = 0
        with get_db_session() as db:
            for (item_id, location_id, quality), orders in snapshot.items():
                city = location_mapping.get(location_id)
                if not city:
                    continue # Ignore unknown/hideout locations
                
                sell_orders = [o for o in orders if o.get("AuctionType") == "offer"]
                buy_orders = [o for o in orders if o.get("AuctionType") == "request"]
                
                sell_orders.sort(key=lambda x: x.get("UnitPriceSilver", 0))
                buy_orders.sort(key=lambda x: x.get("UnitPriceSilver", 0), reverse=True)
                
                # Calculate Anti-Bait True Sell Price
                true_sell_price = None
                cum_vol = 0
                min_vol_required = 1 if city == "Black Market" else settings.anti_bait_min_volume
                
                for order in sell_orders:
                    cum_vol += order.get("Amount", 0)
                    if cum_vol >= min_vol_required:
                        true_sell_price = order.get("UnitPriceSilver")
                        break
                
                # Fallback to the highest available bait price if liquidity is extremely low
                if true_sell_price is None and sell_orders:
                    true_sell_price = sell_orders[-1].get("UnitPriceSilver") 
                    
                # Calculate Anti-Bait True Buy Price
                true_buy_price = None
                cum_vol_buy = 0
                for order in buy_orders:
                    cum_vol_buy += order.get("Amount", 0)
                    if cum_vol_buy >= min_vol_required:
                        true_buy_price = order.get("UnitPriceSilver")
                        break
                
                if true_buy_price is None and buy_orders:
                    true_buy_price = buy_orders[-1].get("UnitPriceSilver")
                
                if true_sell_price is None and true_buy_price is None:
                    continue
                
                now = datetime.utcnow()
                bucket = now.replace(minute=0, second=0, microsecond=0)
                
                update_dict = {}
                # In NATS, UnitPriceSilver is always exact silver * 10000.
                if true_sell_price is not None:
                    update_dict["sell_price_min"] = true_sell_price / 10000.0
                    update_dict["sell_price_min_date"] = now
                if true_buy_price is not None:
                    update_dict["buy_price_max"] = true_buy_price / 10000.0
                    update_dict["buy_price_max_date"] = now
                
                record = db.query(MarketPrice).filter_by(
                    item_id=item_id,
                    city=city,
                    quality=quality,
                    captured_at_bucket=bucket
                ).first()
                
                if record:
                    if "sell_price_min" in update_dict:
                        record.sell_price_min = update_dict["sell_price_min"]
                        record.sell_price_min_date = update_dict["sell_price_min_date"]
                    if "buy_price_max" in update_dict:
                        record.buy_price_max = update_dict["buy_price_max"]
                        record.buy_price_max_date = update_dict["buy_price_max_date"]
                    record.captured_at = now
                    record.data_age_seconds = 0
                else:
                    new_record = MarketPrice(
                        item_id=item_id,
                        city=city,
                        server=settings.albion_api_server,
                        quality=quality,
                        captured_at=now,
                        captured_at_bucket=bucket,
                        data_age_seconds=0,
                        **update_dict
                    )
                    db.add(new_record)
                
                updates += 1
            
            if updates > 0:
                try:
                    db.commit()
                    log.info(f"[NATS] Processed and saved {updates} True Price updates (anti-bait applied).")
                except Exception as e:
                    db.rollback()
                    log.error(f"[NATS] Error saving to DB: {e}")

nats_client = AlbionNatsClient()
