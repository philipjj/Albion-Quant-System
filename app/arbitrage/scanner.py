"""
Arbitrage Scanner for Albion Online.
Finds profitable transport routes across all cities, items, and enchantments.
Includes risk scoring based on route danger and item value density.
"""

from datetime import datetime
from itertools import permutations
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    ALL_MARKET_CITIES,
    DANGEROUS_ROUTES,
    QUALITY_NAMES,
    get_distance,
)
from app.core.logging import log
from app.core.market_utils import simulate_daily_volume
from app.db.models import ArbitrageOpportunity, Item, MarketPrice
from app.db.session import get_db_session


class ArbitrageScanner:
    """
    Scans for profitable cross-city arbitrage opportunities.
    
    Formula:
        net_profit = sell_price - buy_price - market_fees - transport_cost - risk_penalty
        margin = net_profit / buy_price * 100
    
    Filters:
        - margin > MIN_ARBITRAGE_MARGIN (default 12%)
        - profit > MIN_ARBITRAGE_PROFIT (default 10,000 silver)
        - volume > MIN_VOLUME (default 5)
    """

    def __init__(self):
        self.opportunities: list[dict] = []
        self.stats = {
            "items_scanned": 0,
            "pairs_evaluated": 0,
            "opportunities_found": 0,
        }
        self._persistence_cache: dict[str, int] = {} # Key: item_id:source:dest

    def _calculate_market_fees(self, buy_price: int, sell_price: int) -> float:
        """
        Calculate total market fees for a buy-and-sell cycle.
        
        Fees:
        - 2.5% setup fee on buy order
        - 2.5% setup fee on sell order
        - 4% sales tax (premium) or 8% (non-premium)
        """
        buy_setup = buy_price * settings.setup_fee_rate
        sell_setup = sell_price * settings.setup_fee_rate
        sales_tax = sell_price * settings.tax_rate
        return buy_setup + sell_setup + sales_tax

    def _calculate_risk_score(
        self,
        source_city: str,
        dest_city: str,
        item_value: int,
    ) -> float:
        """
        Calculate transport risk score (0.0 = safe, 1.0 = extremely dangerous).
        
        Factors:
        - Route danger (red/black zone traversal)
        - Distance
        - Item value density (higher value = more attractive to gankers)
        """
        # Base distance risk
        distance = get_distance(source_city, dest_city)
        distance_risk = min(distance / 10.0, 0.5)

        # Zone danger
        route = (source_city, dest_city)
        route_rev = (dest_city, source_city)
        zone_risk = 0.0
        if route in DANGEROUS_ROUTES or route_rev in DANGEROUS_ROUTES:
            zone_risk = 0.25  # Routes through Caerleon = red zone

        # Value density risk (higher value items attract more gankers)
        value_risk = 0.0
        if item_value > 500000:
            value_risk = 0.3
        elif item_value > 200000:
            value_risk = 0.2
        elif item_value > 100000:
            value_risk = 0.1

        total_risk = min(distance_risk + zone_risk + value_risk, 1.0)
        return round(total_risk, 3)

    def _calculate_transport_cost(
        self,
        source_city: str,
        dest_city: str,
        item_value: int,
    ) -> float:
        """Estimate transport cost based on distance and risk."""
        distance = get_distance(source_city, dest_city)
        risk = self._calculate_risk_score(source_city, dest_city, item_value)
        return item_value * risk * 0.1

    def _calculate_liquidity_score(self, buy_p: int, sell_p: int) -> float:
        """Estimate liquidity via spread. 0.0=Liquid, 1.0=Stagnant."""
        if sell_p <= 0: return 1.0
        spread = (sell_p - buy_p) / sell_p
        if spread < 0.05: return 0.1  # Very liquid
        if spread < 0.15: return 0.4  # Moderate
        return 0.9  # Wide spread / Illiquid

    def _get_latest_prices(self, db: Session) -> dict:
        """
        Get the latest market prices for all items across all cities.
        Uses in-memory grouping for massive speedup instead of unindexed SQL GROUP BY.
        Ignores Vanity items.
        Returns lookup keyed by (item_id, quality)
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=2)

        # 1. Fetch valid items (non-vanity)
        valid_items = set([
            i[0] for i in db.query(Item.item_id).filter(
                Item.category != "vanity",
                Item.shop_category != "vanity",
                Item.shop_subcategory != "vanity_mount"
            ).all()
        ])

        # 2. Fetch recent prices using the fetched_at index
        recent_prices = db.query(MarketPrice).filter(MarketPrice.fetched_at >= cutoff).all()

        # 3. Group in memory (O(N) single pass, vastly faster than unindexed SQLite GROUP BY)
        prices: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
        for p in recent_prices:
            item_id = cast(str, p.item_id)
            quality = cast(int, p.quality)
            city = cast(str, p.city)
            if item_id not in valid_items:
                continue

            key = (item_id, quality)
            if key not in prices:
                prices[key] = {}

            city_data = prices[key].get(city)
            if not city_data or p.fetched_at > city_data["fetched_at"]:
                prices[key][city] = {
                    "sell_price_min": p.sell_price_min or 0,
                    "buy_price_max": p.buy_price_max or 0,
                    "quality": p.quality,
                    "fetched_at": p.fetched_at,
                }

        return prices

    def _get_item_names(self, db: Session) -> dict[str, str]:
        """Get item_id -> name mapping."""
        items = db.query(Item.item_id, Item.name).all()
        return {i[0]: i[1] for i in items}

    def _get_market_stats_map(self, db: Session) -> dict[tuple[str, str], dict]:
        """Build 24h volume and volatility stats for all item/city pairs in one query."""
        import math
        from datetime import timedelta

        from app.db.models import MarketHistory

        cutoff = datetime.utcnow() - timedelta(hours=24)
        records = db.query(
            MarketHistory.item_id,
            MarketHistory.city,
            MarketHistory.item_count,
            MarketHistory.avg_price,
        ).filter(MarketHistory.timestamp >= cutoff).all()

        grouped: dict[tuple[str, str], dict] = {}
        for item_id, city, item_count, avg_price in records:
            bucket = grouped.setdefault((item_id, city), {"volume": 0, "prices": []})
            bucket["volume"] += item_count or 0
            if avg_price and avg_price > 0:
                bucket["prices"].append(avg_price)

        stats = {}
        for key, bucket in grouped.items():
            prices = bucket["prices"]
            volatility = 0.05
            if len(prices) > 1:
                mean = sum(prices) / len(prices)
                variance = sum((price - mean) ** 2 for price in prices) / len(prices)
                volatility = math.sqrt(variance) / mean if mean > 0 else 0.05
            stats[key] = {"volume": bucket["volume"], "volatility": volatility}

        return stats


    async def scan(self, fast_sell: bool = False, source_city_filter: str = None) -> list[dict]:
        """
        Run the full arbitrage scan.
        
        Iterates through all items × all city pairs to find profitable routes.
        If fast_sell is True, it evaluates selling instantly to the destination's highest buy order.
        If source_city_filter is provided, it only evaluates routes starting from that city.
        """
        log.info("=" * 60)
        log.info(f"ARBITRAGE SCAN - START (fast_sell={fast_sell})")
        log.info("=" * 60)

        self.opportunities = []
        self.stats = {"items_scanned": 0, "pairs_evaluated": 0, "opportunities_found": 0}

        with get_db_session() as db:
            db = cast(Session, db)
            prices = self._get_latest_prices(db)
            item_names = self._get_item_names(db)
            market_stats = self._get_market_stats_map(db)

        if not prices:
            log.warning("No market prices available. Run market collector first.")
            return []

        # Generate all city pairs (directional)
        from app.core.constants import ALL_CITIES_WITH_BM
        city_pairs = list(permutations(ALL_CITIES_WITH_BM, 2))

        for (item_id, quality), city_prices in prices.items():
            self.stats["items_scanned"] += 1

            for source, dest in city_pairs:
                self.stats["pairs_evaluated"] += 1

                # If filter is provided, skip routes not starting from the filtered city
                if source_city_filter and source.lower() != source_city_filter.lower():
                    continue

                source_data = city_prices.get(source)
                dest_data = city_prices.get(dest)

                if not source_data or not dest_data:
                    continue

                buy_price = source_data.get("sell_price_min", 0) or 0

                if fast_sell:
                    sell_price = dest_data.get("buy_price_max", 0) or 0
                else:
                    sell_price = dest_data.get("sell_price_min", 0) or 0

                # Skip zero prices
                if buy_price <= 0 or sell_price <= 0:
                    continue

                # Skip if buy > sell (no profit possible)
                if buy_price >= sell_price:
                    continue

                # Calculate costs
                # Calculate costs accurately for transport runs:
                if fast_sell:
                    # Instant Buy (Source) + Instant Sell (Destination)
                    # 1. Buy at sell_price_min (Source): No setup fee
                    # 2. Sell at buy_price_max (Destination): Sales tax only, no setup fee
                    market_fees = sell_price * settings.tax_rate
                else:
                    # Instant Buy (Source) + Sell Order (Destination)
                    # 1. Buy at sell_price_min (Source): No setup fee
                    # 2. Create sell order at sell_price_min (Destination): Setup fee + Sales tax
                    market_fees = (sell_price * settings.setup_fee_rate) + (sell_price * settings.tax_rate)

                transport_cost = self._calculate_transport_cost(source, dest, buy_price)
                base_risk = self._calculate_risk_score(source, dest, buy_price)
                liquidity_risk = self._calculate_liquidity_score(buy_price, sell_price)

                # Composite risk score
                risk_score = (base_risk * 0.6) + (liquidity_risk * 0.4)

                # Net profit
                net_profit = sell_price - buy_price - market_fees - transport_cost

                if net_profit <= 0:
                    continue

                # Margin
                margin = (net_profit / buy_price) * 100

                # Apply filters
                # We lower the margin and profit requirements slightly for instant sells because there's 0 wait time
                min_margin = settings.min_arbitrage_margin / 2 if fast_sell else settings.min_arbitrage_margin
                min_profit = settings.min_arbitrage_profit / 2 if fast_sell else settings.min_arbitrage_profit

                if margin < min_margin:
                    continue
                if net_profit < min_profit:
                    continue

                # Sanity Check: If margin is > 1000%, it's a dead market troll listing or RMT.
                # No legitimate, high-volume item generates 10x profit instantly.
                if margin > 1000:
                    continue

                base_name = item_names.get(item_id, item_id)
                if quality != 1:
                    quality_str = QUALITY_NAMES.get(quality, "Unknown")
                    item_name = f"{base_name} ({quality_str})"
                else:
                    item_name = base_name

                # Demand Verification & Volatility Analysis
                stats = market_stats.get((item_id, dest), {"volume": 0, "volatility": 0.05})
                real_volume = stats["volume"]
                volatility = stats["volatility"]
                sim_volume = simulate_daily_volume(item_id)

                final_volume = real_volume if real_volume > 0 else sim_volume
                volume_source = "VERIFIED 24H" if real_volume > 0 else "ESTIMATED"

                # Persistence Tracking
                p_key = f"{item_id}:{source}:{dest}"
                persistence = self._persistence_cache.get(p_key, 0) + 1
                self._persistence_cache[p_key] = persistence

                opportunity = {
                    "item_id": item_id, "item_name": item_name,
                    "quality": quality,
                    "source_city": source, "destination_city": dest,
                    "buy_price": buy_price, "sell_price": sell_price,
                    "estimated_profit": round(net_profit, 2),
                    "estimated_margin": round(margin, 2),
                    "risk_score": risk_score, "market_fees": round(market_fees, 2),
                    "transport_cost": round(transport_cost, 2),
                    "daily_volume": final_volume, "volume_source": volume_source,
                    "volatility": volatility, "persistence": persistence,
                    "detected_at": datetime.utcnow().isoformat()
                }

                # Apply Stage 2: EV Scoring
                from app.core.scoring import scorer
                opportunity["ev_score"] = scorer.score_arbitrage(opportunity)

                if opportunity["ev_score"] > 0:
                    self.opportunities.append(opportunity)
                    self.stats["opportunities_found"] += 1

        # Sort by EV Score (The Core Alpha)
        self.opportunities.sort(key=lambda x: x["ev_score"], reverse=True)
        log.info(f"ARBITRAGE SCAN COMPLETE: {self.stats}")
        return self.opportunities

    def store_opportunities(self) -> int:
        """Store found opportunities in the database."""
        if not self.opportunities:
            return 0

        with get_db_session() as db:
            db = cast(Session, db)
            # Mark old opportunities as inactive
            db.query(ArbitrageOpportunity).filter(
                ArbitrageOpportunity.is_active == True
            ).update({"is_active": False})

            now = datetime.utcnow()
            mappings = []

            for opp in self.opportunities:
                mappings.append({
                    "item_id": opp["item_id"],
                    "item_name": opp["item_name"],
                    "source_city": opp["source_city"],
                    "destination_city": opp["destination_city"],
                    "buy_price": opp["buy_price"],
                    "sell_price": opp["sell_price"],
                    "estimated_profit": opp["estimated_profit"],
                    "estimated_margin": opp["estimated_margin"],
                    "risk_score": opp["risk_score"],
                    "daily_volume": opp.get("daily_volume", 0),
                    "volume_source": opp.get("volume_source", "ESTIMATED"),
                    "safe_limit": opp.get("safe_limit", 1),
                    "current_supply": opp.get("current_supply", 0),
                    "market_gap": opp.get("market_gap", 0),
                    "expected_hourly_profit": opp.get("expected_hourly_profit", 0.0),
                    "ev_score": opp.get("ev_score", 0.0),
                    "volatility": opp.get("volatility", 0.0),
                    "persistence": opp.get("persistence", 1),
                    "detected_at": now,
                    "is_active": True,
                })

            if mappings:
                from sqlalchemy import insert
                db.execute(insert(ArbitrageOpportunity), mappings)

            log.info(f"Stored {len(mappings)} arbitrage opportunities (bulk insert)")
            return len(mappings)

    def get_top_opportunities(self, limit: int = 20) -> list[dict]:
        """Get top opportunities sorted by margin."""
        return self.opportunities[:limit]

    def get_opportunities_for_item(self, item_id: str) -> list[dict]:
        """Get all opportunities for a specific item."""
        return [
            opp for opp in self.opportunities
            if opp["item_id"] == item_id
        ]
