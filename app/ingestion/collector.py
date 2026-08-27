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

from sqlalchemy import and_, or_
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
from app.shared.domain.market_snapshot import MarketSnapshot
from app.shared.domain.repository import IMarketDataRepository


def parse_timestamp(ts: str) -> datetime | None:
    if not ts or ts == "0001-01-01T00:00:00":
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
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

    def __init__(self, repository: IMarketDataRepository = None):
        self.base_url = settings.aodp_base_urls.get(
            settings.active_server, "https://europe.albion-online-data.com"
        )
        self.active_server = settings.active_server
        self._stop_requested = False
        self._ingest_lock = asyncio.Lock()
        if repository is None:
            from app.db.repository import SQLiteMarketDataRepository

            self.repository = SQLiteMarketDataRepository()
        else:
            self.repository = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def request_stop(self):
        self._stop_requested = True

    async def fetch_market_data(self, city: str, item_ids: list[str]) -> list[dict]:
        """Queries AODP prices endpoint using the centralized HTTP service."""
        ids_str = ",".join(item_ids)
        url = f"{self.base_url}/api/v2/stats/prices/{ids_str}.json"
        params = {"locations": city, "qualities": "1,2,3,4,5"}

        resp = await aqs_http.get(url, params=params)
        if not resp or resp.status_code != 200:
            return []

        raw = resp.json()
        results = []
        for item in raw:
            item_id = item.get("item_id", "")

            # Independent Age calculation
            sell_date = parse_timestamp(item.get("sell_price_min_date"))
            buy_date = parse_timestamp(item.get("buy_price_max_date"))
            now_utc = datetime.utcnow()

            sell_age_sec = None
            if sell_date:
                sell_age_sec = int(
                    (now_utc.replace(tzinfo=sell_date.tzinfo) - sell_date).total_seconds()
                )

            buy_age_sec = None
            if buy_date:
                buy_age_sec = int(
                    (now_utc.replace(tzinfo=buy_date.tzinfo) - buy_date).total_seconds()
                )

            # General data age: for Black Market or when only buy order exists, use buy order age
            if city == "Black Market" or (item.get("buy_price_max") and not item.get("sell_price_min")):
                age_sec = buy_age_sec if buy_age_sec is not None else sell_age_sec
            else:
                age_sec = sell_age_sec if sell_age_sec is not None else buy_age_sec

            results.append(
                {
                    "item_id": item_id,
                    "city": item.get("city", city),
                    "server": self.active_server.value,
                    "sell_price_min": item.get("sell_price_min"),
                    "sell_price_max": item.get("sell_price_max"),
                    "buy_price_min": item.get("buy_price_min"),
                    "buy_price_max": item.get("buy_price_max"),
                    "sell_price_min_date": sell_date,
                    "buy_price_max_date": buy_date,
                    "quality": item.get("quality", 1),
                    "data_age_seconds": age_sec,
                    "sell_age_seconds": sell_age_sec,
                    "buy_age_seconds": buy_age_sec,
                    "volume_24h": item.get("volume_24h"),  # None until collect_volumes populates it
                    "coverage_suspect": False,
                }
            )
        return results

    async def fetch_volume_data(self, city: str, item_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetches 24-hour volume and historical pool average price using the centralized HTTP service."""
        if not item_ids:
            return {}

        ids_str = ",".join(item_ids)
        url = f"{self.base_url}/api/v2/stats/history/{ids_str}.json?locations={city}&time-scale=24&qualities=1,2,3,4,5"

        resp = await aqs_http.get(url)
        if not resp or resp.status_code != 200:
            return {}

        raw = resp.json()
        volume_map = {}
        for record in raw:
            data = record.get("data", [])
            if not data:
                continue
            valid_data = [d for d in data if d.get("timestamp")]
            if not valid_data:
                continue
            latest = max(valid_data, key=lambda x: x.get("timestamp"))
            key = f"{record.get('item_id', '')}:{record.get('quality', 1)}"

            # Capture volume and average price from 24h historical pool
            volume_map[key] = {
                "volume": int(latest.get("item_count", 1)),
                "avg_price": float(latest.get("avg_price", 0.0)),
                "timestamp": latest.get("timestamp"),
            }
        return volume_map

    async def fetch_volume_data_all_locations(self, item_ids: list[str]) -> dict[tuple[str, str, int], dict[str, Any]]:
        """Fetches 24-hour volume and historical pool average price across all hubs in a SINGLE multiplexed request."""
        if not item_ids:
            return {}

        ids_str = ",".join(item_ids)
        all_cities_str = ",".join(CITY_API_NAMES.values())
        url = f"{self.base_url}/api/v2/stats/history/{ids_str}.json?locations={all_cities_str}&time-scale=24&qualities=1,2,3,4,5"

        resp = await aqs_http.get(url)
        if not resp or resp.status_code != 200:
            return {}

        raw = resp.json()
        volume_map = {}
        for record in raw:
            data = record.get("data", [])
            if not data:
                continue
            valid_data = [d for d in data if d.get("timestamp")]
            if not valid_data:
                continue
            latest = max(valid_data, key=lambda x: x.get("timestamp"))
            item_id = record.get("item_id", "")
            city = record.get("location", "")
            quality = int(record.get("quality", 1))

            key = (item_id, city, quality)
            volume_map[key] = {
                "volume": int(latest.get("item_count", 1)),
                "avg_price": float(latest.get("avg_price", 0.0)),
                "timestamp": latest.get("timestamp"),
            }
        return volume_map

    def _get_tradeable_items_info(self, db: Session) -> dict[str, dict]:
        """Returns map of item_id -> {tier, category} for all scan targets."""
        material_cats = ["crafting", "gathering", "consumables", "farming", "magic", "artefacts", "materials", "token", "mounts"]
        
        tradeable_other_conditions = or_(
            Item.item_id.like("TREASURE_%"),
            Item.item_id.like("%_JOURNAL_%"),
            Item.item_id.like("%_RANDOM_DUNGEON_%"),
            Item.item_id.like("%_HELLGATE_%"),
            Item.item_id.like("%_CORRUPTED_%"),
            Item.item_id.like("%_SIEGE_%"),
            Item.item_id.like("%_TOOL_SIEGE%"),
            Item.item_id.like("QUESTITEM_TOKEN_%"),
            Item.item_id.like("QUESTITEM_EXP_TOME%"),
        )

        query = db.query(Item.item_id, Item.tier, Item.category).filter(
            Item.category.notin_(["furniture", "vanity"]),
            or_(
                Item.category.in_(material_cats),
                Item.tier >= 3,
                and_(Item.category == "other", tradeable_other_conditions),
            ),
            ~Item.item_id.like("%_TRASH%"),
            ~Item.item_id.like("SKIN_%"),
        )
        return {
            i[0]: {"tier": i[1], "category": i[2]} for i in query.all() if validate_item_id(i[0])
        }

    def estimate_item_weight(self, item_id: str) -> int:
        """Calculates 'computational weight' of a single item ID (Task 5.3)."""
        weight = 1
        id_upper = item_id.upper()

        # Heavy categories (Complex backend lookups)
        if "ARTEFACT" in id_upper:
            weight += 2
        if "CAPE" in id_upper:
            weight += 3
        if "AVALON" in id_upper:
            weight += 3
        if "MOUNT" in id_upper:
            weight += 2
        if "SHARD" in id_upper:
            weight += 1

        # Long ID penalty
        if len(item_id) > 25:
            weight += 1

        return weight

    def should_poll_category(self, category: str | None, current_minute: int) -> bool:
        """Determines if a category should be polled based on frequency (Task 5.3)."""
        if not category:
            return True
        cat = category.lower()

        # High Frequency (Every cycle)
        if cat in [
            "crafting",
            "gathering",
            "consumables",
            "farming",
            "weapons",
            "head",
            "armors",
            "shoes",
            "offhands",
            "capes",
            "bags",
            "artefacts", # Critical for enchanting (RUNES, SOULS, RELICS)
            "materials",
            "magic",
            "token"
        ]:
            return True

        # Low Frequency (Every 60 min)
        if cat in ["mounts"]:
            # If the current minute is 0-15, allow it to be polled to ensure 
            # all partitions (up to 10) get a chance to poll it.
            return (current_minute % 60) < 15

        return True

    def build_safe_batches(
        self,
        item_ids: list[str],
        max_url_len: int = 2400,
        max_weight: int = 50,
        max_items: int = 40,
    ) -> list[list[str]]:
        """
        Stealth Batching (High-Throughput).
        Groups items safely within AODP URI and query limits to minimize total roundtrip time.
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
            if (
                (current_len + added_len > max_url_len)
                or (current_weight + weight > max_weight)
                or (len(current_batch) >= max_items)
            ):
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
                    id
                    for id, info in item_info.items()
                    if self.should_poll_category(info.get("category"), current_min)
                ]

            batches = self.build_safe_batches(all_ids)
            log.info(
                f"📦 Syncing {len(batches)} weighted batches (Filtered from {len(item_info)} items)..."
            )

            consecutive_429s = 0
            for i, batch in enumerate(batches):
                if self._stop_requested:
                    break

                # Metrics
                batch_weight = sum(self.estimate_item_weight(id) for id in batch)
                all_cities = ",".join(CITY_API_NAMES.values())
                log.info(
                    f"🌐 Requesting Batch {i + 1}/{len(batches)} | items={len(batch)} | weight={batch_weight} | cities=ALL"
                )

                # 1. Fetch (Multi-City Consolidation)
                try:
                    raw_data = await self.fetch_market_data(all_cities, batch)
                    consecutive_429s = 0
                except Exception as e:
                    if "429" in str(e):
                        consecutive_429s += 1
                        if consecutive_429s >= 5:
                            log.warning(
                                "🛑 CIRCUIT BREAKER: Too many 429s. Cooling down for 60s..."
                            )
                            await asyncio.sleep(60)
                            consecutive_429s = 0
                    raise

                # Group by city for processing
                city_groups = {}
                for r in raw_data:
                    c = r["city"]
                    if c not in city_groups:
                        city_groups[c] = []
                    city_groups[c].append(r)

                # 2. Black Market Process
                bm_to_save = []
                bm_raw = city_groups.get(
                    "Caerleon", []
                )  # BM prices are often tied to Caerleon buy orders
                # Note: The real Black Market is a separate location "Black Market"
                real_bm_raw = city_groups.get("Black Market", [])

                for item in real_bm_raw:
                    info = item_info.get(item["item_id"], {})
                    if not is_market_data_fresh(
                        item["item_id"], item["data_age_seconds"], volume_24h=item.get("volume_24h"), tier=info.get("tier", 4)
                    ):
                        continue
                    item["captured_at"] = datetime.utcnow()
                    item["captured_at_bucket"] = now_bucket
                    if validate_market_record(item):
                        bm_to_save.append(item)

                # 3. Regional Process
                market_to_save = []
                # Add real BM records (as buy orders) to market_prices for the scanner
                for item in bm_to_save:
                    if item.get("buy_price_max", 0) > 0:
                        market_to_save.append(
                            {**item, "city": "Black Market", "server": self.active_server.value}
                        )

                for city_name, city_raw in city_groups.items():
                    if city_name == "Black Market":
                        continue
                    for r in city_raw:
                        info = item_info.get(r["item_id"], {})
                        if not is_market_data_fresh(
                            r["item_id"], r["data_age_seconds"], volume_24h=r.get("volume_24h"), tier=info.get("tier", 4)
                        ):
                            continue

                        r["captured_at"] = datetime.utcnow()
                        r["captured_at_bucket"] = now_bucket
                        if validate_market_record(r):
                            market_to_save.append(r)

                # 4. UPSERT via Repository
                if market_to_save:
                    snapshots = []
                    for r in market_to_save:
                        snapshots.append(
                            MarketSnapshot(
                                item_id=r["item_id"],
                                city=r["city"],
                                quality=r["quality"],
                                timestamp=r["captured_at"],
                                best_bid=float(r["buy_price_max"] or 0),
                                best_ask=float(r["sell_price_min"] or 0),
                                bid_depth=0,
                                ask_depth=0,
                                spread=float(
                                    (r["sell_price_min"] or 0) - (r["buy_price_max"] or 0)
                                ),
                                midprice=float(
                                    ((r["sell_price_min"] or 0) + (r["buy_price_max"] or 0)) / 2
                                ),
                                rolling_volume=r.get("volume_24h") or 0,
                                volatility=0.0,
                                sell_price_min_date=r.get("sell_price_min_date"),
                                buy_price_max_date=r.get("buy_price_max_date"),
                                data_age_seconds=float(r.get("data_age_seconds") or 0.0),
                            )
                        )
                    await self.repository.save_snapshots(snapshots)
                    if settings.enable_historical_parquet:
                        self.parquet_storage.save_snapshots(snapshots)
                    if settings.enable_redis_cache:
                        await asyncio.gather(*(self.redis_cache.set_hot_snapshot(s) for s in snapshots))

                # Mandatory Pacing
                await asyncio.sleep(2.5)

                if (i + 1) % 10 == 0:
                    log.info(f"✅ Ingestion: {i + 1}/{len(batches)} batches synced.")

        log.info("📊 Price Collection Sync Complete.")

    def partition_items(
        self, item_ids: list[str], num_partitions: int, partition_idx: int
    ) -> list[str]:
        """
        Deterministically assign items to partitions using hash-based distribution.
        This ensures each partition gets a diverse mix of categories/tiers,
        not a contiguous alphabetical block.
        """
        return [iid for iid in item_ids if hash(iid) % num_partitions == partition_idx]

    async def collect_partition(self, partition_idx: int, num_partitions: int) -> int:
        """
        Collect prices for a single partition of the item universe.
        Returns the number of batches processed.
        """
        log.info(
            f"🚀 Partition {partition_idx + 1}/{num_partitions} — Starting ingestion ({settings.active_server.value})"
        )

        now = datetime.utcnow()
        now_bucket = get_bucket(now)
        current_min = now.minute

        self._stop_requested = False
        async with self._ingest_lock:
            async with self as collector:
                with get_db_session() as db:
                    db = cast(Session, db)
                    item_info = self._get_tradeable_items_info(db)

                    # Apply category frequency filter first
                    all_ids = [
                        id
                        for id, info in item_info.items()
                        if self.should_poll_category(info.get("category"), current_min)
                    ]

            # Slice to this partition only
            partition_ids = self.partition_items(all_ids, num_partitions, partition_idx)

            # High-priority commodities (Runes, Souls, Relics, Avalonian Shards, Royal Sigils, Faction Hearts, Base Capes & Crests)
            # are polled FIRST in EVERY partition to guarantee zero-staleness on all enchantment, crafting, and royal cape calculations
            always_poll_commodities = (
                [
                    f"T{t}_{m}"
                    for t in range(4, 9)
                    for m in ["RUNE", "SOUL", "RELIC", "SHARD_AVALONIAN"]
                ]
                + [f"QUESTITEM_TOKEN_ROYAL_T{t}" for t in range(4, 9)]
                + ["QUESTITEM_TOKEN_AVALON"]
                + [f"T{t}_CAPE" for t in range(4, 9)]
                + [
                    "T1_FACTION_FOREST_TOKEN_1",
                    "T1_FACTION_HIGHLAND_TOKEN_1",
                    "T1_FACTION_STEPPE_TOKEN_1",
                    "T1_FACTION_MOUNTAIN_TOKEN_1",
                    "T1_FACTION_SWAMP_TOKEN_1",
                    "T1_FACTION_CAERLEON_TOKEN_1",
                ]
                + [
                    f"T{t}_CAPEITEM_FW_{c}_BP"
                    for t in range(4, 9)
                    for c in ["BRIDGEWATCH", "FORTSTERLING", "LYMHURST", "MARTLOCK", "THETFORD", "CAERLEON", "BRECILIEN"]
                ]
                + [
                    f"T{t}_CAPEITEM_{m}_BP"
                    for t in range(4, 9)
                    for m in ["AVALON", "HERETIC", "UNDEAD", "KEEPER", "MORGANA", "DEMON", "SMUGGLER"]
                ]
            )
            priority_core = [ap_id for ap_id in always_poll_commodities if ap_id in item_info]
            partition_ids = priority_core + [iid for iid in partition_ids if iid not in priority_core]

            if not partition_ids:
                log.info(
                    f"⚠️ Partition {partition_idx + 1}/{num_partitions} is empty after filtering. Skipping."
                )
                return 0

            batches = self.build_safe_batches(partition_ids)
            log.info(
                f"📦 Partition {partition_idx + 1}/{num_partitions}: {len(partition_ids)} items → {len(batches)} batches"
            )

            consecutive_429s = 0
            for i, batch in enumerate(batches):
                if self._stop_requested:
                    break

                batch_weight = sum(self.estimate_item_weight(id) for id in batch)
                all_cities = ",".join(CITY_API_NAMES.values())
                log.info(
                    f"🌐 P{partition_idx + 1} Batch {i + 1}/{len(batches)} | items={len(batch)} | weight={batch_weight}"
                )

                try:
                    raw_data = await self.fetch_market_data(all_cities, batch)
                    consecutive_429s = 0
                except Exception as e:
                    if "429" in str(e):
                        consecutive_429s += 1
                        if consecutive_429s >= 5:
                            log.warning(
                                "🛑 CIRCUIT BREAKER: Too many 429s. Cooling down for 60s..."
                            )
                            await asyncio.sleep(60)
                            consecutive_429s = 0
                    raise

                # Group by city
                city_groups = {}
                for r in raw_data:
                    c = r["city"]
                    if c not in city_groups:
                        city_groups[c] = []
                    city_groups[c].append(r)

                # Black Market Process
                bm_to_save = []
                real_bm_raw = city_groups.get("Black Market", [])
                for item in real_bm_raw:
                    info = item_info.get(item["item_id"], {})
                    if not is_market_data_fresh(
                        item["item_id"], item["data_age_seconds"], volume_24h=item.get("volume_24h"), tier=info.get("tier", 4)
                    ):
                        continue
                    item["captured_at"] = datetime.utcnow()
                    item["captured_at_bucket"] = now_bucket
                    if validate_market_record(item):
                        bm_to_save.append(item)

                # Regional Process
                market_to_save = []
                for item in bm_to_save:
                    if item.get("buy_price_max", 0) > 0:
                        market_to_save.append(
                            {**item, "city": "Black Market", "server": self.active_server.value}
                        )

                for city_name, city_raw in city_groups.items():
                    if city_name == "Black Market":
                        continue
                    for r in city_raw:
                        info = item_info.get(r["item_id"], {})
                        if not is_market_data_fresh(
                            r["item_id"], r["data_age_seconds"], volume_24h=r.get("volume_24h"), tier=info.get("tier", 4)
                        ):
                            continue
                        r["captured_at"] = datetime.utcnow()
                        r["captured_at_bucket"] = now_bucket
                        if validate_market_record(r):
                            market_to_save.append(r)

                # UPSERT via Repository
                if market_to_save:
                    snapshots = []
                    for r in market_to_save:
                        snapshots.append(
                            MarketSnapshot(
                                item_id=r["item_id"],
                                city=r["city"],
                                quality=r["quality"],
                                timestamp=r["captured_at"],
                                best_bid=float(r["buy_price_max"] or 0),
                                best_ask=float(r["sell_price_min"] or 0),
                                bid_depth=0,
                                ask_depth=0,
                                spread=float(
                                    (r["sell_price_min"] or 0) - (r["buy_price_max"] or 0)
                                ),
                                midprice=float(
                                    ((r["sell_price_min"] or 0) + (r["buy_price_max"] or 0)) / 2
                                ),
                                rolling_volume=r.get("volume_24h") or 0,
                                volatility=0.0,
                                sell_price_min_date=r.get("sell_price_min_date"),
                                buy_price_max_date=r.get("buy_price_max_date"),
                                data_age_seconds=float(r.get("data_age_seconds") or 0.0),
                            )
                        )
                    await self.repository.save_snapshots(snapshots)

                # Mandatory Pacing
                await asyncio.sleep(0.5)

            log.info(
                f"✅ Partition {partition_idx + 1}/{num_partitions} complete: {len(batches)} batches ingested."
            )
            return len(batches)

    async def collect_volumes(self):
        """Lower-frequency volume ingestion (Pass 2). Updates current market records with location multiplexing."""
        log.info(f"🚀 Starting AQS v3.1 VOLUME Refresh ({settings.active_server.value})")

        async with self._ingest_lock:
            async with self as collector:
                with get_db_session() as db:
                    db = cast(Session, db)
                    item_info = self._get_tradeable_items_info(db)
                    all_ids = list(item_info.keys())

                batches = self.build_safe_batches(all_ids, max_url_len=1200, max_items=25)

                for i, batch in enumerate(batches):
                    if self._stop_requested:
                        break

                    v_map = await self.fetch_volume_data_all_locations(batch)
                    if v_map:
                        await asyncio.gather(
                            *(
                                self.repository.update_volume(
                                    item_id, city, quality, v_data["volume"], v_data["avg_price"], v_data["timestamp"]
                                )
                                for (item_id, city, quality), v_data in v_map.items()
                            )
                        )

                    if (i + 1) % 10 == 0 or (i + 1) == len(batches):
                        log.info(f"✅ Volume Sync: {i + 1}/{len(batches)} batches done.")

                    await asyncio.sleep(0.5)

        log.info("📊 Volume Refresh Complete.")

    async def collect_full_universe_fast(self, max_concurrency: int = 4) -> int:
        """
        Fast Full-Universe Market Sweep.
        Fetches all tradeable items across all cities using controlled concurrent worker tasks.
        Completes in 2-3 minutes for the full catalog of ~8,334 items.
        """
        log.info(f"🚀 [AODP SWEEP] Starting Full-Universe Fast Ingestion ({settings.active_server.value})...")
        now = datetime.utcnow()
        now_bucket = get_bucket(now)

        with get_db_session() as db:
            db = cast(Session, db)
            item_info = self._get_tradeable_items_info(db)
            all_ids = list(item_info.keys())

        batches = self.build_safe_batches(all_ids, max_url_len=1200, max_items=25)
        log.info(f"📦 [AODP SWEEP] {len(all_ids)} items divided into {len(batches)} batches.")

        all_cities = ",".join(CITY_API_NAMES.values())
        sem = asyncio.Semaphore(max_concurrency)
        total_ingested = 0

        async def process_batch(idx: int, batch: list[str]):
            nonlocal total_ingested
            if self._stop_requested:
                return

            async with sem:
                try:
                    raw_data = await self.fetch_market_data(all_cities, batch)
                    if not raw_data:
                        return

                    market_to_save = []
                    for r in raw_data:
                        r["captured_at"] = datetime.utcnow()
                        r["captured_at_bucket"] = now_bucket
                        if validate_market_record(r):
                            market_to_save.append(r)

                    if market_to_save:
                        snapshots = [
                            MarketSnapshot(
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
                                rolling_volume=r.get("volume_24h") or 0,
                                volatility=0.0,
                                sell_price_min_date=r.get("sell_price_min_date"),
                                buy_price_max_date=r.get("buy_price_max_date"),
                                data_age_seconds=float(r.get("data_age_seconds") or 0.0),
                            )
                            for r in market_to_save
                        ]
                        await self.repository.save_snapshots(snapshots)
                        total_ingested += len(snapshots)

                    await asyncio.sleep(0.3)
                except Exception as e:
                    log.warning(f"[AODP SWEEP] Batch {idx + 1} error: {e}")

        tasks = [process_batch(i, b) for i, b in enumerate(batches)]
        await asyncio.gather(*tasks)

        log.info(f"✅ [AODP SWEEP] Finished full sweep: {total_ingested} records updated.")
        return total_ingested
