import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
try:
    import nats
except ImportError:
    nats = None

from app.core.config import settings
from app.db.models import MarketPrice
from app.db.session import get_db_session

log = logging.getLogger(__name__)

LOCATION_MAPPING = {
    7: "Thetford",
    1002: "Lymhurst",
    2004: "Bridgewatch",
    3003: "Martlock",
    3005: "Caerleon",
    3008: "Black Market",
    4002: "Fort Sterling",
    4300: "Brecilien",
}


def _parse_expires(expires_str: str | None) -> datetime | None:
    if not expires_str or expires_str.startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(expires_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _is_equipment_item(item_id: str) -> bool:
    upper = item_id.upper()
    return any(
        k in upper
        for k in [
            "ARMOR", "ROBE", "JACKET", "GARB", "HEAD", "HELMET", "COWL", "CAP", "SHOES", "BOOTS",
            "MAIN_", "2H_", "1H_", "OFF_", "BAG", "CAPE", "MOUNT", "TOOL", "SPEAR", "SWORD", "AXE",
            "BOW", "CROSSBOW", "HAMMER", "MACE", "DAGGER", "STAFF", "FLAIL", "SCYTHE", "HALBERD",
            "CLAW", "KNUCKLES", "SHAPESHIFTER", "QUARTERSTAFF", "SHIELD", "TORCH", "BOOK", "TOME",
        ]
    )


class AlbionNatsClient:
    """
    Production-Grade Hybrid NATS Ingestion Engine.
    1. Reconstructs Live In-Memory Orderbook (LOB) with Level 2 depth per (item, city, quality).
    2. Computes Anti-Bait True Market Price by depth pooling across orderbook layers.
    3. Handles order expirations and purges stale listings.
    4. Provides zero-latency in-memory price feeds for the opportunity scanner.
    5. Batches and persists high-confidence snapshots to the database.
    """

    def __init__(self):
        self.nc = None
        self.sub_orders = None
        self.sub_history = None
        self.sub_gold = None
        self.flush_task = None
        self.purge_task = None
        self._running = False

        # Live In-Memory Level 2 Orderbook: (item_id, city, quality) -> dict
        self.live_orderbook: dict[tuple[str, str, int], dict] = {}
        # Buffer for periodic DB upserts
        self.order_buffer = defaultdict(list)
        # Gold price cache
        self.latest_gold_price: float = 0.0

    async def _error_callback(self, e):
        if self._running:
            err_type = type(e).__name__
            if "Timeout" in err_type or "NoServers" in err_type or "Cancelled" in err_type:
                log.debug(f"[NATS] Connection timeout or retry notification: {err_type}")
            else:
                err_msg = str(e) if str(e).strip() else repr(e)
                log.warning(f"[NATS] Client notification: {err_msg}")

    async def _disconnected_callback(self):
        if self._running:
            log.info("[NATS] Disconnected from server. Reconnecting...")

    async def _reconnected_callback(self):
        if self._running:
            log.info("[NATS] Reconnected to NATS server.")

    async def _closed_callback(self):
        if self._running:
            log.info("[NATS] Connection closed.")

    async def start(self):
        if not settings.enable_nats_ingestion:
            log.info("[NATS] NATS ingestion is disabled in settings.")
            return

        if nats is None:
            log.warning("[NATS] nats-py is not installed. Live NATS streaming disabled.")
            return

        self._running = True
        log.info(f"[NATS] Connecting to {settings.nats_url}...")
        try:
            self.nc = await nats.connect(
                settings.nats_url,
                connect_timeout=6.0,
                reconnect_time_wait=10.0,
                max_reconnect_attempts=60,
                error_cb=self._error_callback,
                disconnected_cb=self._disconnected_callback,
                reconnected_cb=self._reconnected_callback,
                closed_cb=self._closed_callback,
            )
            log.info("[NATS] Connected successfully. Subscribing to market channels...")

            # Subscribe to real-time order stream
            self.sub_orders = await self.nc.subscribe("marketorders.deduped", cb=self.order_message_handler)
            # Subscribe to real-time market history stream
            self.sub_history = await self.nc.subscribe("markethistories.deduped", cb=self.history_message_handler)
            # Subscribe to gold prices
            self.sub_gold = await self.nc.subscribe("goldprices.deduped", cb=self.gold_message_handler)

            # Start background flusher and expiration pruner
            self.flush_task = asyncio.create_task(self._buffer_flusher())
            self.purge_task = asyncio.create_task(self._expiration_purger())
            log.info("[NATS] Real-time LOB orderbook stream active.")
        except Exception as e:
            err_type = type(e).__name__
            if "NoServers" in err_type or "Timeout" in err_type:
                log.warning(f"[NATS] Public NATS server is currently unreachable ({err_type}). Live order stream will reconnect automatically when available.")
            else:
                log.warning(f"[NATS] Failed to start NATS stream: {e}")

    async def stop(self):
        self._running = False
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()
        if self.purge_task and not self.purge_task.done():
            self.purge_task.cancel()

        for sub in (self.sub_orders, self.sub_history, self.sub_gold):
            if sub:
                try:
                    await sub.unsubscribe()
                except Exception:
                    pass

        if self.nc and not self.nc.is_closed:
            try:
                await self.nc.drain()
            except Exception:
                pass
            try:
                await self.nc.close()
            except Exception:
                pass
        log.info("[NATS] Disconnected.")

    async def order_message_handler(self, msg):
        try:
            data_str = msg.data.decode()
            order = json.loads(data_str)

            item_id = order.get("ItemTypeId")
            location_id = order.get("LocationId")
            quality = order.get("QualityLevel", 1)

            if item_id and location_id:
                city = LOCATION_MAPPING.get(location_id)
                if not city:
                    return

                key = (item_id, city, quality)
                self.order_buffer[key].append(order)
                self._update_live_lob(item_id, city, quality, order)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.error(f"[NATS] Error processing order message: {e}")

    async def history_message_handler(self, msg):
        try:
            data_str = msg.data.decode()
            hist = json.loads(data_str)
            # Live market history update: can be used to update 24h volume and price averages
            item_id = hist.get("ItemTypeId")
            location_id = hist.get("LocationId")
            quality = hist.get("QualityLevel", 1)
            city = LOCATION_MAPPING.get(location_id)
            if item_id and city:
                key = (item_id, city, quality)
                if key in self.live_orderbook:
                    lob = self.live_orderbook[key]
                    lob["volume_24h"] = hist.get("ItemCount", lob.get("volume_24h", 0))
                    lob["avg_price_24h"] = hist.get("UnitPriceSilver", 0) / 10000.0
        except Exception:
            pass

    async def gold_message_handler(self, msg):
        try:
            data_str = msg.data.decode()
            gold_data = json.loads(data_str)
            price = gold_data.get("Price", 0)
            if price > 0:
                self.latest_gold_price = price / 10000.0 if price > 100000 else float(price)
        except Exception:
            pass

    def _update_live_lob(self, item_id: str, city: str, quality: int, order: dict):
        """Reconstructs live Level 2 orderbook state for (item_id, city, quality)."""
        key = (item_id, city, quality)
        now = datetime.utcnow()

        if key not in self.live_orderbook:
            self.live_orderbook[key] = {
                "offers": {},  # order_id -> dict
                "requests": {},
                "true_sell_price": 0.0,
                "true_buy_price": 0.0,
                "top_sell_price": 0.0,
                "top_buy_price": 0.0,
                "sell_depth": 0,
                "buy_depth": 0,
                "volume_24h": 0,
                "avg_price_24h": 0.0,
                "last_updated": now,
            }

        lob = self.live_orderbook[key]
        order_id = order.get("Id")
        if not order_id:
            return

        auction_type = order.get("AuctionType")
        unit_price = order.get("UnitPriceSilver", 0) / 10000.0
        amount = order.get("Amount", 0)
        expires = _parse_expires(order.get("Expires"))

        order_entry = {
            "price": unit_price,
            "amount": amount,
            "expires": expires,
            "updated_at": now,
        }

        if auction_type == "offer":
            lob["offers"][order_id] = order_entry
        elif auction_type == "request":
            lob["requests"][order_id] = order_entry

        lob["last_updated"] = now
        self._recalculate_lob_metrics(lob, item_id, city)

    def _recalculate_lob_metrics(self, lob: dict, item_id: str, city: str):
        """Computes true anti-bait sell and buy prices using dynamic depth requirements."""
        is_equip = _is_equipment_item(item_id)
        if city == "Black Market":
            min_sell_vol = 1
            min_buy_vol = 1
        elif is_equip:
            min_sell_vol = getattr(settings, "anti_bait_min_volume_equipment", 3)
            min_buy_vol = getattr(settings, "anti_bait_min_volume_equipment", 3)
        else:
            min_sell_vol = getattr(settings, "anti_bait_min_volume_materials", 20)
            min_buy_vol = getattr(settings, "anti_bait_min_volume_materials", 20)

        # 1. Active Sell Orders (Offers)
        offers = [o for o in lob["offers"].values() if o["price"] > 0 and o["amount"] > 0]
        offers.sort(key=lambda x: x["price"])
        lob["sell_depth"] = sum(o["amount"] for o in offers)

        if offers:
            lob["top_sell_price"] = offers[0]["price"]
            cum_vol = 0
            true_sell = None
            for o in offers:
                cum_vol += o["amount"]
                if cum_vol >= min_sell_vol:
                    true_sell = o["price"]
                    break
            if true_sell is None:
                # Thin liquidity: use weighted average of all available units
                tot_val = sum(o["price"] * o["amount"] for o in offers)
                true_sell = tot_val / lob["sell_depth"] if lob["sell_depth"] > 0 else offers[0]["price"]
            lob["true_sell_price"] = round(true_sell, 2)
        else:
            lob["top_sell_price"] = 0.0
            lob["true_sell_price"] = 0.0

        # 2. Active Buy Orders (Requests)
        requests = [r for r in lob["requests"].values() if r["price"] > 0 and r["amount"] > 0]
        requests.sort(key=lambda x: x["price"], reverse=True)
        lob["buy_depth"] = sum(r["amount"] for r in requests)

        if requests:
            lob["top_buy_price"] = requests[0]["price"]
            cum_vol_buy = 0
            true_buy = None
            for r in requests:
                cum_vol_buy += r["amount"]
                if cum_vol_buy >= min_buy_vol:
                    true_buy = r["price"]
                    break
            if true_buy is None:
                tot_val = sum(r["price"] * r["amount"] for r in requests)
                true_buy = tot_val / lob["buy_depth"] if lob["buy_depth"] > 0 else requests[0]["price"]
            lob["true_buy_price"] = round(true_buy, 2)
        else:
            lob["top_buy_price"] = 0.0
            lob["true_buy_price"] = 0.0

    async def _expiration_purger(self):
        """Periodically removes expired orders from the live orderbook."""
        while self._running:
            interval = getattr(settings, "nats_purge_expired_seconds", 60)
            await asyncio.sleep(interval)
            now = datetime.utcnow()

            keys_to_delete = []
            for key, lob in list(self.live_orderbook.items()):
                item_id, city, _ = key
                is_bm = (city == "Black Market")

                # Dynamic BM request retention ceiling:
                def _get_bm_ttl(order_dict: dict) -> float:
                    if not is_bm:
                        return 86400.0
                    p = order_dict.get("price", 0)
                    up = item_id.upper()

                    # 1. Whale / High-Value Relic Trades (> 20M - 55M+, T8.4, T8.3, T7.4) -> Up to 72 hours
                    is_tier_8_4 = "@4" in up or "LEVEL4" in up or (up.startswith("T8_") and ("@3" in up or "@4" in up))
                    if p >= 35_000_000 or (is_tier_8_4 and p >= 20_000_000):
                        return 259200.0  # 72 hours (3 days)
                    if p >= 20_000_000 or is_tier_8_4:
                        return 129600.0  # 36 hours

                    # 2. Fast-moving mid-tier items (T4.*, T5.0-T5.3, T6.0-T6.2, T7.0-T7.2) -> 10m to 45m
                    is_fast_tier = (
                        up.startswith("T4_")
                        or (up.startswith("T5_") and (any(e in up for e in ["@0", "@1", "@2", "@3", "LEVEL1", "LEVEL2", "LEVEL3"]) or ("@" not in up and "LEVEL" not in up)))
                        or (up.startswith("T6_") and (any(e in up for e in ["@0", "@1", "@2", "LEVEL1", "LEVEL2"]) or ("@" not in up and "LEVEL" not in up)))
                        or (up.startswith("T7_") and (any(e in up for e in ["@0", "@1", "@2", "LEVEL1", "LEVEL2"]) or ("@" not in up and "LEVEL" not in up)))
                    )

                    if is_fast_tier and p < 5_000_000 and "@4" not in up and "LEVEL4" not in up:
                        if p >= 1_500_000:
                            return 2700.0  # 45 minutes
                        elif p >= 500_000:
                            return 1800.0  # 30 minutes
                        elif p >= 200_000:
                            return 1200.0  # 20 minutes
                        else:
                            return 600.0   # 10 minutes

                    # 3. Mid-High Capital Tiers (T6.3, T7.3, T8.0, T8.1, T8.2, 3M - 10M+) -> 1 hour to 12 hours
                    is_mid_high_tier = (
                        (up.startswith("T6_") and ("@3" in up or "LEVEL3" in up))
                        or (up.startswith("T7_") and ("@3" in up or "LEVEL3" in up))
                        or (up.startswith("T8_") and (any(e in up for e in ["@0", "@1", "@2", "LEVEL1", "LEVEL2"]) or ("@" not in up and "LEVEL" not in up)))
                    )

                    if is_mid_high_tier or p >= 3_000_000:
                        if p >= 10_000_000 or "@3" in up:
                            return 43200.0  # 12 hours
                        elif p >= 5_000_000:
                            return 28800.0  # 8 hours
                        elif p >= 3_000_000:
                            return 14400.0  # 4 hours
                        else:
                            return 3600.0   # 1 hour

                    if p >= 1_000_000:
                        return 3600.0  # 1 hour
                    elif p >= 500_000:
                        return 1800.0  # 30 minutes
                    return 600.0  # 10 minutes default

                # Purge expired offers (or BM offers older than 10 minutes)
                lob["offers"] = {
                    oid: o for oid, o in lob["offers"].items()
                    if (o["expires"] is None or o["expires"] > now)
                    and (not is_bm or (now - o.get("updated_at", now)).total_seconds() <= 600)
                }
                # Purge expired requests (dynamic Black Market retention based on tier and price)
                lob["requests"] = {
                    oid: r for oid, r in lob["requests"].items()
                    if (r["expires"] is None or r["expires"] > now)
                    and (now - r.get("updated_at", now)).total_seconds() <= _get_bm_ttl(r)
                }

                if not lob["offers"] and not lob["requests"]:
                    # Orderbook completely empty for over 10 minutes (or 1h for royal)
                    cutoff = 600 if is_bm else 3600
                    if (now - lob["last_updated"]).total_seconds() > cutoff:
                        keys_to_delete.append(key)
                else:
                    self._recalculate_lob_metrics(lob, item_id, city)

            for k in keys_to_delete:
                self.live_orderbook.pop(k, None)

    async def _buffer_flusher(self):
        """Periodically aggregates buffered orders and writes snapshots to the DB."""
        while self._running:
            await asyncio.sleep(2.0)
            if not self.order_buffer:
                continue

            snapshot = dict(self.order_buffer)
            self.order_buffer.clear()

            await asyncio.to_thread(self._process_buffer, snapshot)

    def _process_buffer(self, snapshot):
        from sqlalchemy import func
        from app.shared.utils.market import get_bucket

        now = datetime.utcnow()
        bucket = get_bucket(now)
        records_to_save = []

        for (item_id, city, quality), _ in snapshot.items():
            key = (item_id, city, quality)
            lob = self.live_orderbook.get(key)
            if not lob:
                continue

            true_sell = lob.get("true_sell_price", 0.0)
            true_buy = lob.get("true_buy_price", 0.0)

            if true_sell <= 0 and true_buy <= 0:
                continue

            item_dict = {
                "item_id": item_id,
                "city": city,
                "server": settings.active_server.value,
                "quality": quality,
                "captured_at": now,
                "captured_at_bucket": bucket,
                "data_age_seconds": 0.0,
                "confidence_score": 1.0,
                "coverage_suspect": False,
                "volume_24h": lob.get("volume_24h", 0),
                "sell_price_min": int(true_sell) if true_sell > 0 else None,
                "sell_price_min_date": now if true_sell > 0 else None,
                "buy_price_max": int(true_buy) if true_buy > 0 else None,
                "buy_price_max_date": now if true_buy > 0 else None,
            }
            records_to_save.append(item_dict)

        if not records_to_save:
            return

        deduped = {}
        for item in records_to_save:
            k = (item["item_id"], item["city"], item["quality"], item["captured_at_bucket"])
            if k not in deduped:
                deduped[k] = item
            else:
                if item["sell_price_min"] is not None:
                    deduped[k]["sell_price_min"] = item["sell_price_min"]
                    deduped[k]["sell_price_min_date"] = item["sell_price_min_date"]
                if item["buy_price_max"] is not None:
                    deduped[k]["buy_price_max"] = item["buy_price_max"]
                    deduped[k]["buy_price_max_date"] = item["buy_price_max_date"]

        clean_records = list(deduped.values())
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
            except Exception as e:
                db.rollback()
                log.error(f"[NATS] Error saving buffer to DB: {e}")

    def get_live_prices_dict(self) -> dict[str, dict[str, dict[int, dict]]]:
        """
        Direct in-memory access for OpportunityScanner.
        Returns live orderbook prices in {item_id: {city: {quality: {fields...}}}} format.
        """
        now = datetime.utcnow()
        res: dict[str, dict[str, dict[int, dict]]] = {}

        for (item_id, city, quality), lob in self.live_orderbook.items():
            if item_id not in res:
                res[item_id] = {}
            if city not in res[item_id]:
                res[item_id][city] = {}

            age = max(0, int((now - lob["last_updated"]).total_seconds()))
            res[item_id][city][quality] = {
                "sell_price_min": int(lob["true_sell_price"]) if lob["true_sell_price"] > 0 else int(lob["top_sell_price"]),
                "buy_price_max": int(lob["true_buy_price"]) if lob["true_buy_price"] > 0 else int(lob["top_buy_price"]),
                "volume_24h": lob.get("volume_24h", 0),
                "data_age_seconds": age,
                "is_black_market": city == "Black Market",
                "sell_depth": lob.get("sell_depth", 0),
                "buy_depth": lob.get("buy_depth", 0),
                "avg_price_24h": lob.get("avg_price_24h", 0.0),
            }

        return res

    def get_vwap_for_quantity(
        self, item_id: str, city: str, quality: int = 1, required_qty: int = 1, is_buy: bool = True
    ) -> tuple[float | None, int]:
        """
        Calculates the exact Volume-Weighted Average Price (VWAP) to fill `required_qty` units
        from the live in-memory Level 2 orderbook.
        - If is_buy=True (we are buying), walks sell offers sorted ascending by price.
        - If is_buy=False (we are selling), walks buy requests sorted descending by price.
        Returns (vwap_price, total_depth_available).
        If depth is insufficient, calculates VWAP for available units and extrapolates the remainder
        using a conservative orderbook depth slippage step.
        """
        key = (item_id, city, quality)
        lob = self.live_orderbook.get(key)
        if not lob:
            return (None, 0)

        now = datetime.utcnow()
        if is_buy:
            orders = [
                o for o in lob.get("offers", {}).values()
                if o.get("price", 0) > 0 and o.get("amount", 0) > 0 and (o.get("expires") is None or o.get("expires") > now)
            ]
            orders.sort(key=lambda x: x["price"])
        else:
            orders = [
                r for r in lob.get("requests", {}).values()
                if r.get("price", 0) > 0 and r.get("amount", 0) > 0 and (r.get("expires") is None or r.get("expires") > now)
            ]
            orders.sort(key=lambda x: x["price"], reverse=True)

        if not orders:
            return (None, 0)

        total_depth = sum(o["amount"] for o in orders)
        target_qty = max(1, required_qty)
        cum_qty = 0
        cum_cost = 0.0
        last_price = orders[0]["price"]

        for o in orders:
            price = o["price"]
            amt = o["amount"]
            last_price = price
            take_qty = min(amt, target_qty - cum_qty)
            cum_cost += take_qty * price
            cum_qty += take_qty
            if cum_qty >= target_qty:
                break

        if cum_qty >= target_qty:
            vwap = cum_cost / target_qty
            return (round(vwap, 2), total_depth)

        # Partial depth available: fill remaining deficit with depth step premium
        remaining = target_qty - cum_qty
        deficit_factor = 1.0 + min(0.35, 0.05 * (remaining / float(target_qty)))
        projected_deficit_price = last_price * deficit_factor
        total_projected_cost = cum_cost + (remaining * projected_deficit_price)
        vwap = total_projected_cost / target_qty
        return (round(vwap, 2), total_depth)


nats_client = AlbionNatsClient()
