"""
Live Market Data Collector for Albion Online.
Fetches prices from the Albion Online Data Project API in batches.
Stores snapshots for live analysis and historical tracking.
"""

import asyncio
from datetime import datetime
from typing import cast

import httpx
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.constants import CITY_API_NAMES
from app.core.feature_gate import feature_gate
from app.core.logging import log
from app.db.models import Item, MarketPrice, MarketSnapshot
from app.db.session import get_db_session


class MarketCollector:
    """
    Collects live market prices from the Albion Online Data Project API.
    
    Features:
    - Batch requests (100-300 items per request)
    - Rate limiting (respects 180 req/min)
    - Stores latest + historical snapshots
    - Automatic retry on failure
    """

    API_PRICE_ENDPOINT = "/api/v2/stats/prices/{item_ids}.json"
    API_HISTORY_ENDPOINT = "/api/v2/stats/history/{item_ids}.json"
    API_ORDERS_ENDPOINT = "/api/v2/stats/orders/{item_ids}"
    API_ORDER_VIEW_ENDPOINT = "/api/v2/stats/view/{item_ids}"
    BATCH_SIZE = 20  # Reduced to 20 for Europe server stability
    REQUEST_DELAY = 2.0  # Increased to 2.0s to prevent rate limits

    def __init__(self):
        self.base_url = settings.albion_api_base
        self.cities = ",".join(CITY_API_NAMES.values())
        self._stop_requested = False
        self.stats = {
            "total_fetched": 0,
            "total_stored": 0,
            "errors": 0,
            "batches": 0,
        }

    def request_stop(self) -> None:
        """Signal long-running collectors to stop as soon as possible."""
        self._stop_requested = True

    def _get_tradeable_items(self, db: Session) -> list[str]:
        """Get all item IDs that should be tracked for market prices."""
        items = db.query(Item.item_id).all()
        item_ids = [i[0] for i in items]

        if not item_ids:
            log.warning("No items in database. Run static data parser first.")
            # Fallback: use a set of common tradeable items
            item_ids = self._get_default_items()

        log.info(f"Tracking {len(item_ids)} items for market prices")
        return item_ids

    @staticmethod
    def _get_default_items() -> list[str]:
        """Comprehensive fallback list of tradeable items across all categories."""
        items = []
        # Core Equipment Groups
        base_items = [
            "BAG", "CAPE", "MOUNT_HORSE", "MOUNT_OX",
            "HEAD_CLOTH_SET1", "ARMOR_CLOTH_SET1", "SHOES_CLOTH_SET1",
            "HEAD_LEATHER_SET1", "ARMOR_LEATHER_SET1", "SHOES_LEATHER_SET1",
            "HEAD_PLATE_SET1", "ARMOR_PLATE_SET1", "SHOES_PLATE_SET1",
            "MAIN_SWORD", "2H_CLAYMORE", "2H_DUALSWORD",
            "MAIN_AXE", "2H_HALBERD", "2H_AXE",
            "MAIN_MACE", "2H_POLEHAMMER", "2H_MACE",
            "MAIN_HAMMER", "2H_HAMMER", "2H_POLEHAMMER",
            "MAIN_SPEAR", "2H_SPEAR", "2H_GLAIVE",
            "MAIN_DAGGER", "2H_DAGGERPAIR", "2H_CLAW",
            "MAIN_BOW", "2H_BOW", "2H_LONGBOW",
            "MAIN_CROSSBOW", "2H_CROSSBOW", "2H_REPEATINGCROSSBOW",
            "MAIN_FIRESTAFF", "2H_FIRESTAFF", "2H_INFERNOSTAFF",
            "MAIN_HOLYSTAFF", "2H_HOLYSTAFF", "2H_DIVINESTAFF",
            "MAIN_ARCANESTAFF", "2H_ARCANESTAFF", "2H_ENIGMATICSTAFF",
            "MAIN_FROSTSTAFF", "2H_FROSTSTAFF", "2H_GLACIALSTAFF",
            "MAIN_CURSEDSTAFF", "2H_CURSEDSTAFF", "2H_DEMONICSTAFF",
            "MAIN_NATURESTAFF", "2H_NATURESTAFF", "2H_WILDSTAFF",
            "MAIN_QUARTERSTAFF", "2H_QUARTERSTAFF", "2H_IRONCLADSTAFF",
            "OFF_SHIELD", "OFF_TOWERSHIELD", "OFF_BOOK", "OFF_ORB", "OFF_TOTEM",
        ]
        
        # Resources (Raw and Refined)
        resources = ["WOOD", "ORE", "FIBER", "HIDE", "ROCK", "PLANKS", "METALBAR", "CLOTH", "LEATHER", "STONEBLOCK"]
        
        # Artifacts & Consumables
        misc = ["POTION_HEAL", "POTION_ENERGY", "POTION_REGEN", "FOOD_SOUP", "FOOD_STEW", "FOOD_SANDWICH"]
        
        # Journals & Artifact Components
        extras = ["JOURNAL_BLACKSMITH_EMPTY", "JOURNAL_FLETCHER_EMPTY", "JOURNAL_IMBUER_EMPTY", "JOURNAL_TINKER_EMPTY", "RUNE", "SOUL", "RELIC"]

        for tier in [4, 5, 6, 7, 8]:
            # Add base equipment with enchantments
            for cat in base_items:
                items.append(f"T{tier}_{cat}")
                for ench in [1, 2, 3]:
                    items.append(f"T{tier}_{cat}@{ench}")
            
            # Add resources
            for res in resources:
                items.append(f"T{tier}_{res}")
                for ench in [1, 2, 3]:
                    items.append(f"T{tier}_{res}_LEVEL{ench}")

            # Add misc & journals
            for m in misc + extras:
                items.append(f"T{tier}_{m}")
                
            # Add common artifacts
            artifact_suffixes = ["KEEPER", "HELL", "UNDEAD", "MORGANA", "AVALON"]
            for suff in artifact_suffixes:
                items.append(f"T{tier}_ARTIFACT_ARMOR_PLATE_{suff}")
                items.append(f"T{tier}_ARTIFACT_MAIN_SWORD_{suff}")

        return items

    def _batch_items(self, item_ids: list[str]) -> list[list[str]]:
        """Split item IDs into batches for API requests."""
        return [
            item_ids[i : i + self.BATCH_SIZE]
            for i in range(0, len(item_ids), self.BATCH_SIZE)
        ]

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=60))
    async def _fetch_batch(
        self, client: httpx.AsyncClient, item_ids: list[str]
    ) -> list[dict]:
        """Fetch market prices for a batch of items."""
        items_str = ",".join(item_ids)
        url = f"{self.base_url}{self.API_PRICE_ENDPOINT.format(item_ids=items_str)}"

        params = {
            "locations": self.cities,
            "qualities": "1,2,3,4,5",
        }

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning(f"API Error {e.response.status_code} for batch. URL: {url[:100]}...")
            raise

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=60))
    async def _fetch_history_batch(
        self, client: httpx.AsyncClient, item_ids: list[str]
    ) -> list[dict]:
        """Fetch historical sales data for a batch of items."""
        items_str = ",".join(item_ids)
        url = f"{self.base_url}{self.API_HISTORY_ENDPOINT.format(item_ids=items_str)}"

        # Use 24h time scale for daily volume verification
        params = {
            "locations": self.cities,
            "time-scale": 24
        }

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            log.warning(f"API Error {e.response.status_code} for batch. URL: {url[:100]}...")
            raise

    def _store_history(self, db: Session, history_data: list[dict]) -> int:
        """Store historical sales data in the database."""
        stored = 0
        from app.db.models import MarketHistory

        for entry in history_data:
            item_id = entry.get("item_id", "")
            location = entry.get("location", "")
            data_points = entry.get("data", [])

            if not item_id or not location or not data_points:
                continue

            # We usually only care about the most recent 24h block
            latest = data_points[-1]

            history = MarketHistory(
                item_id=item_id,
                city=location,
                quality=entry.get("quality", 1),
                item_count=latest.get("item_count", 0),
                avg_price=latest.get("avg_price", 0.0),
                timestamp=self._parse_date(latest.get("timestamp", "")) or datetime.utcnow()
            )
            db.add(history)
            stored += 1

        return stored

    def _store_prices(self, db: Session, prices: list[dict]) -> int:
        """Store fetched prices in the database."""
        stored = 0
        now = datetime.utcnow()

        for price_data in prices:
            item_id = price_data.get("item_id", "")
            city = price_data.get("city", "")
            sell_min = price_data.get("sell_price_min", 0)
            buy_max = price_data.get("buy_price_max", 0)
            quality = price_data.get("quality", 1)

            if not item_id or not city:
                continue

            # Skip zero-price entries (no data available)
            if sell_min == 0 and buy_max == 0:
                continue

            # Parse API date strings
            sell_date = self._parse_date(price_data.get("sell_price_min_date", ""))
            buy_date = self._parse_date(price_data.get("buy_price_max_date", ""))

            market_price = MarketPrice(
                item_id=item_id,
                city=city,
                sell_price_min=sell_min,
                sell_price_min_date=sell_date,
                buy_price_max=buy_max,
                buy_price_max_date=buy_date,
                quality=quality,
                fetched_at=now,
            )
            db.add(market_price)
            stored += 1

        return stored

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse ISO date string from API."""
        if not date_str or date_str == "0001-01-01T00:00:00":
            return None
        try:
            # Handle various ISO formats
            clean = date_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean.replace("+00:00", ""))
        except (ValueError, AttributeError):
            return None

    async def collect_all_prices(self) -> dict:
        """
        Main collection pipeline:
        1. Get all tradeable items from DB
        2. Batch them into API requests
        3. Fetch prices with rate limiting
        4. Store in database
        """
        log.info("=" * 60)
        log.info("MARKET PRICE COLLECTION - START")
        log.info("=" * 60)

        self.stats = {"total_fetched": 0, "total_stored": 0, "errors": 0, "batches": 0}

        with get_db_session() as db:
            db = cast(Session, db)
            item_ids = self._get_tradeable_items(db)

        batches = self._batch_items(item_ids)
        log.info(f"Collecting prices in {len(batches)} batches of ~{self.BATCH_SIZE} items")

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": "AlbionQuantTradingSystem/1.0 (DiscordBot Contact: User)",
            },
        ) as client:
            for i, batch in enumerate(batches):
                if self._stop_requested:
                    log.info("Price collection stop requested.")
                    return self.stats
                try:
                    log.debug(f"Fetching batch {i + 1}/{len(batches)} ({len(batch)} items)")
                    prices = await self._fetch_batch(client, batch)
                    self.stats["total_fetched"] += len(prices)
                    self.stats["batches"] += 1

                    # Store in DB
                    with get_db_session() as db:
                        db = cast(Session, db)
                        stored = self._store_prices(db, prices)
                        self.stats["total_stored"] += stored

                    log.debug(f"Batch {i + 1}: fetched={len(prices)}, stored={stored}")

                    # Rate limiting
                    await asyncio.sleep(self.REQUEST_DELAY)

                except asyncio.CancelledError:
                    log.info("Price collection stopped (system shutdown).")
                    raise
                except httpx.HTTPStatusError as e:
                    feature_gate.report_failure("prices", e.response.status_code)
                    log.error(f"Batch {i + 1} HTTP error: {e.response.status_code}")
                    self.stats["errors"] += 1
                    wait_time = 30.0 if e.response.status_code == 429 else 2.0
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    log.error(f"Batch {i + 1} error: {e}")
                    self.stats["errors"] += 1
                    await asyncio.sleep(1.0)

        log.info(f"MARKET COLLECTION COMPLETE: {self.stats}")
        return self.stats

    async def collect_market_history(self) -> dict:
        """
        Fetches the actual 24h sales volume for all tracked items.
        This provides the 'Real Demand' metric to prevent market saturation risk.
        """
        log.info("📊 FETCHING MARKET HISTORY (REAL VOLUME)...")
        stats = {"total_history": 0, "errors": 0}

        with get_db_session() as db:
            db = cast(Session, db)
            item_ids = self._get_tradeable_items(db)

        batches = self._batch_items(item_ids)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, batch in enumerate(batches):
                if self._stop_requested:
                    log.info("History collection stop requested.")
                    return stats
                try:
                    if feature_gate.is_rate_limited:
                        await asyncio.sleep(10.0) # Emergency backoff

                    data = await self._fetch_history_batch(client, batch)
                    with get_db_session() as db:
                        db = cast(Session, db)
                        stored = self._store_history(db, data)
                        stats["total_history"] += stored

                    await asyncio.sleep(self.REQUEST_DELAY)

                except asyncio.CancelledError:
                    log.info("History collection stopped (system shutdown).")
                    raise
                except Exception as e:
                    log.error(f"History batch {i+1} error: {e}")
                    stats["errors"] += 1

        log.info(f"MARKET HISTORY COMPLETE: {stats}")
        return stats

    async def fetch_total_supply(self, client: httpx.AsyncClient, item_id: str, city: str) -> int:
        """
        Fetches the total current supply (active sell orders) for an item in a city.
        This allows us to calculate the 'Market Gap'.
        """
        url = f"{self.base_url}{self.API_ORDERS_ENDPOINT.format(item_ids=item_id)}"
        params = {"locations": city}

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            orders = response.json()

            if not isinstance(orders, list):
                return 0

            # Sum up all 'offer' (sell order) quantities
            total_supply = sum(
                order.get("Amount", 0)
                for order in orders
                if order.get("AuctionType") == "offer"
            )
            return total_supply
        except httpx.HTTPStatusError as e:
            feature_gate.report_failure("orders", e.response.status_code)
            return 0
        except Exception as e:
            log.error(f"Error fetching supply for {item_id}: {e}")
            return 0

    async def create_snapshot(self) -> int:
        """Create a historical snapshot of current market state."""
        log.info("Creating market snapshot...")
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=2)

        with get_db_session() as db:
            db = cast(Session, db)
            # Fetch recent prices and group in memory to avoid slow SQLite GROUP BY
            recent_prices = db.query(MarketPrice).filter(MarketPrice.fetched_at >= cutoff).all()

            prices_map: dict[tuple[str, str, int], MarketPrice] = {}
            for p in recent_prices:
                key = (cast(str, p.item_id), cast(str, p.city), cast(int, p.quality))
                if key not in prices_map or p.fetched_at > prices_map[key].fetched_at:
                    prices_map[key] = p

            now = datetime.utcnow()
            count = 0
            for price in prices_map.values():
                snapshot = MarketSnapshot(
                    item_id=price.item_id,
                    city=price.city,
                    sell_price_min=price.sell_price_min,
                    buy_price_max=price.buy_price_max,
                    quality=price.quality,
                    snapshot_at=now,
                )
                db.add(snapshot)
                count += 1

            log.info(f"Created {count} snapshot records")
            return count

    async def cleanup_old_prices(self, keep_hours: int = 24) -> int:
        """Remove market prices older than keep_hours."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=keep_hours)

        with get_db_session() as db:
            db = cast(Session, db)
            deleted = (
                db.query(MarketPrice)
                .filter(MarketPrice.fetched_at < cutoff)
                .delete()
            )
            log.info(f"Cleaned up {deleted} old market price records")
            return deleted
