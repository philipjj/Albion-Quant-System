"""
Arbitrage Scanner for Albion Online v3.1.
Finds profitable transport routes across all cities, items, and enchantments.
Includes fee-aware scoring and risk-adjusted EV calculations.
"""
import math
from datetime import datetime, timedelta
from itertools import permutations
from typing import Any, Dict, cast

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    ALL_CITIES_WITH_BM,
    DANGEROUS_ROUTES,
    QUALITY_NAMES,
    get_distance,
    is_price_sane,
)
from app.core.fees import calculate_net_margin
from app.core.logging import log
from app.core.market_utils import calculate_z_score
from app.core.scoring import scorer
from app.db.models import ArbitrageOpportunity, BlackMarketSnapshot, Item, MarketPrice
from app.db.session import get_db_session


class ArbitrageScanner:
    """
    Scans for profitable cross-city arbitrage opportunities.
    Uses AQS v3.1 optimized route evaluation and streaming.
    """

    def __init__(self):
        self.opportunities: list[dict] = []
        self.stats = {"items_scanned": 0, "pairs_evaluated": 0, "opportunities_found": 0}
        self._persistence_cache: dict[str, int] = {}

    def _calculate_risk_score(self, source: str, dest: str, item_value: float) -> float:
        """Calculates transport risk based on distance and route danger."""
        dist = get_distance(source, dest)
        is_dangerous = (source, dest) in DANGEROUS_ROUTES
        
        base_risk = dist * settings.arb_distance_weight
        if is_dangerous:
            base_risk *= settings.arb_danger_multiplier
            
        # Value-at-risk penalty
        value_risk = (item_value / settings.arb_value_divisor) * settings.arb_value_weight
        return round(base_risk + value_risk, 2)

    def _get_latest_prices(self, db: Session) -> dict[tuple[str, int], dict[str, dict[str, Any]]]:
        """Fetches and groups latest prices using memory-efficient streaming."""
        cutoff = datetime.utcnow() - timedelta(hours=settings.arb_regular_hours)
        valid_items = set([
            i[0] for i in db.query(Item.item_id).filter(
                Item.category != "vanity"
            ).all()
        ])

        item_meta = {i.item_id: i.item_value for i in db.query(Item.item_id, Item.item_value).all()}
        
        recent_prices = db.query(MarketPrice).filter(
            MarketPrice.captured_at >= cutoff,
            MarketPrice.server == settings.active_server.value
        ).yield_per(5000)
        
        prices: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
        for p in recent_prices:
            item_id = cast(str, p.item_id)
            if item_id not in valid_items: continue

            key = (item_id, p.quality)
            if key not in prices: prices[key] = {}

            iv = item_meta.get(item_id, 0.0)
            prices[key][p.city] = {
                "sell_price_min": p.sell_price_min or 0,
                "buy_price_max": p.buy_price_max or 0,
                "quality": p.quality,
                "data_age_seconds": p.data_age_seconds,
                "volume_24h": p.volume_24h or 0,
                "confidence_score": p.confidence_score or 1.0,
                "item_value": iv,
                "is_black_market": False
            }

        # --- Black Market Integration ---
        bm_cutoff = datetime.utcnow() - timedelta(hours=settings.arb_bm_hours)
        bm_snapshots = db.query(BlackMarketSnapshot).filter(
            BlackMarketSnapshot.captured_at >= bm_cutoff
        ).all()
        
        for bm in bm_snapshots:
            if bm.item_id not in valid_items: continue
            key = (bm.item_id, bm.quality)
            if key not in prices: prices[key] = {}
            
            prices[key]["Black Market"] = {
                "sell_price_min": 0,
                "buy_price_max": bm.buy_price_max or 0,
                "quality": bm.quality,
                "data_age_seconds": bm.data_age_seconds,
                "volume_24h": 1,
                "confidence_score": 1.0,
                "item_value": item_meta.get(bm.item_id, 0.0),
                "is_black_market": True
            }
        return prices

    async def scan(self, fast_sell: bool = False, source_city_filter: str = None) -> list[dict]:
        log.info(f"ARBITRAGE SCAN v3.1 - START (fast_sell={fast_sell})")
        self.opportunities = []
        self.stats = {"items_scanned": 0, "pairs_evaluated": 0, "opportunities_found": 0}

        with get_db_session() as db:
            db = cast(Session, db)
            prices = self._get_latest_prices(db)
            items = db.query(Item.item_id, Item.name, Item.weight).all()
            item_names = {i.item_id: i.name for i in items}
            item_weights = {i.item_id: i.weight for i in items}

        if not prices:
            log.warning("No market prices available.")
            return []

        # Optimization: O(N * C) logic
        for (item_id, quality), city_prices in prices.items():
            self.stats["items_scanned"] += 1
            if self.stats["items_scanned"] % 500 == 0:
                log.info(f"Scanning progress: {self.stats['items_scanned']} items analyzed...")

            # Find cheapest regional source
            sources = [(c, p) for c, p in city_prices.items() if p.get("sell_price_min", 0) > 0 and not p.get("is_black_market")]
            if not sources: continue
            
            if source_city_filter:
                sources = [s for s in sources if s[0].lower() == source_city_filter.lower()]
                if not sources: continue
            
            cheapest_source_city, s_data = min(sources, key=lambda x: x[1]["sell_price_min"])
            buy_price = s_data["sell_price_min"]
            
            if buy_price > settings.max_capital_per_trade: continue

            for dest_city, d_data in city_prices.items():
                if dest_city == cheapest_source_city: continue
                self.stats["pairs_evaluated"] += 1
                
                if d_data.get("is_black_market"):
                    sell_price = d_data.get("buy_price_max", 0)
                    fast_sell_actual = True
                else:
                    sell_price = d_data.get("buy_price_max", 0) if fast_sell else d_data.get("sell_price_min", 0)
                    fast_sell_actual = fast_sell

                if sell_price <= buy_price: continue

                # Calculate Fee-Adjusted Profit
                net_profit, margin_pct = calculate_net_margin(
                    buy_price=buy_price,
                    sell_price=sell_price,
                    is_black_market=d_data.get("is_black_market", False),
                    fast_sell=fast_sell_actual,
                    tax_free=False 
                )

                if margin_pct < settings.min_arbitrage_margin: continue
                
                # Sanitize 999 Volume Fallbacks
                raw_vol = d_data.get("volume_24h", 0)
                daily_vol = 1 if raw_vol == 999 or raw_vol == 0 else raw_vol
                
                if daily_vol <= 0 and not d_data.get("is_black_market"): continue

                risk_score = self._calculate_risk_score(cheapest_source_city, dest_city, s_data["item_value"])
                p_key = f"{item_id}:{cheapest_source_city}:{dest_city}"
                persistence = self._persistence_cache.get(p_key, 0) + 1
                self._persistence_cache[p_key] = persistence

                opportunity = {
                    "item_id": item_id,
                    "item_name": item_names.get(item_id, item_id),
                    "item_weight": item_weights.get(item_id, 0.0),
                    "quality": quality,
                    "source_city": cheapest_source_city,
                    "destination_city": dest_city,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "estimated_profit": round(net_profit, 2), # strictly unit math
                    "estimated_margin": round(margin_pct, 2),
                    "risk_score": risk_score,
                    "daily_volume": daily_vol,
                    "volatility": settings.arb_default_volatility, 
                    "persistence": persistence,
                    "data_age_seconds": d_data.get("data_age_seconds", 0),
                    "confidence_score": d_data.get("confidence_score", 1.0),
                    "detected_at": datetime.utcnow().isoformat()
                }
                
                # Protect core metrics from mutation
                opportunity["ev_score"] = scorer.score_arbitrage(opportunity.copy())
                if opportunity["ev_score"] > 0:
                    self.opportunities.append(opportunity)
                    self.stats["opportunities_found"] += 1

        self.opportunities.sort(key=lambda x: x["ev_score"], reverse=True)
        return self.opportunities

    def store_opportunities(self) -> int:
        if not self.opportunities: return 0
        with get_db_session() as db:
            db = cast(Session, db)
            # Clear old active opportunities
            db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).update({"is_active": False})
            
            mappings = []
            for o in self.opportunities:
                mappings.append({
                    "item_id": o["item_id"], 
                    "item_name": o["item_name"], 
                    "source_city": o["source_city"], 
                    "destination_city": o["destination_city"], 
                    "buy_price": o["buy_price"], 
                    "sell_price": o["sell_price"],
                    "estimated_profit": o["estimated_profit"], 
                    "estimated_margin": o["estimated_margin"],
                    "risk_score": o.get("risk_score", 0), 
                    "daily_volume": o.get("daily_volume", 0),
                    "ev_score": o.get("ev_score", 0.0), 
                    "volatility": o.get("volatility", 0.0), 
                    "persistence": o.get("persistence", 1),
                    "detected_at": datetime.utcnow(), 
                    "is_active": True
                })
                
            if mappings:
                from sqlalchemy import insert
                db.execute(insert(ArbitrageOpportunity), mappings)
            return len(mappings)
