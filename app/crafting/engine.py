"""
Crafting ROI Engine for Albion Online.
Identifies best silver/focus crafting opportunities with recursive optimization.
"""

import json
from datetime import datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    ALL_MARKET_CITIES,
    BASE_RESOURCE_RETURN_RATE,
    CITY_BONUS_RESOURCE_RETURN_RATE,
    CITY_CRAFTING_BONUSES,
    DEFAULT_STATION_FEE,
    FOCUS_RESOURCE_RETURN_RATE,
    REFINING_BONUS_RESOURCE_RETURN_RATE,
    REFINING_FOCUS_RESOURCE_RETURN_RATE,
)
from app.core.logging import log
from app.db.models import CraftingOpportunity, Item, MarketHistory, MarketPrice, Recipe
from app.db.session import get_db_session


class CraftingEngine:
    """
    Calculates crafting profitability with recursive procurement optimization.
    It determines the cheapest "Entry Point" in a recipe tree.
    """

    def __init__(self):
        self.opportunities: list[dict] = []
        self.stats = {"recipes_evaluated": 0, "profitable_found": 0, "skipped_no_price": 0}

    def _get_latest_prices_map(self, db: Session) -> dict:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        # Fetch ALL qualities
        recent_prices = db.query(MarketPrice).filter(MarketPrice.fetched_at >= cutoff).all()
        prices: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
        for p in recent_prices:
            item_id = cast(str, p.item_id)
            city = cast(str, p.city)
            quality = cast(int, p.quality)
            if item_id not in prices:
                prices[item_id] = {}
            if city not in prices[item_id]:
                prices[item_id][city] = {}
            
            city_data = prices[item_id][city].get(quality)
            if not city_data or p.fetched_at > city_data["fetched_at"]:
                prices[item_id][city][quality] = {
                    "sell_price_min": p.sell_price_min,
                    "buy_price_max": p.buy_price_max,
                    "fetched_at": p.fetched_at
                }
        return prices

    def _get_recipes(self, db: Session) -> dict:
        recipes = db.query(Recipe).join(Item, Recipe.crafted_item_id == Item.item_id).filter(Item.category != "vanity").all()
        valid_items = set([i[0] for i in db.query(Item.item_id).all()])
        recipe_map: dict[str, dict[str, Any]] = {}
        for r in recipes:
            crafted_id = cast(str, r.crafted_item_id)
            ing_id = cast(str, r.ingredient_item_id)
            if "@" in crafted_id:
                level = crafted_id.split("@")[1]
                if f"{ing_id}@{level}" in valid_items: ing_id = f"{ing_id}@{level}"
            if crafted_id not in recipe_map:
                recipe_map[crafted_id] = {
                    "ingredients": [],
                    "nutrition": r.nutrition_cost or 0.0,
                    "focus": r.focus_cost or 0.0,
                    "fame": r.crafting_fame or 0.0
                }
            recipe_map[crafted_id]["ingredients"].append({"item_id": ing_id, "quantity": r.quantity})
        return recipe_map

    def _get_market_stats_map(self, db: Session) -> dict[tuple[str, str], dict]:
        """Build 24h volume and volatility stats once for crafting sell-city checks."""
        from datetime import timedelta

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
                volatility = (variance ** 0.5) / mean if mean > 0 else 0.05
            stats[key] = {"volume": bucket["volume"], "volatility": volatility}

        return stats

    def _get_rrr(self, item_id: str, city: str, use_focus: bool) -> float:
        base = item_id.split("@")[0]
        # Better category extraction
        cat = "_".join(base.split("_")[1:]).lower() if "_" in base else base.lower()
        
        is_refining = any(r in cat for r in ["ore", "wood", "fiber", "hide", "rock", "stone", "bar", "plank", "cloth", "leather"])
        city_bonus = CITY_CRAFTING_BONUSES.get(city, {})
        
        # 1. Check Refining Bonuses
        if is_refining:
            if any(b in cat for b in city_bonus.get("refining_bonus", [])):
                return REFINING_FOCUS_RESOURCE_RETURN_RATE if use_focus else REFINING_BONUS_RESOURCE_RETURN_RATE
            return FOCUS_RESOURCE_RETURN_RATE if use_focus else BASE_RESOURCE_RETURN_RATE

        # 2. Check City Crafting Bonuses (Equipment, Capes, etc.)
        bonus_cats = city_bonus.get("bonus_categories", [])
        if any(b in cat for b in bonus_cats):
            # Special case for capes/bags which might have lower base but can benefit from city bonus
            return FOCUS_RESOURCE_RETURN_RATE if use_focus else CITY_BONUS_RESOURCE_RETURN_RATE

        # 3. Items with NO base return rate but CAN have focus return rate
        if any(x in cat for x in ["bag", "mount", "potion", "food"]):
            return FOCUS_RESOURCE_RETURN_RATE if use_focus else 0.0
        
        if "cape" in cat:
            # Capes only have RRR in bonus cities (Lymhurst)
            return FOCUS_RESOURCE_RETURN_RATE if use_focus else 0.0

        # 4. Default Royal RRR
        return FOCUS_RESOURCE_RETURN_RATE if use_focus else BASE_RESOURCE_RETURN_RATE

    def _resolve_optimal_procurement(self, item_id, qty, prices, recipes, city, item_names, depth=0):
        """Recursively find the cheapest way to get an item (Buy vs Craft)."""
        display_name = item_names.get(item_id, item_id)

        # 1. Market Price (Baseline)
        p_data = prices.get(item_id, {}).get(city, {})
        market_price = p_data.get("sell_price_min") or 0.0
        if market_price <= 100:
            others = [x.get("sell_price_min", 0) or 0 for x in prices.get(item_id, {}).values() if (x.get("sell_price_min") or 0) > 100]
            market_price = min(others) if others else 0.0

        # 2. Crafting Cost (Option)
        craft_cost = None
        sub_details = []
        decision_lines = []
        if depth < 2 and item_id in recipes:
            recipe = recipes[item_id]
            ing_total = 0.0
            temp_details = []
            valid_sub = True
            for ing in recipe["ingredients"]:
                res = self._resolve_optimal_procurement(ing["item_id"], ing["quantity"] * qty, prices, recipes, city, item_names, depth + 1)
                if res["unit_cost"] == 0:
                    valid_sub = False; break
                ing_total += res["total_cost"]
                temp_details.extend(res["details"])

            if valid_sub:
                rrr = self._get_rrr(item_id, city, use_focus=False)
                # Station fee (scaled by qty)
                fee = ((recipe.get("nutrition") or 0.0) * DEFAULT_STATION_FEE / 100.0) * qty
                # Simple return value calculation
                # Simplified return logic for sub-crafts to avoid recursion bloat
                returns = ing_total * rrr * 0.8 # conservative estimate
                craft_cost = (ing_total + fee - returns) / qty
                sub_details = temp_details

        # Pick best
        should_craft = craft_cost is not None and (
            market_price <= 0 or craft_cost < market_price * 0.95
        )
        if should_craft:
            decision_lines.append(f"CRAFT {display_name} x{qty:g} (unit~{craft_cost:,.0f})")
            return {
                "unit_cost": craft_cost,
                "total_cost": craft_cost * qty,
                "details": sub_details,
                "mode": "CRAFT",
                "lines": decision_lines,
            }
        else:
            decision_lines.append(f"BUY {display_name} x{qty:g} (unit~{market_price:,.0f})")
            return {
                "unit_cost": market_price,
                "total_cost": market_price * qty,
                "details": [{"id": item_id, "name": display_name, "quantity": qty, "unit_price": market_price, "total_price": market_price * qty}],
                "mode": "BUY",
                "lines": decision_lines,
            }

    async def compute(self, crafting_city_filter: str = None) -> list[dict]:
        """Run optimized computation with recursive tree awareness."""
        log.info(f"🚀 Starting Recursive Crafting Tree Analysis (filter={crafting_city_filter})...")
        self.opportunities = []
        with get_db_session() as db:
            db = cast(Session, db)
            prices = self._get_latest_prices_map(db)
            recipes = self._get_recipes(db)
            # Fetch names and item_values
            items_data = db.query(Item.item_id, Item.name, Item.item_value).all()
            item_names = {i[0]: i[1] for i in items_data}
            item_values = {i[0]: i[2] or 0.0 for i in items_data}
            market_stats = self._get_market_stats_map(db)

        for item_id, recipe_data in recipes.items():
            for city in ALL_MARKET_CITIES:
                if crafting_city_filter and city.lower() != crafting_city_filter.lower():
                    continue

                total_ing_cost = 0.0
                final_shopping_list = []
                decision_lines = []
                rrr = self._get_rrr(item_id, city, use_focus=True)

                # Procurement check (Top level)
                for ing in recipe_data["ingredients"]:
                    res = self._resolve_optimal_procurement(ing["item_id"], ing["quantity"], prices, recipes, city, item_names)
                    if res["unit_cost"] == 0: total_ing_cost = 0; break
                    total_ing_cost += res["total_cost"]
                    final_shopping_list.extend(res["details"])
                    decision_lines.extend(res.get("lines", []))

                if total_ing_cost == 0: continue

                # Calculate RRR Value
                return_val = 0.0
                for ing in recipe_data["ingredients"]:
                    p_map = prices.get(ing["item_id"], {}).get(city, {})
                    # Default to quality 1 for return value baseline
                    p = p_map.get(1, {}).get("sell_price_min", 0)
                    if not any(x in ing["item_id"].upper() for x in ["_CREST", "_ARTIFACT", "_SOUL", "_RELIC", "_RUNE", "_SHARD"]):
                        return_val += (p * ing["quantity"] * rrr)

                # Station Fee: (ItemValue * 0.11 * StationTax) / 100
                # Using DEFAULT_STATION_FEE as the StationTax (e.g. 1200)
                item_val = item_values.get(item_id, 0.0)
                from app.core.constants import calculate_station_fee
                fee = calculate_station_fee(item_val, DEFAULT_STATION_FEE)
                craft_cost = total_ing_cost + fee - return_val
                if craft_cost <= 0: continue

                if item_id not in prices: continue

                # Check all cities and ALL QUALITIES
                for sell_city, quality_map in prices[item_id].items():
                    for quality, sell_data in quality_map.items():
                        sell_p = sell_data.get("sell_price_min", 0)
                        if sell_p <= 0: continue
                        
                        # Sanity check
                        stats = market_stats.get((item_id, sell_city), {"volume": 0, "volatility": 0.05})
                        real_vol = stats["volume"]
                        if (sell_p > craft_cost * 10) and (real_vol <= 0): continue
                        
                        profit = sell_p - craft_cost - (sell_p * settings.tax_rate) - (sell_p * settings.setup_fee_rate)
                        
                        # Add Journal Profit (Approx 10% of ingredient cost for now)
                        journal_val = total_ing_cost * 0.08 if "JOURNAL" not in item_id else 0
                        total_profit = profit + journal_val
                        
                        if total_profit <= settings.min_crafting_profit: continue
                        margin = (total_profit / craft_cost) * 100

                        self.opportunities.append({
                            "item_id": item_id, "item_name": f"{item_names.get(item_id, item_id)} (Q{quality})",
                            "quality": quality,
                            "crafting_city": city, "sell_city": sell_city,
                            "craft_cost": round(craft_cost, 2), "sell_price": sell_p,
                            "profit": round(total_profit, 2), "profit_margin": round(margin, 2),
                            "journal_profit": round(journal_val, 2),
                            "focus_cost": recipe_data["focus"],
                            "daily_volume": real_vol, "volume_source": "VERIFIED 24H" if real_vol > 0 else "ESTIMATED",
                            "volatility": stats["volatility"], "persistence": 1,
                            "ingredients_detail": final_shopping_list, # Simplified
                            "detected_at": datetime.utcnow().isoformat(), "is_active": True
                        })

                        # EV Scoring
                        from app.core.scoring import scorer
                        opp_data = self.opportunities[-1]
                        opp_data["buy_price"] = craft_cost
                        opp_data["ev_score"] = scorer.score_arbitrage(opp_data)
                        if opp_data["ev_score"] <= 0: self.opportunities.pop()

        log.info(f"✨ Found {len(self.opportunities)} hard-fact crafting opportunities.")
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
                    "profit": o["profit"], "profit_margin": o["profit_margin"], "focus_cost": o.get("focus_cost", 0),
                    "daily_volume": o.get("daily_volume", 0), "volume_source": o.get("volume_source", "EST"),
                    "ev_score": o.get("ev_score", 0.0),
                    "volatility": o.get("volatility", 0.0),
                    "persistence": o.get("persistence", 1),
                    "ingredients_json": json.dumps(o.get("ingredients_detail", [])),
                    "detected_at": datetime.utcnow(), "is_active": True
                })
            if mappings:
                from sqlalchemy import insert
                db.execute(insert(CraftingOpportunity), mappings)
            return len(mappings)
