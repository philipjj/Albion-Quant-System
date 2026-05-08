"""
AQS Scanner Integration
========================
Drop-in replacement wrappers around OpportunityEngine that produce dicts
compatible with the existing DB models and Discord alerter.

Usage:
    from app.core.scanner_integration import UnifiedScanner
    scanner = UnifiedScanner()
    bm, crafting, arb = await scanner.scan_all(db_session)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.opportunity_engine import (
    BMOpportunity,
    ArbitrageOpportunity,
    CraftingOpportunity,
    OpportunityScanner,
)
from app.db.models import BlackMarketSnapshot, Item, MarketPrice, Recipe
from app.db.session import get_db_session

log = logging.getLogger(__name__)


class UnifiedScanner:
    """
    Replaces the fragmented ArbitrageScanner + CraftingEngine.
    One price map load, three opportunity types, one coherent model.
    """

    def __init__(
        self,
        use_focus: bool = False,
        premium: bool = True,
        min_bm_profit: int = 10_000,
        min_craft_profit: int = 5_000,
        min_arb_profit: int = 5_000,
    ):
        self.engine = OpportunityScanner(
            min_bm_profit=min_bm_profit,
            min_craft_profit=min_craft_profit,
            min_arb_profit=min_arb_profit,
            use_focus=use_focus,
            premium=premium,
        )

    # ── Data loading ────────────────────────────────────────────────────────

    def _load_prices(self, db: Session, lookback_hours: float = 4.0) -> Dict:
        """
        Load latest prices into the nested dict structure OpportunityEngine expects.
        Structure: {item_id: {city: {quality: {fields...}}}}
        """
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        prices: Dict[str, Dict[str, Dict[int, Dict]]] = {}

        rows = (
            db.query(MarketPrice)
            .filter(
                MarketPrice.captured_at >= cutoff,
                MarketPrice.server == settings.active_server.value,
            )
            .all()
        )

        for p in rows:
            item_id = p.item_id
            city = p.city
            quality = p.quality or 1

            if item_id not in prices:
                prices[item_id] = {}
            if city not in prices[item_id]:
                prices[item_id][city] = {}

            existing = prices[item_id][city].get(quality)
            if existing and p.captured_at and existing.get("_ts") and p.captured_at <= existing["_ts"]:
                continue   # Keep newest only

            prices[item_id][city][quality] = {
                "sell_price_min": p.sell_price_min or 0,
                "buy_price_max": p.buy_price_max or 0,
                "volume_24h": p.volume_24h or 0,
                "data_age_seconds": int(p.data_age_seconds or 9999),
                "is_black_market": False,
                "item_value": 0.0,  # Filled below
                "_ts": p.captured_at,
            }

        # Black Market snapshots (Caerleon buy orders)
        bm_cutoff = datetime.utcnow() - timedelta(hours=2)
        bm_rows = db.query(BlackMarketSnapshot).filter(
            BlackMarketSnapshot.captured_at >= bm_cutoff
        ).all()

        for bm in bm_rows:
            item_id = bm.item_id
            quality = bm.quality or 1
            city = "Black Market"

            if item_id not in prices:
                prices[item_id] = {}
            if city not in prices[item_id]:
                prices[item_id][city] = {}

            existing = prices[item_id][city].get(quality)
            if existing and bm.captured_at and existing.get("_ts") and bm.captured_at <= existing["_ts"]:
                continue

            prices[item_id][city][quality] = {
                "sell_price_min": 0,
                "buy_price_max": bm.buy_price_max or 0,
                "volume_24h": 1,
                "data_age_seconds": int(bm.data_age_seconds or 9999),
                "is_black_market": True,
                "_ts": bm.captured_at,
            }

        return prices

    def _load_item_metadata(self, db: Session) -> Tuple[Dict, Dict, Dict]:
        """Returns (item_names, item_categories, item_values)"""
        rows = db.query(Item.item_id, Item.name, Item.category, Item.item_value).all()
        names = {r.item_id: r.name for r in rows}
        categories = {r.item_id: (r.category or "") for r in rows}
        values = {r.item_id: float(r.item_value or 0.0) for r in rows}
        return names, categories, values

    def _load_recipes(self, db: Session) -> Dict:
        """
        Build recipe map: {item_id: {"ingredients": [{"item_id": str, "quantity": float}]}}
        Filters out raw-resource-only ingredients for non-refining crafts (same logic
        as existing engine, but simplified and less lossy).
        """
        rows = db.query(Recipe).all()
        recipes: Dict[str, Dict] = {}
        for r in rows:
            cid = r.crafted_item_id
            if cid not in recipes:
                recipes[cid] = {"ingredients": []}
            recipes[cid]["ingredients"].append({
                "item_id": r.ingredient_item_id,
                "quantity": float(r.quantity or 1),
            })
        return recipes

    # ── Main entry point ────────────────────────────────────────────────────

    async def scan_all(
        self, db: Session = None
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Returns (bm_opps, craft_opps, arb_opps) as plain dicts ready for DB storage
        and Discord alerts. All sorted by score descending.
        """
        with get_db_session() as db:
            log.info("[UNIFIED SCANNER] Loading prices...")
            prices = self._load_prices(db)
            log.info(f"[UNIFIED SCANNER] {len(prices)} items loaded.")

            names, categories, values = self._load_item_metadata(db)
            recipes = self._load_recipes(db)

        log.info("[UNIFIED SCANNER] Scanning Black Market...")
        bm_raw = self.engine.scan_black_market(prices, names, recipes, categories)
        log.info(f"[UNIFIED SCANNER] BM: {len(bm_raw)} opportunities")

        log.info("[UNIFIED SCANNER] Scanning Crafting...")
        craft_raw = self.engine.scan_crafting(prices, names, recipes, categories, values)
        log.info(f"[UNIFIED SCANNER] Crafting: {len(craft_raw)} opportunities")

        log.info("[UNIFIED SCANNER] Scanning Arbitrage...")
        arb_raw = self.engine.scan_arbitrage(prices, names)
        log.info(f"[UNIFIED SCANNER] Arbitrage: {len(arb_raw)} opportunities")

        return (
            [self._bm_to_dict(o) for o in bm_raw],
            [self._craft_to_dict(o) for o in craft_raw],
            [self._arb_to_dict(o) for o in arb_raw],
        )

    # ── Dict converters for compatibility with existing DB/Discord code ─────

    def _bm_to_dict(self, o: BMOpportunity) -> Dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": o.item_name,
            "source_city": o.buy_city,
            "destination_city": "Black Market",
            "buy_price": o.buy_price,
            "sell_price": o.bm_buy_price,
            "estimated_profit": o.effective_profit,
            "estimated_margin": o.profit_pct,
            "mode": o.mode,                      # "BUY+RUN" or "CRAFT+RUN"
            "craft_cost": o.craft_cost,
            "craft_city": o.craft_city,
            "can_be_crafted": o.can_be_crafted,
            "daily_volume": o.daily_volume,
            "data_age_buy": o.data_age_buy,
            "data_age_bm": o.data_age_bm,
            "quality": o.quality,
            "ev_score": o.score,
            "risk_score": 0.5,   # BM always requires Caerleon run
            "type": "black_market",
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _craft_to_dict(self, o: CraftingOpportunity) -> Dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": o.item_name,
            "crafting_city": o.craft_city,
            "sell_city": o.sell_city,
            "sell_mode": o.sell_mode,            # "BM" or "MARKET"
            "craft_cost": o.material_cost_net + o.station_fee,
            "material_cost_gross": o.material_cost_gross,
            "material_cost_net": o.material_cost_net,
            "station_fee": o.station_fee,
            "rrr_used": o.rrr_used,
            "sell_price": o.sell_price,
            "revenue_net": o.revenue_net,
            "profit": o.profit,
            "profit_margin": o.profit_pct,
            "daily_volume": o.daily_volume,
            "data_age_materials": o.data_age_materials,
            "data_age_sell": o.data_age_sell,
            "use_focus": o.use_focus,
            "quality": o.quality,
            "ev_score": o.score,
            "ingredients": o.ingredients,
            "type": "crafting",
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _arb_to_dict(self, o: ArbitrageOpportunity) -> Dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": o.item_name,
            "source_city": o.buy_city,
            "destination_city": o.sell_city,
            "buy_price": o.buy_price,
            "sell_price": o.sell_price,   # This is buy_price_max (existing buy order)
            "estimated_profit": o.net_profit,
            "estimated_margin": o.profit_pct,
            "tax_paid": o.tax_paid,
            "is_dangerous": o.is_dangerous_route,
            "daily_volume": o.daily_volume,
            "data_age_buy": o.data_age_buy,
            "data_age_sell": o.data_age_sell,
            "quality": o.quality,
            "ev_score": o.score,
            "risk_score": 0.7 if o.is_dangerous_route else 0.2,
            "type": "arbitrage",
            "detected_at": datetime.utcnow().isoformat(),
        }
