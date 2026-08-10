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

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import log
from app.core.opportunity_engine import (
    ArbitrageOpportunity,
    BMOpportunity,
    CraftingOpportunity,
    EnchantingOpportunity,
    RefiningOpportunity,
    MarketMakingOpportunity,
    OpportunityScanner,
)
from app.db.models import BlackMarketSnapshot, Item, MarketPrice, Recipe
from app.db.session import get_db_session


class UnifiedScanner:
    """
    Replaces the fragmented ArbitrageScanner + CraftingEngine.
    One price map load, three opportunity types, one coherent model.
    """

    def __init__(
        self,
        use_focus: bool = False,
        premium: bool = None,
        min_bm_profit: int = 30_000,
        min_craft_profit: int = 5_000,
        min_arb_profit: int = 1_000,
    ):
        self.default_min_bm_profit = min_bm_profit
        self.default_min_craft_profit = min_craft_profit
        self.default_min_arb_profit = min_arb_profit

        self.engine = OpportunityScanner(
            min_bm_profit=min_bm_profit,
            min_craft_profit=min_craft_profit,
            min_arb_profit=min_arb_profit,
            use_focus=use_focus,
            premium=premium,
        )

    # ── Data loading ────────────────────────────────────────────────────────

    def _load_prices(self, db: Session, lookback_hours: float = 4.0, scan_bm: bool = False) -> dict:
        """
        Load latest prices into the nested dict structure OpportunityEngine expects.
        Structure: {item_id: {city: {quality: {fields...}}}}
        """
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
        prices: dict[str, dict[str, dict[int, dict]]] = {}

        rows = (
            db.query(MarketPrice)
            .filter(
                MarketPrice.captured_at >= cutoff,
                MarketPrice.server == settings.active_server.value,
            )
            .order_by(MarketPrice.captured_at.asc())
            .all()
        )
        log.info(
            f"[UNIFIED SCANNER] Loaded {len(rows)} rows from DB for cutoff {cutoff} and server {settings.active_server.value}"
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
            if existing and existing.get("_ts"):
                cur_ts = p.captured_at or datetime.min
                old_ts = existing.get("_ts") or datetime.min
                if cur_ts <= old_ts:
                    continue  # Keep newest only

            # Recompute data age dynamically: original API age + time since collection
            api_age = int(p.data_age_seconds) if p.data_age_seconds is not None else 0
            if p.captured_at:
                db_age = (datetime.utcnow() - p.captured_at).total_seconds()
            else:
                db_age = 0
            effective_age = api_age + db_age

            prices[item_id][city][quality] = {
                "sell_price_min": p.sell_price_min or 0,
                "buy_price_max": p.buy_price_max or 0,
                "volume_24h": p.volume_24h or 0,
                "data_age_seconds": int(effective_age),
                "is_black_market": (city == "Black Market"),
                "item_value": 0.0,  # Filled below
                "_ts": p.captured_at,
            }

        if scan_bm:
            # Black Market snapshots (Caerleon buy orders)
            bm_cutoff = datetime.utcnow() - timedelta(hours=2)
            bm_rows = (
                db.query(BlackMarketSnapshot)
                .filter(BlackMarketSnapshot.captured_at >= bm_cutoff)
                .all()
            )

            for bm in bm_rows:
                item_id = bm.item_id
                if bm.enchantment and bm.enchantment > 0:
                    item_id = f"{item_id}@{bm.enchantment}"

                quality = bm.quality or 1
                city = "Black Market"

                if item_id not in prices:
                    prices[item_id] = {}
                if city not in prices[item_id]:
                    prices[item_id][city] = {}

                existing = prices[item_id][city].get(quality)
                if (
                    existing
                    and bm.captured_at
                    and existing.get("_ts")
                    and bm.captured_at <= existing["_ts"]
                ):
                    continue

                # Recompute BM data age dynamically
                bm_api_age = int(bm.data_age_seconds or 0)
                if bm.captured_at:
                    bm_db_age = (datetime.utcnow() - bm.captured_at).total_seconds()
                else:
                    bm_db_age = 0
                bm_effective_age = bm_api_age + bm_db_age

                prices[item_id][city][quality] = {
                    "sell_price_min": 0,
                    "buy_price_max": bm.buy_price_max or 0,
                    "volume_24h": 1,
                    "data_age_seconds": int(bm_effective_age),
                    "is_black_market": True,
                    "_ts": bm.captured_at,
                }

        from app.core.market_utils import apply_enchantment_ceiling_crafting
        apply_enchantment_ceiling_crafting(prices)

        return prices

    def _load_item_metadata(self, db: Session) -> tuple[dict, dict, dict, dict]:
        """Returns (item_names, item_categories, item_values, item_weights)"""
        # Ensure your Item model has a 'weight' column (or gracefully fallback)
        try:
            rows = db.query(Item.item_id, Item.name, Item.category, Item.item_value, getattr(Item, "weight", None).label("weight")).all()
        except Exception:
            rows = db.query(Item.item_id, Item.name, Item.category, Item.item_value).all()
            
        names = {r.item_id: r.name for r in rows}
        categories = {r.item_id: (r.category or "") for r in rows}
        values = {r.item_id: float(r.item_value or 0.0) for r in rows}
        weights = {r.item_id: float(getattr(r, "weight", 0.0) or 0.0) for r in rows}
        return names, categories, values, weights


    def _load_recipes(self, db: Session) -> dict:
        """
        Build recipe map: {item_id: {"ingredients": [{"item_id": str, "quantity": float}]}}
        Filters out raw-resource-only ingredients for non-refining crafts (same logic
        as existing engine, but simplified and less lossy).
        """
        rows = db.query(Recipe).all()
        recipes: dict[str, dict] = {}
        for r in rows:
            cid = r.crafted_item_id
            if cid not in recipes:
                recipes[cid] = {"ingredients": []}
            recipes[cid]["ingredients"].append(
                {
                    "item_id": r.ingredient_item_id,
                    "quantity": float(r.quantity or 1),
                }
            )

        # Generate enchanted recipes for items that can be enchanted
        enchanted_recipes = {}
        for cid, recipe in recipes.items():
            # Skip if already enchanted (shouldn't be in DB usually, but just in case)
            if "@" in cid:
                continue

            for e in [1, 2, 3, 4]:
                modified_ingredients = []
                for ing in recipe["ingredients"]:
                    ing_id = ing["item_id"]
                    # Skip artifacts and runes/souls/relics/sigils which are not enchanted
                    if any(x in ing_id for x in ["ARTEFACT", "RUNE", "SOUL", "RELIC", "SIGIL"]):
                        modified_ingredients.append(ing)
                    else:
                        modified_ingredients.append(
                            {"item_id": f"{ing_id}@{e}", "quantity": ing["quantity"]}
                        )
                enchanted_recipes[f"{cid}@{e}"] = {"ingredients": modified_ingredients}

        recipes.update(enchanted_recipes)
        return recipes

    # ── Main entry point ────────────────────────────────────────────────────

    async def scan_all(
        self, db: Session = None, scan_bm: bool = False, lookback_hours: float = 4.0
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
        """
        Returns (bm_opps, craft_opps, arb_opps, refining_opps, mm_opps, enchant_opps) as plain dicts
        ready for DB storage and Discord alerts. All sorted by score descending.
        Runs all scanners in one unified pass, optionally returning raw dicts.
        """
        from app.core import state

        # Use dynamic thresholds from state
        self.engine.min_arb_profit = self.default_min_arb_profit
        self.engine.min_craft_profit = state.min_craft_profit
        self.engine.min_bm_profit = state.min_bm_profit
        self.engine.allow_enchant_transport = getattr(state, "allow_enchant_transport", False)

        if db is None:
            db_context = get_db_session()
            session = db_context.__enter__()
        else:
            session = db
            db_context = None
            
        try:
            log.info("[UNIFIED SCANNER] Loading prices...")
            prices = self._load_prices(session, lookback_hours=lookback_hours, scan_bm=scan_bm)
            log.info(f"[UNIFIED SCANNER] {len(prices)} items loaded.")

            names, categories, values, weights = self._load_item_metadata(session)
            recipes = self._load_recipes(session)

            bm_raw = []
            enchant_raw = []
            if scan_bm:
                log.info("[UNIFIED SCANNER] Scanning Black Market...")
                bm_raw = self.engine.scan_black_market(prices, names, recipes, categories, values, weights)
                log.info(f"[UNIFIED SCANNER] BM: {len(bm_raw)} opportunities")
                
                log.info("[UNIFIED SCANNER] Scanning Enchantment Flips...")
                enchant_raw = self.engine.scan_enchanting(prices, names, categories)
                log.info(f"[UNIFIED SCANNER] Enchantment: {len(enchant_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Crafting...")
            craft_raw = self.engine.scan_crafting(prices, names, recipes, categories, values, weights)
            log.info(f"[UNIFIED SCANNER] Crafting: {len(craft_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Arbitrage...")
            arb_raw = self.engine.scan_arbitrage(prices, names, weights)
            log.info(f"[UNIFIED SCANNER] Arbitrage: {len(arb_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Refining...")
            refine_raw = self.engine.scan_refining(prices, names, recipes, categories, values, weights)
            log.info(f"[UNIFIED SCANNER] Refining: {len(refine_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Market Making...")
            mm_raw = self.engine.scan_market_making(prices, names, weights)
            log.info(f"[UNIFIED SCANNER] MM: {len(mm_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Quality Inversions...")
            quality_raw = self.engine.scan_quality_inversions(prices, names)
            log.info(f"[UNIFIED SCANNER] Quality Inversions: {len(quality_raw)} opportunities")

            return (
                [self._bm_to_dict(o, categories.get(o.item_id, "Unknown")) for o in bm_raw] if scan_bm else [],
                [self._craft_to_dict(o, categories.get(o.item_id, "Unknown")) for o in craft_raw],
                [self._arb_to_dict(o, categories.get(o.item_id, "Unknown")) for o in arb_raw],
                [self._refine_to_dict(o, categories.get(o.item_id, "Unknown")) for o in refine_raw],
                [self._mm_to_dict(o, categories.get(o.item_id, "Unknown")) for o in mm_raw],
                [self._enchant_to_dict(o, categories.get(o.target_item_id, "Unknown")) for o in enchant_raw] if scan_bm else [],
                [self._quality_to_dict(o, categories.get(o.item_id, "Unknown")) for o in quality_raw],
            )
        finally:
            if db_context:
                db_context.__exit__(None, None, None)

    # ── Dict converters for compatibility with existing DB/Discord code ─────

    def _quality_to_dict(self, o, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": f"{o.item_name} ({o.buy_quality_name})",
            "source_city": o.city,
            "destination_city": o.city,
            "buy_price": o.buy_price,
            "sell_price": o.reference_price,
            "estimated_profit": o.net_profit,
            "estimated_margin": o.profit_pct,
            "profit": o.net_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "buy_quality": o.buy_quality,
            "buy_quality_name": o.buy_quality_name,
            "reference_quality": o.reference_quality,
            "reference_quality_name": o.reference_quality_name,
            "inversion_type": o.inversion_type,
            "safe_limit": o.safe_limit,
            "roi": o.profit_pct,
            "daily_volume": o.daily_volume,
            "data_age_seconds": o.data_age_seconds,
            "ev_score": o.score,
            "category": category,
            "type": "quality_misprice",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _enchant_to_dict(self, o, category: str) -> dict[str, Any]:
        base_c = getattr(o, "base_city", "Caerleon")
        return {
            "item_id": o.target_item_id,
            "target_item_id": o.target_item_id,
            "item_name": self._enhance_name(o.target_item_id, o.target_item_name, getattr(o, "quality", 1)),
            "base_item_id": o.base_item_id,
            "base_price": o.base_price,
            "base_city": base_c,
            "material_id": o.material_id,
            "material_qty": o.material_qty,
            "material_price": o.material_price,
            "bm_buy_price": o.bm_buy_price,
            "estimated_profit": o.net_profit,
            "estimated_margin": o.profit_pct,
            "profit": o.net_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "source_city": base_c,
            "destination_city": "Black Market",
            "total_cost": o.total_cost,
            "safe_limit": o.safe_limit,
            "roi": o.roi,
            "quality": o.quality,
            "data_age_base": getattr(o, "data_age_base", 0),
            "data_age_material": getattr(o, "data_age_material", 0),
            "data_age_bm": getattr(o, "data_age_bm", 0),
            "category": category,
            "type": "enchanting",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _enhance_name(self, item_id: str, item_name: str, quality: int) -> str:
        display_name = item_name
        if "@" in item_id:
            enchant = f" .{item_id.split('@')[1]}"
            if enchant not in display_name:
                display_name += enchant
        if quality and quality > 1:
            quality_names = {1: "", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
            display_name += f" ({quality_names.get(quality, 'Unknown')})"
        return display_name

    def _bm_to_dict(self, o: BMOpportunity, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": self._enhance_name(o.item_id, o.item_name, getattr(o, "quality", 1)),
            "source_city": o.buy_city,
            "destination_city": "Black Market",
            "buy_price": o.buy_price,
            "sell_price": o.bm_buy_price,
            "estimated_profit": o.effective_profit,
            "estimated_margin": o.profit_pct,
            "profit": o.effective_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "mode": o.mode,  # "BUY+RUN" or "CRAFT+RUN"
            "craft_cost": o.craft_cost,
            "craft_city": o.craft_city,
            "can_be_crafted": o.can_be_crafted,
            "daily_volume": o.daily_volume,
            "data_age_buy": o.data_age_buy,
            "data_age_bm": o.data_age_bm,
            "quality": o.quality,
            "ev_score": o.score,
            "risk_score": 0.5,  # BM always requires Caerleon run
            "type": "black_market",
            "category": category,
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _craft_to_dict(self, o: CraftingOpportunity, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": self._enhance_name(o.item_id, o.item_name, getattr(o, "quality", 1)),
            "crafting_city": o.craft_city,
            "source_city": o.craft_city,
            "sell_city": o.sell_city,
            "destination_city": o.sell_city,
            "sell_mode": o.sell_mode,  # "BM" or "MARKET"
            "craft_cost": o.material_cost_net + o.station_fee,
            "material_cost_gross": o.material_cost_gross,
            "material_cost_net": o.material_cost_net,
            "station_fee": o.station_fee,
            "rrr_used": o.rrr_used,
            "sell_price": o.sell_price,
            "revenue_net": o.revenue_net,
            "profit": o.profit,
            "estimated_profit": o.profit,
            "profit_margin": o.profit_pct,
            "estimated_margin": o.profit_pct,
            "profit_pct": o.profit_pct,
            "daily_volume": o.daily_volume,
            "data_age_materials": o.data_age_materials,
            "data_age_sell": o.data_age_sell,
            "use_focus": o.use_focus,
            "quality": o.quality,
            "ev_score": o.score,
            "ingredients": o.ingredients,
            "type": "crafting",
            "category": category,
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _refine_to_dict(self, o: RefiningOpportunity, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": self._enhance_name(o.item_id, o.item_name, o.quality),
            "buy_city": getattr(o, "buy_city", ""),
            "refine_city": o.refine_city,
            "crafting_city": o.refine_city,
            "source_city": getattr(o, "buy_city", "") or o.refine_city,
            "sell_city": o.sell_city,
            "destination_city": o.sell_city,
            "material_cost_gross": o.material_cost_gross,
            "rrr_used": o.rrr_used,
            "material_cost_net": o.material_cost_net,
            "station_fee": o.station_fee,
            "craft_cost": o.material_cost_net + o.station_fee,
            "sell_price": o.sell_price,
            "revenue_net": o.revenue_net,
            "profit": o.profit,
            "estimated_profit": o.profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "estimated_margin": o.profit_pct,
            "daily_volume": o.daily_volume,
            "data_age_materials": o.data_age_materials,
            "data_age_sell": o.data_age_sell,
            "quality": o.quality,
            "use_focus": o.use_focus,
            "focus_cost": o.focus_cost,
            "silver_per_focus": o.silver_per_focus,
            "safe_limit": o.safe_limit,
            "roi": o.roi,
            "profit_per_kg": o.profit_per_kg,
            "ev_score": o.score,
            "ingredients": getattr(o, "ingredients", []),
            "category": category,
            "type": "refining",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _mm_to_dict(self, o: MarketMakingOpportunity, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": self._enhance_name(o.item_id, o.item_name, getattr(o, "quality", 1)),
            "source_city": o.source_city,
            "destination_city": o.destination_city,
            "buy_price": o.buy_price,
            "sell_price": o.sell_price,
            "gross_profit": o.gross_profit,
            "setup_fees": o.setup_fees,
            "tax_paid": o.tax_paid,
            "net_profit": o.net_profit,
            "profit": o.net_profit,
            "estimated_profit": o.net_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "estimated_margin": o.profit_pct,
            "daily_volume": o.daily_volume,
            "data_age_buy": o.data_age_buy,
            "data_age_sell": o.data_age_sell,
            "is_dangerous_route": getattr(o, "is_dangerous_route", False),
            "quality": getattr(o, "quality", 1),
            "safe_limit": getattr(o, "safe_limit", 1),
            "roi": getattr(o, "roi", 0.0),
            "profit_per_kg": getattr(o, "profit_per_kg", 0.0),
            "ev_score": getattr(o, "score", 0.0),
            "category": category,
            "type": "market_making",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _arb_to_dict(self, o: ArbitrageOpportunity, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": self._enhance_name(o.item_id, o.item_name, getattr(o, "quality", 1)),
            "source_city": o.buy_city,
            "destination_city": o.sell_city,
            "buy_price": o.buy_price,
            "sell_price": o.sell_price,  # This is buy_price_max (existing buy order)
            "estimated_profit": o.net_profit,
            "estimated_margin": o.profit_pct,
            "roi": getattr(o, "roi", o.profit_pct),
            "safe_limit": getattr(o, "safe_limit", 1),
            "profit_per_kg": getattr(o, "profit_per_kg", 0.0),
            "tax_paid": o.tax_paid,
            "is_dangerous": o.is_dangerous_route,
            "daily_volume": o.daily_volume,
            "data_age_buy": o.data_age_buy,
            "data_age_sell": o.data_age_sell,
            "quality": o.quality,
            "ev_score": o.score,
            "risk_score": 0.7 if o.is_dangerous_route else 0.2,
            "type": "arbitrage",
            "category": category,
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def save_opportunities(
        self,
        db: Session,
        bm_opps: list[dict],
        craft_opps: list[dict],
        arb_opps: list[dict],
        refining_opps: list[dict] | None = None,
        mm_opps: list[dict] | None = None,
        enchant_opps: list[dict] | None = None,
        quality_opps: list[dict] | None = None,
    ):
        """Save opportunities to the database, marking old ones as inactive."""
        from app.db.models import ArbitrageOpportunity, CraftingOpportunity
        import json

        # Deactivate old ones
        db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).update({"is_active": False})
        db.query(CraftingOpportunity).filter(CraftingOpportunity.is_active == True).update({"is_active": False})
        db.commit()

        # Save new Arbitrage & BM opportunities
        for o in arb_opps:
            db.add(ArbitrageOpportunity(
                item_id=o["item_id"],
                item_name=o["item_name"],
                source_city=o["source_city"],
                destination_city=o["destination_city"],
                buy_price=o["buy_price"],
                sell_price=o["sell_price"],
                estimated_profit=float(o["estimated_profit"]),
                estimated_margin=float(o["estimated_margin"]),
                risk_score=float(o["risk_score"]),
                daily_volume=int(o["daily_volume"]),
                volume_source=o.get("volume_source", "ESTIMATED"),
                safe_limit=o.get("safe_limit", 1),
                current_supply=o.get("current_supply", 0),
                market_gap=o.get("market_gap", 0),
                expected_hourly_profit=o.get("expected_hourly_profit", 0.0),
                ev_score=float(o["ev_score"]),
                volatility=o.get("volatility", 0.0),
                z_score=o.get("z_score", 0.0),
                persistence=o.get("persistence", 1),
                is_active=True
            ))

        for o in bm_opps:
            db.add(ArbitrageOpportunity(
                item_id=o["item_id"],
                item_name=o["item_name"],
                source_city=o["source_city"],
                destination_city=o["destination_city"],
                buy_price=o["buy_price"],
                sell_price=o["sell_price"],
                estimated_profit=float(o["estimated_profit"]),
                estimated_margin=float(o["estimated_margin"]),
                risk_score=float(o["risk_score"]),
                daily_volume=int(o["daily_volume"]),
                volume_source=o.get("volume_source", "ESTIMATED"),
                safe_limit=o.get("safe_limit", 1),
                current_supply=o.get("current_supply", 0),
                market_gap=o.get("market_gap", 0),
                expected_hourly_profit=o.get("expected_hourly_profit", 0.0),
                ev_score=float(o["ev_score"]),
                volatility=o.get("volatility", 0.0),
                z_score=o.get("z_score", 0.0),
                persistence=o.get("persistence", 1),
                is_active=True
            ))

        # Save new Crafting opportunities
        for o in craft_opps:
            db.add(CraftingOpportunity(
                item_id=o["item_id"],
                item_name=o["item_name"],
                crafting_city=o["crafting_city"],
                sell_city=o["sell_city"],
                craft_cost=float(o["craft_cost"]),
                sell_price=float(o["sell_price"]),
                profit=float(o["profit"]),
                profit_margin=float(o["profit_margin"]),
                focus_cost=o.get("focus_cost", 0.0),
                profit_per_focus=o.get("profit_per_focus", 0.0),
                silver_per_nutrition=o.get("silver_per_nutrition", 0.0),
                journal_profit=o.get("journal_profit", 0.0),
                daily_volume=int(o["daily_volume"]),
                volume_source=o.get("volume_source", "ESTIMATED"),
                safe_limit=o.get("safe_limit", 1),
                current_supply=o.get("current_supply", 0),
                market_gap=o.get("market_gap", 0),
                ev_score=float(o["ev_score"]),
                volatility=o.get("volatility", 0.0),
                persistence=o.get("persistence", 1),
                ingredients_json=json.dumps(o.get("ingredients", [])),
                decision_log=o.get("decision_log", ""),
                is_active=True
            ))

        db.commit()
