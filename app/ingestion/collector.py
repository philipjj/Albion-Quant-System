"""
Market Data Collector v3.1 — Professional Edition
=================================================
Optimized for high-throughput regional data ingestion.
1. Deterministic Pacing (Rate Limiter)
2. Centralized HTTP Client (AQSHttpClient)
3. Integrity & Freshness Filtering
4. UPSERT Logic for Deduplication
"""

import asyncio
from datetime import datetime
from typing import Any, Optional, cast

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import AlbionServer, settings
from app.core.constants import CITY_API_NAMES
from app.core.freshness import is_market_data_fresh
from app.core.logging import log
from app.core.validators import validate_item_id, validate_market_record
from app.db.models import BlackMarketSnapshot, Item, MarketPrice
from app.db.session import get_db_session
from app.services.http_client import aqs_http
from app.services.rate_limiter import limiter

from app.shared.domain.repository import IMarketDataRepository
from app.shared.domain.market_snapshot import MarketSnapshot


def parse_timestamp(ts: str) -> datetime | None:
    if not ts or ts == "0001-01-01T00:00:00":
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except:
        return None

def get_bucket(dt: datetime, window_min: int = 5) -> datetime:
    """Rounds a datetime to the nearest window_min bucket."""
    minute = (dt.minute // window_min) * window_min
    return dt.replace(minute=minute, second=0, microsecond=0)

class MarketCollector:
    """
    Production-grade AQS v3.1+ Collector.
    Phase 1: Deterministic pacing.
    Phase 2: Integrity & Freshness filtering.
    Phase 3: O(n) performance scaling.
    """
    def __init__(self, repository: IMarketDataRepository = None, parquet_storage = None, redis_cache = None):
        self.base_url = settings.aodp_base_urls.get(settings.active_server, "https://europe.albion-online-data.com")
        self.active_server = settings.active_server
        self._stop_requested = False
        if repository is None:
            from app.db.repository import SQLiteMarketDataRepository
            self.repository = SQLiteMarketDataRepository()
        else:
            self.repository = repository
            
        if parquet_storage is None:
            from app.storage.parquet_storage import ParquetHistoricalStorage
            self.parquet_storage = ParquetHistoricalStorage()
        else:
            self.parquet_storage = parquet_storage
            
        if redis_cache is None:
            from app.storage.redis_cache import RedisCache
            self.redis_cache = RedisCache(settings.redis_url)
        else:
            self.redis_cache = redis_cache

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def request_stop(self):
        self._stop_requested = True

    async def fetch_market_data(self, city: str, item_ids: list[str]) -> list[dict]:
        """Queries AODP prices endpoint using the centralized HTTP service."""
        ids_str  = ",".join(item_ids)
        url      = f"{self.base_url}/api/v2/stats/prices/{ids_str}.json"
        params   = {"locations": city, "qualities": "1,2,3,4,5"}

        resp = await aqs_http.get(url, params=params)
        if not resp or resp.status_code != 200:
            return []

        raw = resp.json()
        results = []
        for item in raw:
            item_id = item.get("item_id", "")
            
            # Age calculation
            dates = [item.get("sell_price_min_date"), item.get("buy_price_max_date")]
            parsed_dates = [parse_timestamp(d) for d in dates if d]
            parsed_dates = [d for d in parsed_dates if d is not None]
            age_sec = None
            if parsed_dates:
                latest_date = max(parsed_dates)
                age_sec = int((datetime.utcnow().replace(tzinfo=latest_date.tzinfo) - latest_date).total_seconds())

            results.append({
                "item_id":            item_id,
                "city":               item.get("city", city),
                "server":             self.active_server.value,
                "sell_price_min":     item.get("sell_price_min"),
                "sell_price_max":     item.get("sell_price_max"),
                "buy_price_min":      item.get("buy_price_min"),
                "buy_price_max":      item.get("buy_price_max"),
                "sell_price_min_date": parse_timestamp(item.get("sell_price_min_date")),
                "buy_price_max_date":  parse_timestamp(item.get("buy_price_max_date")),
                "quality":            item.get("quality", 1),
                "data_age_seconds":   age_sec,
                "volume_24h":         1, # Replaced 0 with 1 to prevent downstream fallbacks
                "coverage_suspect":   False
            })
        return results

    async def fetch_volume_data(self, city: str, item_ids: list[str]) -> dict[str, int]:
        """Fetches 24-hour volume using the centralized HTTP service."""
        if not item_ids: return {}
        
        ids_str = ",".join(item_ids)
        url = f"{self.base_url}/api/v2/stats/history/{ids_str}.json?locations={city}&time-scale=24&qualities=1,2,3,4,5"

        resp = await aqs_http.get(url)
        if not resp or resp.status_code != 200:
            return {}

        raw = resp.json()
        volume_map = {}
        for record in raw:
            data = record.get("data", [])
            if not data: continue
            valid_data = [d for d in data if d.get("timestamp")]
            if not valid_data: continue
            latest = max(valid_data, key=lambda x: x.get("timestamp"))
            key = f"{record.get('item_id', '')}:{record.get('quality', 1)}"
            
            # Force minimum volume of 1
            volume_map[key] = int(latest.get("item_count", 1)) 
        return volume_map

    def _get_tradeable_items_info(self, db: Session) -> dict[str, dict]:
        """Returns map of item_id -> {tier, category} for all scan targets."""
        # Task 5.4 - Derived tradeability logic instead of missing model field
        material_cats = ['crafting', 'gathering', 'consumables', 'farming']
        excluded_cats = ['furniture', 'vanity', 'other']

        query = (
            db.query(Item.item_id, Item.tier, Item.category)
            .filter(
                Item.category.notin_(excluded_cats),
                or_(
                    Item.category.in_(material_cats),
                    Item.tier >= 4
                )
            )
        )
        return {
            i[0]: {"tier": i[1], "category": i[2]} 
            for i in query.all() 
            if validate_item_id(i[0])
        }

    def estimate_item_weight(self, item_id: str) -> int:
        """Calculates 'computational weight' of a single item ID (Task 5.3)."""
        weight = 1
        id_upper = item_id.upper()
        
        # Heavy categories (Complex backend lookups)
        if "ARTEFACT" in id_upper: weight += 2
        if "CAPE" in id_upper:     weight += 3
        if "AVALON" in id_upper:   weight += 3
        if "MOUNT" in id_upper:    weight += 2
        if "SHARD" in id_upper:    weight += 1
        
        # Long ID penalty
        if len(item_id) > 25: weight += 1
        
        return weight

    def should_poll_category(self, category: str | None, current_minute: int) -> bool:
        """Determines if a category should be polled based on frequency (Task 5.3)."""
        if not category: return True
        cat = category.lower()
        
        # High Frequency (Every cycle)
        if cat in ['crafting', 'gathering', 'consumables', 'farming']:
            return True
            
        # Medium Frequency (Every 15 min)
        if cat in ['weapons', 'head', 'armors', 'shoes', 'offhands']:
            return (current_minute % 15) < 5 # Poll at 0, 15, 30, 45
            
        # Low Frequency (Every 60 min)
        if cat in ['mounts', 'artefacts', 'capes', 'bags']:
            return (current_minute % 60) < 5 # Poll only at the top of the hour
            
        return True

    def build_safe_batches(self, item_ids: list[str], max_url_len: int = 1200, max_weight: int = 25, max_items: int = 20) -> list[list[str]]:
        """
        Stealth Batching (Priority 1).
        Drastically reduced limits to avoid CDN/Backend 'expensive query' heuristics.
        """
        batches = []
        current_batch = []
        base_overhead = len(self.base_url) + 100 
        current_len = base_overhead
        current_weight = 0
        
        for item_id in item_ids:
            weight = self.estimate_item_weight(item_id)
            added_len = len(item_id) + 1
            
            # Flush if weight, length, or item count exceeded
            if (current_len + added_len > max_url_len) or \
               (current_weight + weight > max_weight) or \
               (len(current_batch) >= max_items):
               
                if current_batch:
                    batches.append(current_batch)
                current_batch = [item_id]
                current_len = base_overhead + added_len
                current_weight = weight
            else:
                current_batch.append(item_id)
                current_len += added_len
                current_weight += weight
                
        if current_batch:
            batches.append(current_batch)
            
        return batches

    async def process_signals(self, snapshots: list[MarketSnapshot]):
        """Generates signals for new snapshots using MeanReversionEngine and CrossCityModel."""
        # Hourly throttle
        if not hasattr(self, "_last_signal_run"):
            self._last_signal_run = None
            
        now = datetime.utcnow()
        if self._last_signal_run and (now - self._last_signal_run).total_seconds() < 3600:
            return # Skip if less than an hour has passed
            
        self._last_signal_run = now
        
        from app.models.mean_reversion_engine import MeanReversionEngine
        from app.models.cross_city_model import CrossCityModel
        from app.alerts.discord import DiscordAlerter
        
        mr_engine = MeanReversionEngine()
        cc_model = CrossCityModel()
        alerter = DiscordAlerter()
        
        # Group by item_id
        by_item = {}
        for s in snapshots:
            if s.item_id not in by_item: by_item[s.item_id] = []
            by_item[s.item_id].append(s)
            
        for item_id, snaps in by_item.items():
            # 1. Mean Reversion Signals
            processed = set()
            for s in snaps:
                if (s.item_id, s.city) in processed:
                    continue
                processed.add((s.item_id, s.city))
                
                prices = await self.repository.get_historical_prices(s.item_id, s.city, quality=s.quality)
                if prices and len(prices) >= 10:
                    signal = mr_engine.evaluate(s.item_id, s.city, prices)
                    if signal:
                        log.info(f"🚨 SIGNAL generated: {signal.signal_type} for {signal.item_id} in {signal.city} (Strength: {signal.strength:.2f})")
                        await alerter.send_signal_alert({
                            "item_id": signal.item_id,
                            "signal_type": signal.signal_type,
                            "alpha_score": signal.strength,
                            "confidence": 0.8,
                            "manipulation_risk": signal.metadata.get("volatility", 0.0),
                            "liquidity_score": 0.0,
                            "persistence_score": signal.metadata.get("half_life_seconds", 0.0) / 3600.0,
                            "cluster_id": signal.city
                        })
                        
            # 2. Cross-City Arbitrage Signals
            city_prices = {s.city: s.best_ask for s in snaps if s.best_ask > 0}
            if len(city_prices) > 1:
                # Generate dummy route info for pairs
                dummy_route = {}
                for c1 in city_prices:
                    dummy_route[c1] = {}
                    for c2 in city_prices:
                        if c1 != c2:
                            dummy_route[c1][c2] = {"distance_zones": 2, "zone_type": "red", "killboard_activity": 5}
                            
                signals = cc_model.evaluate(item_id, city_prices, item_weight=1.0, route_info=dummy_route)
                for sig in signals:
                    log.info(f"🚨 ARB SIGNAL: {sig.signal_type} for {sig.item_id} from {sig.metadata['source_city']} to {sig.metadata['target_city']} (Net Profit: {sig.metadata['net_profit']:.0f})")
                    await alerter.send_signal_alert({
                        "item_id": sig.item_id,
                        "signal_type": f"ARB ({sig.metadata['source_city']}->{sig.metadata['target_city']})",
                        "alpha_score": sig.strength,
                        "confidence": 0.8,
                        "manipulation_risk": 0.0,
                        "liquidity_score": 0.0,
                        "persistence_score": 0.0,
                        "cluster_id": sig.item_id
                    })

    async def collect_prices(self):
        """High-frequency price ingestion (Pass 1 only)."""
        log.info(f"🚀 Starting AQS v3.1 PRICE Ingestion ({settings.active_server.value})")
        
        now = datetime.utcnow()
        now_bucket = get_bucket(now)
        current_min = now.minute

        async with self as collector:
            with get_db_session() as db:
                db = cast(Session, db)
                item_info = self._get_tradeable_items_info(db)
                
                # Filter by Category Frequency (Task 5.3)
                all_ids = [
                    id for id, info in item_info.items() 
                    if self.should_poll_category(info.get("category"), current_min)
                ]
                
            batches = self.build_safe_batches(all_ids)
            log.info(f"📦 Syncing {len(batches)} weighted batches (Filtered from {len(item_info)} items)...")

            consecutive_429s = 0
            for i, batch in enumerate(batches):
                if self._stop_requested: break
                
                # Metrics
                batch_weight = sum(self.estimate_item_weight(id) for id in batch)
                all_cities = ",".join(CITY_API_NAMES.values())
                log.info(f"🌐 Requesting Batch {i+1}/{len(batches)} | items={len(batch)} | weight={batch_weight} | cities=ALL")

                # 1. Fetch (Multi-City Consolidation)
                try:
                    raw_data = await self.fetch_market_data(all_cities, batch)
                    consecutive_429s = 0 
                except Exception as e:
                    if "429" in str(e):
                        consecutive_429s += 1
                        if consecutive_429s >= 5:
                            log.warning("🛑 CIRCUIT BREAKER: Too many 429s. Cooling down for 60s...")
                            await asyncio.sleep(60)
                            consecutive_429s = 0
                    raise 

                # Group by city for processing
                city_groups = {}
                for r in raw_data:
                    c = r["city"]
                    if c not in city_groups: city_groups[c] = []
                    city_groups[c].append(r)
                
                # 2. Black Market Process
                bm_to_save = []
                bm_raw = city_groups.get("Caerleon", []) # BM prices are often tied to Caerleon buy orders
                # Note: The real Black Market is a separate location "Black Market"
                real_bm_raw = city_groups.get("Black Market", [])
                
                for item in real_bm_raw:
                    info = item_info.get(item["item_id"], {})
                    if not is_market_data_fresh(item["item_id"], item["data_age_seconds"], tier=info.get("tier", 4)):
                        continue
                    item["captured_at"] = datetime.utcnow()
                    item["captured_at_bucket"] = now_bucket
                    if validate_market_record(item): bm_to_save.append(item)

                # 3. Regional Process
                market_to_save = []
                # Add real BM records (as buy orders) to market_prices for the scanner
                for item in bm_to_save:
                    if item.get("buy_price_max", 0) > 0:
                        market_to_save.append({
                            **item, "city": "Black Market", "server": self.active_server.value
                        })

                for city_name, city_raw in city_groups.items():
                    if city_name == "Black Market": continue
                    for r in city_raw:
                        info = item_info.get(r["item_id"], {})
                        if not is_market_data_fresh(r["item_id"], r["data_age_seconds"], tier=info.get("tier", 4)):
                            continue
                            
                        r["captured_at"] = datetime.utcnow()
                        r["captured_at_bucket"] = now_bucket
                        if validate_market_record(r): market_to_save.append(r)

                # 4. UPSERT via Repository
                if market_to_save:
                    snapshots = []
                    for r in market_to_save:
                        snapshots.append(MarketSnapshot(
                            item_id=r["item_id"],
                            city=r["city"],
                            quality=r["quality"],
                            timestamp=r["captured_at"],
                            best_bid=float(r["buy_price_max"] or 0),
                            best_ask=float(r["sell_price_min"] or 0),
                            bid_depth=0,
                            ask_depth=0,
                            spread=float((r["sell_price_min"] or 0) - (r["buy_price_max"] or 0)),
                            midprice=float(((r["sell_price_min"] or 0) + (r["buy_price_max"] or 0)) / 2),
                            rolling_volume=r["volume_24h"] or 0,
                            volatility=0.0
                        ))
                    await self.repository.save_snapshots(snapshots)
                    self.parquet_storage.save_snapshots(snapshots)
                    # Cache hot snapshots in Redis
                    await asyncio.gather(*(self.redis_cache.set_hot_snapshot(s) for s in snapshots))
                    
                    # Process signals
                    await self.process_signals(snapshots)

                # Mandatory Pacing
                await asyncio.sleep(2.5)

                if (i + 1) % 10 == 0:
                    log.info(f"✅ Ingestion: {i + 1}/{len(batches)} batches synced.")

        log.info("📊 Price Collection Sync Complete.")

    async def collect_volumes(self):
        """Lower-frequency volume ingestion (Pass 2). Updates current market records."""
        log.info(f"🚀 Starting AQS v3.1 VOLUME Refresh ({settings.active_server.value})")
        
        async with self as collector:
            with get_db_session() as db:
                db = cast(Session, db)
                item_info = self._get_tradeable_items_info(db)
                all_ids = list(item_info.keys())
            
            # Larger batches for history is okay as it's less frequent
            batches = self.build_safe_batches(all_ids, max_url_len=1500)
            
            for i, batch in enumerate(batches):
                if self._stop_requested: break
                
                for city_name in CITY_API_NAMES:
                    v_map = await self.fetch_volume_data(city_name, batch)
                    if not v_map: continue
                    
                    # Update the LATEST records for these items in the DB via repository
                    async def update_item_volume(k, v):
                        item_id, quality = k.split(":")
                        await self.repository.update_volume(item_id, city_name, int(quality), v)
                        
                    await asyncio.gather(*(update_item_volume(key, vol) for key, vol in v_map.items()))
                
                if (i + 1) % 5 == 0:
                    log.info(f"✅ Volume Sync: {i + 1}/{len(batches)} batches done.")

        log.info("📊 Volume Refresh Complete.")
