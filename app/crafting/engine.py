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
    REFINING_BONUS_RRR,
    REFINING_FOCUS_RRR,
    is_price_sane,
)
from app.core.logging import log
from app.core.market_utils import calculate_blended_price
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
                return REFINING_FOCUS_RRR if use_focus else REFINING_BONUS_RRR
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

    def _get_best_price_anywhere(self, item_id: str, prices: dict) -> float:
        """Find the lowest sell price across all known cities as a fallback."""
        all_prices = []
        for city_map in prices.get(item_id, {}).values():
            for q_map in city_map.values():
                p = q_map.get("sell_price_min", 0)
                if p > 10: all_prices.append(p)
        return min(all_prices) if all_prices else 0.0

    def _resolve_optimal_procurement(self, item_id, qty, prices, recipes, city, item_names, depth=0):
        """Recursively find the cheapest way to get an item (Buy vs Craft)."""
        display_name = item_names.get(item_id, item_id)

        # 1. Market Price (Baseline with fallback)
        p_data = prices.get(item_id, {}).get(city, {}).get(1, {})
        market_price = p_data.get("sell_price_min") or 0.0
        if market_price <= 0:
            market_price = self._get_best_price_anywhere(item_id, prices)

        # 2. Crafting Cost (Option)
        craft_cost = None
        sub_details = []
        decision_lines = []
        
        # Increased depth for complex May 2026 paths
        if depth < 3 and item_id in recipes:
            recipe = recipes[item_id]
            ing_total = 0.0
            temp_details = []
            valid_sub = True
            
            # Keep track of resolved unit costs for RRR later
            resolved_ing_prices = {}
            
            for ing in recipe["ingredients"]:
                res = self._resolve_optimal_procurement(ing["item_id"], ing["quantity"] * qty, prices, recipes, city, item_names, depth + 1)
                if res["unit_cost"] == 0:
                    valid_sub = False; break
                ing_total += res["total_cost"]
                resolved_ing_prices[ing["item_id"]] = res["unit_cost"]
                temp_details.extend(res["details"])

            if valid_sub:
                rrr = self._get_rrr(item_id, city, use_focus=False)
                # Station fee (simplified for sub-crafts to avoid recursion bloat)
                fee = 0 
                
                # Use resolved prices for a more accurate RRR return
                returns = 0.0
                for ing in recipe["ingredients"]:
                    if not any(x in ing["item_id"].upper() for x in ["_CREST", "_ARTIFACT", "_SOUL", "_RELIC"]):
                        unit_p = resolved_ing_prices.get(ing["item_id"], 0)
                        returns += (unit_p * ing["quantity"] * qty * rrr)
                
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

    def _calculate_journal_profit(self, item_id: str, fame: float, prices: dict, city: str) -> float:
        """Calculate silver profit from filled journals based on 2026 fame requirements."""
        from app.core.constants import JOURNAL_FAME_REQUIRED, get_journal_id
        
        tier_str = item_id.split("_")[0].replace("T", "")
        if not tier_str.isdigit(): return 0.0
        tier = int(tier_str)
        
        fame_needed = JOURNAL_FAME_REQUIRED.get(tier)
        if not fame_needed or fame <= 0: return 0.0
        
        # Get category for journal mapping
        # item_id example: T4_ARMOR_PLATE_SET1
        parts = item_id.split("_")
        category = parts[1].lower() if len(parts) > 1 else ""
        
        empty_id = get_journal_id(category, tier)
        if not empty_id: return 0.0
        
        full_id = empty_id.replace("_EMPTY", "_FULL")
        
        # Fetch prices for journals in the crafting city
        p_empty = prices.get(empty_id, {}).get(city, {}).get(1, {}).get("sell_price_min") or (tier * 1000)
        p_full = prices.get(full_id, {}).get(city, {}).get(1, {}).get("sell_price_min") or (p_empty + tier * 5000)
        
        profit_per_journal = p_full - p_empty
        journals_filled = fame / fame_needed
        
        return journals_filled * profit_per_journal

    async def compute(self, crafting_city_filter: str = None) -> list[dict]:
        """Run optimized computation with recursive tree awareness and hard-fact math."""
        log.info(f"🚀 Starting Recursive Crafting Tree Analysis (May 2026 Logic)...")
        from app.core.constants import SETUP_FEE, PREMIUM_SALES_TAX, NON_PREMIUM_SALES_TAX
        
        self.opportunities = []
        with get_db_session() as db:
            db = cast(Session, db)
            prices = self._get_latest_prices_map(db)
            recipes = self._get_recipes(db)
            items_data = db.query(Item.item_id, Item.name, Item.item_value).all()
            item_names = {i[0]: i[1] for i in items_data}
            item_values = {i[0]: i[2] or 0.0 for i in items_data}
            market_stats = self._get_market_stats_map(db)

        tax_rate = PREMIUM_SALES_TAX if settings.is_premium else NON_PREMIUM_SALES_TAX

        for item_id, recipe_data in recipes.items():
            for city in ALL_MARKET_CITIES:
                if crafting_city_filter and city.lower() != crafting_city_filter.lower():
                    continue

                total_ing_cost = 0.0
                final_shopping_list = []
                decision_lines = []
                # Use focus for potential profit analysis
                rrr_focus = self._get_rrr(item_id, city, use_focus=True)
                rrr_no_focus = self._get_rrr(item_id, city, use_focus=False)

                # Recursive Procurement check
                resolved_ing_costs = {}
                for ing in recipe_data["ingredients"]:
                    # Depth 3 for May 2026 logic
                    res = self._resolve_optimal_procurement(ing["item_id"], ing["quantity"], prices, recipes, city, item_names, depth=0)
                    if res["unit_cost"] == 0: total_ing_cost = 0; break
                    total_ing_cost += res["total_cost"]
                    resolved_ing_costs[ing["item_id"]] = res["unit_cost"]
                    final_shopping_list.extend(res["details"])
                    decision_lines.extend(res.get("lines", []))

                if total_ing_cost == 0: continue

                # Station Fee: Precision 0.1125 constant
                item_val = item_values.get(item_id, 0.0)
                from app.core.constants import calculate_station_fee
                fee = calculate_station_fee(item_val, DEFAULT_STATION_FEE)

                # Journal Yield
                journal_profit = self._calculate_journal_profit(item_id, recipe_data["fame"], prices, city)

                # Calculate two costs: Focus and Non-Focus
                def calc_return(rate):
                    ret = 0.0
                    for ing in recipe_data["ingredients"]:
                        # Use resolved procurement price for RRR back calculation
                        unit_p = resolved_ing_costs.get(ing["item_id"], 0)
                        if unit_p == 0:
                            # Fallback to market
                            unit_p = prices.get(ing["item_id"], {}).get(city, {}).get(1, {}).get("sell_price_min", 0)
                            
                        if not any(x in ing["item_id"].upper() for x in ["_CREST", "_ARTIFACT", "_SOUL", "_RELIC"]):
                            ret += (unit_p * ing["quantity"] * rate)
                    return ret

                cost_focus = total_ing_cost + fee - calc_return(rrr_focus)
                cost_no_focus = total_ing_cost + fee - calc_return(rrr_no_focus)

                if item_id not in prices: continue

                for sell_city, quality_map in prices[item_id].items():
                    for quality, sell_data in quality_map.items():
                        sell_raw = sell_data.get("sell_price_min", 0)
                        buy_raw = sell_data.get("buy_price_max", 0)
                        
                        # BLENDED PRICE: Check cheapest sellers + buy order floor to get a realistic average
                        sell_p = calculate_blended_price(sell_raw, buy_raw, item_val)
                        
                        if sell_p <= 0: continue
                        
                        # SANITY CHECK: Detect outliers/manipulation (e.g. 85M horses)
                        if not is_price_sane(sell_p, item_val):
                            continue
                        
                        # Sales Tax Logic: In this tool, we assume sell_price_min is a Sell Order.
                        total_fees = (sell_p * SETUP_FEE) + (sell_p * tax_rate)
                        
                        # Profit Calculation
                        profit_no_focus = sell_p - cost_no_focus - total_fees + journal_profit
                        profit_focus = sell_p - cost_focus - total_fees + journal_profit
                        
                        if profit_no_focus < settings.min_crafting_profit and profit_focus < settings.min_crafting_profit:
                            continue

                        # Focus Efficiency
                        ppf = (profit_focus - profit_no_focus) / recipe_data["focus"] if recipe_data["focus"] > 0 else 0
                        profit_margin = (profit_no_focus / cost_no_focus) * 100 if cost_no_focus > 0 else 0
                        
                        stats = market_stats.get((item_id, sell_city), {"volume": 0, "volatility": 0.05})
                        real_vol = stats["volume"]

                        # Margin Sanity: Discard items with > 1000% margin as they are usually 
                        # market manipulation trolls or illiquid artifacts.
                        if profit_margin > 1000:
                            continue
                        
                        self.opportunities.append({
                            "item_id": item_id, "item_name": f"{item_names.get(item_id, item_id)} (Q{quality})",
                            "quality": quality, "crafting_city": city, "sell_city": sell_city,
                            "craft_cost": round(cost_no_focus, 2), "sell_price": sell_p,
                            "profit": round(profit_no_focus, 2), 
                            "profit_focus": round(profit_focus, 2),
                            "profit_margin": round(profit_margin, 2),
                            "profit_per_focus": round(ppf, 2),
                            "journal_profit": round(journal_profit, 2),
                            "focus_cost": recipe_data["focus"],
                            "daily_volume": real_vol, "volume_source": "VERIFIED 24H" if real_vol > 0 else "ESTIMATED",
                            "volatility": stats["volatility"], "persistence": 1,
                            "ingredients_detail": final_shopping_list,
                            "decision_log": decision_lines,
                            "detected_at": datetime.utcnow().isoformat(), "is_active": True
                        })

                        # EV Scoring
                        from app.core.scoring import scorer
                        opp_data = self.opportunities[-1]
                        opp_data["buy_price"] = cost_no_focus
                        opp_data["ev_score"] = scorer.score_arbitrage(opp_data)
                        if opp_data["ev_score"] <= 0: self.opportunities.pop()

        log.info(f"✨ Found {len(self.opportunities)} hard-fact crafting opportunities.")
        
        # DIVERSITY FILTER: Ensure top results aren't all the same category (Capes/Bags)
        self.opportunities.sort(key=lambda x: x["ev_score"], reverse=True)
        
        diverse_ops = []
        category_counts = {}
        for opp in self.opportunities:
            # Extract category (e.g., T4_CAPE -> CAPE)
            item_id = opp["item_id"]
            cat = item_id.split("_")[1] if "_" in item_id else "OTHER"
            
            # Limit any single category to 25% of top results
            count = category_counts.get(cat, 0)
            if count < 5 or len(diverse_ops) > 20: 
                diverse_ops.append(opp)
                category_counts[cat] = count + 1
            else:
                # Still include very high EV items even if category is full
                if opp["ev_score"] > 1000000: # 1M EV/hr threshold
                    diverse_ops.append(opp)

        return diverse_ops

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
                    "decision_log": json.dumps(o.get("decision_log", [])),
                    "detected_at": datetime.utcnow(), "is_active": True
                })
            if mappings:
                from sqlalchemy import insert
                db.execute(insert(CraftingOpportunity), mappings)
            return len(mappings)
