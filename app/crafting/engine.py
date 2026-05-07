"""
Crafting ROI Engine for Albion Online v3.0.
Recursive procurement optimization with verified RRR and market fee logic.
"""
import json
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import ALL_MARKET_CITIES, is_price_sane
from app.core.logging import log
from app.core.market_utils import calculate_rrr, calculate_net_material_cost, calculate_blended_price
from app.core.fees import calculate_sell_proceeds
from app.core.scoring import scorer
from app.db.models import CraftingOpportunity, Item, MarketPrice, Recipe, BlackMarketSnapshot
from app.db.session import get_db_session

class CraftingEngine:
    """
    Recursive Crafting Engine v3.0.
    """

    def __init__(self):
        self.opportunities: list[dict] = []
        self.stats = {"recipes_evaluated": 0, "profitable_found": 0}

    def _get_latest_prices_map(self, db: Session) -> dict:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_prices = db.query(MarketPrice).filter(
            MarketPrice.captured_at >= cutoff,
            MarketPrice.server == settings.active_server.value
        ).all()
        prices: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
        for p in recent_prices:
            item_id, city, quality = cast(str, p.item_id), cast(str, p.city), cast(int, p.quality)
            if item_id not in prices: prices[item_id] = {}
            if city not in prices[item_id]: prices[item_id][city] = {}
            
            city_data = prices[item_id][city].get(quality)
            if not city_data or p.captured_at > city_data["captured_at"]:
                prices[item_id][city][quality] = {
                    "sell_price_min": p.sell_price_min or 0,
                    "buy_price_max": p.buy_price_max or 0,
                    "volume_24h": p.volume_24h or 0,
                    "confidence_score": p.confidence_score or 1.0,
                    "captured_at": p.captured_at,
                    "is_black_market": False
                }
        
        # --- Black Market Integration ---
        bm_snapshots = db.query(BlackMarketSnapshot).filter(
            BlackMarketSnapshot.captured_at >= cutoff
        ).all()
        for bm in bm_snapshots:
            item_id, quality = bm.item_id, bm.quality
            if item_id not in prices: prices[item_id] = {}
            if "Black Market" not in prices[item_id]: prices[item_id]["Black Market"] = {}
            
        for bm in bm_snapshots:
            item_id, quality = bm.item_id, bm.quality
            if item_id not in prices: prices[item_id] = {}
            if "Black Market" not in prices[item_id]: prices[item_id]["Black Market"] = {}
            
            prices[item_id]["Black Market"][quality] = {
                "sell_price_min": 0,
                "buy_price_max": bm.buy_price_max or 0,
                "volume_24h": 1, # [v3.1] Corrected fallback to 1 to avoid Alpha hallucinations
                "confidence_score": 1.0,
                "captured_at": bm.captured_at,
                "is_black_market": True
            }
            
        return prices

    def _get_recipes(self, db: Session) -> dict:
        recipes = db.query(Recipe).all()
        recipe_map: dict[str, dict[str, Any]] = {}
        for r in recipes:
            c_id = cast(str, r.crafted_item_id)
            if c_id not in recipe_map:
                recipe_map[c_id] = {"ingredients": [], "fame": r.crafting_fame or 0.0}
            recipe_map[c_id]["ingredients"].append({"item_id": r.ingredient_item_id, "quantity": r.quantity})
        return recipe_map

    def _resolve_optimal_procurement(self, item_id, qty, prices, recipes, city, item_names, depth=0):
        """Calculates the most efficient way to acquire an item (Buy vs. Craft)."""
        p_data = prices.get(item_id, {}).get(city, {}).get(1, {})
        market_price = p_data.get("sell_price_min") or 0.0
        
        # BUY mode cost (including market setup fee)
        buy_unit_cost = market_price * (1 + settings.market_setup_fee_pct) if market_price > 0 else 0
        
        craft_unit_cost = None
        ingredients_purchased = []
        
        # Attempt to craft if within depth limits and recipe exists
        if depth < 2 and item_id in recipes:
            recipe = recipes[item_id]
            ing_total_cost = 0.0
            valid_sub = True
            
            # Determine RRR for current city/item
            try:
                tier = int(item_id.split("_")[0].replace("T", "")) if "T" in item_id else 4
            except: tier = 4
            category = item_id.split("_")[1].lower() if "_" in item_id else "other"
            rrr = calculate_rrr(city, category, tier)

            for ing in recipe["ingredients"]:
                # Recursive call to find cheapest sub-procurement
                res = self._resolve_optimal_procurement(
                    ing["item_id"], 
                    ing["quantity"], # Resolve unit cost first
                    prices, recipes, city, item_names, depth + 1
                )
                
                if res["unit_cost"] <= 0:
                    valid_sub = False
                    break
                
                # Cost is (unit_cost * quantity_required)
                ing_total_cost += (res["unit_cost"] * ing["quantity"])
                
                # Add to path details (Summary only shows immediate ingredients to avoid double-counting)
                ingredients_purchased.append({
                    "id": ing["item_id"], 
                    "mode": res["mode"], 
                    "quantity": ing["quantity"], 
                    "unit_price": res["unit_cost"]
                })
            
            if valid_sub:
                # Crafting unit cost = (Ingredient sum * (1 - RRR))
                craft_unit_cost = ing_total_cost * (1.0 - rrr)

        # Decision: Craft if cheaper than buying
        should_craft = craft_unit_cost is not None and (buy_unit_cost <= 0 or craft_unit_cost < buy_unit_cost)
        
        if should_craft:
            return {
                "unit_cost": craft_unit_cost, 
                "total_cost": craft_unit_cost * qty, 
                "details": ingredients_purchased, 
                "mode": "CRAFT"
            }
        else:
            return {
                "unit_cost": buy_unit_cost, 
                "total_cost": buy_unit_cost * qty, 
                "details": [{"id": item_id, "mode": "BUY", "quantity": 1, "unit_price": buy_unit_cost}], 
                "mode": "BUY"
            }

    async def scan(self, crafting_city_filter: str = None) -> list[dict]:
        log.info(f"Crafting Tree Analysis v3.0 - START")
        self.opportunities = []
        with get_db_session() as db:
            db = cast(Session, db)
            prices = self._get_latest_prices_map(db)
            recipes = self._get_recipes(db)
            items = db.query(Item.item_id, Item.name, Item.category).all()
            item_names = {i[0]: i[1] for i in items}
            item_cats = {i[0]: i[2] for i in items}

        items_processed = 0
        sell_locations = ALL_MARKET_CITIES + ["Black Market"]

        for item_id, recipe_data in recipes.items():
            items_processed += 1
            if items_processed % 200 == 0:
                log.info(f"Crafting Tree Analysis: {items_processed} items analyzed...")

            for city in ALL_MARKET_CITIES:
                if crafting_city_filter and city.lower() != crafting_city_filter.lower():
                    continue

                # 1. Resolve procurement
                res = self._resolve_optimal_procurement(item_id, 1, prices, recipes, city, item_names)
                if res["unit_cost"] == 0: continue
                
                # [FIX] Only allow crafting opportunities where we actually *craft* the item
                if res["mode"] != "CRAFT":
                    continue

                cost_base = res["unit_cost"]
                
                # [NEW] Capital Check: Skip crafts that are too expensive
                if cost_base > settings.max_crafting_capital:
                    continue

                # 2. Evaluate sell cities
                if item_id not in prices: continue
                for sell_city, quality_map in prices[item_id].items():
                    for quality, sell_data in quality_map.items():
                        sell_p = calculate_blended_price(sell_data["sell_price_min"], sell_data["buy_price_max"])
                        if sell_p <= 0: continue
                        
                        # Apply v3.0 fees (Special Black Market logic)
                        if sell_data.get("is_black_market"):
                            net_proceeds = sell_data["buy_price_max"]
                        else:
                            proceeds = calculate_sell_proceeds(sell_p, premium=settings.is_premium)
                            net_proceeds = proceeds["net_proceeds"]

                        profit = net_proceeds - cost_base
                        
                        # Filter by absolute profit and percentage margin
                        if profit < settings.min_crafting_profit: continue
                        
                        margin = (profit / cost_base) * 100
                        if margin < settings.min_crafting_margin: continue

                        # [NEW] Volume Check: Skip zero-volume items except Black Market
                        if sell_data.get("volume_24h", 0) <= 0 and not sell_data.get("is_black_market"):
                            continue

                        opp = {
                            "item_id": item_id, "item_name": f"{item_names.get(item_id, item_id)} (Q{quality})",
                            "quality": quality, "crafting_city": city, "sell_city": sell_city,
                            "craft_cost": round(cost_base, 2), "sell_price": sell_p,
                            "profit": round(profit, 2), "profit_margin": round(margin, 2),
                            "daily_volume": sell_data["volume_24h"],
                            "volatility": 0.05, "persistence": 1,
                            "confidence_score": sell_data["confidence_score"],
                            "coverage_suspect": sell_data.get("volume_24h", 0) == 0,
                            "details": res.get("details", []),
                            "detected_at": datetime.utcnow().isoformat()
                        }
                        
                        opp["ev_score"] = scorer.score_crafting(opp)
                        if opp["ev_score"] > 0:
                            self.opportunities.append(opp)
                            
        self.opportunities.sort(key=lambda x: x["ev_score"], reverse=True)
        return self.opportunities

    def store_opportunities(self) -> int:
        if not self.opportunities: return 0
        with get_db_session() as db:
            db = cast(Session, db)
            db.query(CraftingOpportunity).filter(CraftingOpportunity.is_active == True).update({"is_active": False})
            mappings = []
            for o in self.opportunities:
                mappings.append({
                    "item_id": o["item_id"], "item_name": o["item_name"], "crafting_city": o["crafting_city"],
                    "sell_city": o["sell_city"], "craft_cost": o["craft_cost"], "sell_price": o["sell_price"],
                    "profit": o["profit"], "profit_margin": o["profit_margin"],
                    "daily_volume": o.get("daily_volume", 0), "ev_score": o.get("ev_score", 0.0),
                    "volatility": o.get("volatility", 0.0), "z_score": o.get("z_score", 0.0),
                    "persistence": o.get("persistence", 1),
                    "detected_at": datetime.utcnow(), "is_active": True
                })
            if mappings:
                from sqlalchemy import insert
                db.execute(insert(CraftingOpportunity), mappings)
            return len(mappings)
