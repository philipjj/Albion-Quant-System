"""
AQS Scanner Integration
========================
Drop-in replacement wrappers around OpportunityEngine that produce dicts
compatible with the existing DB models and Discord alerter.

Usage:
    from app.core.scanner_integration import UnifiedScanner
    scanner = UnifiedScanner()
    (
        bm_arb, craft, arb, refine, mm, enchant, quality, transmute,
        island, bm_craft, bm_refine, bm_enchant, bm_mm
    ) = await scanner.scan_all(db_session)
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
    get_min_realistic_price,
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
        min_roi: float = 5.0,
        default_trade_volume: int = 1,
    ):
        self.default_min_bm_profit = min_bm_profit
        self.default_min_craft_profit = min_craft_profit
        self.default_min_arb_profit = min_arb_profit
        self.min_roi = min_roi
        self.default_trade_volume = default_trade_volume

        self.engine = OpportunityScanner(
            min_bm_profit=min_bm_profit,
            min_craft_profit=min_craft_profit,
            min_arb_profit=min_arb_profit,
            min_roi=min_roi,
            default_trade_volume=default_trade_volume,
            use_focus=use_focus,
            premium=premium,
        )

    # ── Data loading ────────────────────────────────────────────────────────

    def _load_prices(self, db: Session, lookback_hours: float = 12.0, scan_bm: bool = False) -> dict:
        """
        Load latest prices into the nested dict structure OpportunityEngine expects.
        Merges DB historical records with live zero-latency NATS in-memory orderbook.
        Structure: {item_id: {city: {quality: {fields...}}}}
        """
        lookback = max(lookback_hours, 6.0)
        cutoff = datetime.utcnow() - timedelta(hours=lookback)
        prices: dict[str, dict[str, dict[int, dict]]] = {}

        # High-performance DB-API column tuple query (DESC order for fast first-hit caching)
        try:
            conn = db.connection().connection
            cursor = conn.cursor()
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """
                SELECT item_id, city, quality, sell_price_min, buy_price_max,
                       volume_24h, data_age_seconds, captured_at, sell_price_min_date, buy_price_max_date
                FROM market_prices
                WHERE server = ? AND captured_at >= ?
                ORDER BY captured_at DESC
                """,
                (settings.active_server.value, cutoff_str),
            )
            rows = cursor.fetchall()
        except Exception:
            rows = (
                db.query(
                    MarketPrice.item_id,
                    MarketPrice.city,
                    MarketPrice.quality,
                    MarketPrice.sell_price_min,
                    MarketPrice.buy_price_max,
                    MarketPrice.volume_24h,
                    MarketPrice.data_age_seconds,
                    MarketPrice.captured_at,
                    MarketPrice.sell_price_min_date,
                    MarketPrice.buy_price_max_date,
                )
                .filter(
                    MarketPrice.server == settings.active_server.value,
                    MarketPrice.captured_at >= cutoff,
                )
                .order_by(MarketPrice.captured_at.desc())
                .all()
            )
        log.info(
            f"[UNIFIED SCANNER] Loaded {len(rows)} raw price tuples from DB for server {settings.active_server.value} (cutoff: {cutoff})"
        )

        now = datetime.utcnow()
        for item_id, city, qual, sp_min, bp_max, vol_24h, age_sec, captured_at, sp_date, bp_date in rows:
            quality = qual or 1

            item_dict = prices.get(item_id)
            if item_dict is None:
                item_dict = {}
                prices[item_id] = item_dict

            city_dict = item_dict.get(city)
            if city_dict is None:
                city_dict = {}
                item_dict[city] = city_dict

            # Compute effective age from age_sec + time since capture
            is_bm = (city == "Black Market")
            effective_age = float(age_sec or 0.0)
            if captured_at:
                if isinstance(captured_at, datetime):
                    effective_age += max(0.0, (now - captured_at).total_seconds())
                elif isinstance(captured_at, str):
                    try:
                        cap_dt = datetime.fromisoformat(captured_at.replace(" ", "T"))
                        effective_age += max(0.0, (now - cap_dt).total_seconds())
                    except Exception:
                        pass

            min_realistic = get_min_realistic_price(item_id)
            is_sp_valid = (sp_min is not None and sp_min >= min_realistic)
            is_bp_valid = (bp_max is not None and bp_max > 0)

            if quality in city_dict:
                # If existing entry has a 0 or a troll price (< min_realistic), but older entry has a valid realistic price, preserve realistic price!
                if city_dict[quality]["sell_price_min"] < min_realistic and is_sp_valid:
                    city_dict[quality]["sell_price_min"] = sp_min
                    city_dict[quality]["data_age_seconds"] = int(effective_age)
                    city_dict[quality]["_ts"] = captured_at
                if city_dict[quality]["buy_price_max"] == 0 and is_bp_valid:
                    city_dict[quality]["buy_price_max"] = bp_max
                if vol_24h and city_dict[quality]["volume_24h"] == 0:
                    city_dict[quality]["volume_24h"] = vol_24h
                continue  # Already processed this quality level

            city_dict[quality] = {
                "sell_price_min": sp_min if is_sp_valid else (sp_min or 0),
                "buy_price_max": bp_max or 0,
                "volume_24h": vol_24h or 0,
                "data_age_seconds": int(effective_age),
                "is_black_market": is_bm,
                "item_value": 0.0,  # Filled below
                "_ts": captured_at,
            }

        # Intelligent Deep Merge: AODP historical DB prices + Live In-Memory NATS Level 2 Orderbook
        try:
            from app.ingestion.nats_client import nats_client
            live_nats = nats_client.get_live_prices_dict()
            nats_merged_count = 0
            for item_id, city_map in live_nats.items():
                if item_id not in prices:
                    prices[item_id] = {}
                for city, qual_map in city_map.items():
                    if city not in prices[item_id]:
                        prices[item_id][city] = {}
                    for q, nats_q in qual_map.items():
                        db_q = prices[item_id][city].get(q)
                        if db_q:
                            # Intelligently combine: take the freshest sell and buy prices
                            merged_sell = nats_q["sell_price_min"] if nats_q.get("sell_price_min", 0) > 0 else db_q.get("sell_price_min", 0)
                            merged_buy = nats_q["buy_price_max"] if nats_q.get("buy_price_max", 0) > 0 else db_q.get("buy_price_max", 0)
                            merged_vol = nats_q.get("volume_24h", 0) or db_q.get("volume_24h", 0) or 5
                            merged_age = min(nats_q.get("data_age_seconds", 0), db_q.get("data_age_seconds", 99999))
                            merged_val = db_q.get("item_value", 0.0) or nats_q.get("item_value", 0.0)

                            prices[item_id][city][q] = {
                                "sell_price_min": merged_sell,
                                "buy_price_max": merged_buy,
                                "volume_24h": merged_vol,
                                "data_age_seconds": merged_age,
                                "is_black_market": (city == "Black Market"),
                                "item_value": merged_val,
                                "sell_depth": nats_q.get("sell_depth", db_q.get("sell_depth", 0)),
                                "buy_depth": nats_q.get("buy_depth", db_q.get("buy_depth", 0)),
                                "avg_price_24h": nats_q.get("avg_price_24h", db_q.get("avg_price_24h", 0.0)),
                                "_ts": datetime.utcnow(),
                            }
                        else:
                            # NATS discovered a fresh item not yet present in AODP DB
                            prices[item_id][city][q] = {
                                **nats_q,
                                "volume_24h": nats_q.get("volume_24h", 0) or 5,
                                "item_value": 0.0,
                                "_ts": datetime.utcnow(),
                            }
                        nats_merged_count += 1
            if nats_merged_count > 0:
                log.info(f"[UNIFIED SCANNER] Intelligently merged {nats_merged_count} live LOB prices from NATS stream with AODP DB history.")
        except Exception as e:
            log.debug(f"[UNIFIED SCANNER] NATS memory merge skipped: {e}")

        if scan_bm:
            # Black Market snapshots (Caerleon buy orders — loaded up to 7 days, evaluated per-tier by get_max_allowed_bm_age_seconds)
            bm_cutoff = datetime.utcnow() - timedelta(hours=max(lookback_hours, 168.0))
            bm_rows = (
                db.query(
                    BlackMarketSnapshot.item_id,
                    BlackMarketSnapshot.enchantment,
                    BlackMarketSnapshot.quality,
                    BlackMarketSnapshot.buy_price_max,
                    BlackMarketSnapshot.data_age_seconds,
                    BlackMarketSnapshot.captured_at,
                )
                .filter(BlackMarketSnapshot.captured_at >= bm_cutoff)
                .order_by(BlackMarketSnapshot.captured_at.asc())
                .all()
            )

            for item_id, enchantment, qual, bp_max, age_sec, captured_at in bm_rows:
                if enchantment and enchantment > 0:
                    item_id = f"{item_id}@{enchantment}"

                quality = qual or 1
                city = "Black Market"

                if item_id not in prices:
                    prices[item_id] = {}
                if city not in prices[item_id]:
                    prices[item_id][city] = {}

                existing = prices[item_id][city].get(quality)
                if (
                    existing
                    and captured_at
                    and existing.get("_ts")
                    and captured_at <= existing["_ts"]
                ):
                    continue

                # Recompute BM data age dynamically
                bm_api_age = int(age_sec or 0)
                bm_db_age = (now - captured_at).total_seconds() if captured_at else 0
                bm_effective_age = bm_api_age + bm_db_age

                prices[item_id][city][quality] = {
                    "sell_price_min": 0,
                    "buy_price_max": bp_max or 0,
                    "volume_24h": 1,
                    "data_age_seconds": int(bm_effective_age),
                    "is_black_market": True,
                    "_ts": captured_at,
                }

        from app.core.market_utils import apply_enchantment_ceiling_crafting
        apply_enchantment_ceiling_crafting(prices)

        return prices

    def _load_item_metadata(self, db: Session) -> tuple[dict, dict, dict, dict]:
        """Returns (item_names, item_categories, item_values, item_weights)"""
        from app.core.market_utils import get_item_crafting_subcategory

        # Ensure your Item model has a 'weight' column (or gracefully fallback)
        try:
            rows = db.query(Item.item_id, Item.name, Item.category, Item.item_value, getattr(Item, "weight", None).label("weight")).all()
        except Exception:
            rows = db.query(Item.item_id, Item.name, Item.category, Item.item_value).all()
            
        names = {r.item_id: r.name for r in rows}
        categories = {}
        for r in rows:
            subcat = get_item_crafting_subcategory(r.item_id, r.category or "")
            categories[r.item_id] = subcat or r.category or ""
        values = {r.item_id: float(r.item_value or 0.0) for r in rows}
        
        def _estimate_fallback_weight(item_id: str, category: str = "") -> float:
            id_upper = item_id.upper()
            cat_lower = (category or "").lower()
            if any(r in id_upper for r in ["PLANKS", "CLOTH", "LEATHER", "BAR", "METALBAR", "STONEBLOCK", "WOOD", "ORE", "HIDE", "FIBER", "ROCK"]):
                return 0.8
            if any(w in id_upper for w in ["2H_", "BOW", "CROSSBOW", "STAFF", "HAMMER", "AXE", "SWORD", "MACE"]):
                return 3.5
            if any(a in id_upper for a in ["ARMOR", "ROBE", "JACKET", "HEAD", "HELMET", "SHOES", "BOOTS"]):
                return 2.0
            if "MOUNT" in id_upper or "mount" in cat_lower:
                return 15.0
            return 1.5

        weights = {
            r.item_id: (float(getattr(r, "weight", 0.0) or 0.0) or _estimate_fallback_weight(r.item_id, r.category or ""))
            for r in rows
        }
        return names, categories, values, weights

    def _load_recipes(self, db: Session) -> dict:
        """
        Build recipe map: {item_id: {"ingredients": [{"item_id": str, "quantity": float}]}}
        Filters out invalid craft recipes (Royal Sigil transmutes, Raw material gathering pseudo-recipes, raw artifacts, vanity).
        Guarantees that all enchanted equipment (including .1, .2, .3, and .4 Pristine items like Faction/Avalonian Capes)
        consume properly enchanted base items (e.g. T5_CAPE@4) and refined materials (e.g. T5_CLOTH_LEVEL4@4).
        """
        def _format_enchanted_ingredient(ing_id: str, e: int) -> str:
            """Format ingredient item ID to match Albion API database keys for enchanted resources and base equipment."""
            if not ing_id or e <= 0:
                return ing_id
            if "@" in ing_id:
                return ing_id

            ing_upper = ing_id.upper()
            # Non-enchanted crafting tokens, crests, artifacts, sigils, runes, souls, relics, faction hearts
            if any(x in ing_upper for x in ["ARTEFACT", "TOKEN", "QUESTITEM", "SIGIL", "_BP", "RUNE", "SOUL", "RELIC", "SHARD", "FACTION_HEART", "HEART"]):
                return ing_id

            # If already has _LEVEL in name (e.g. T6_PLANKS_LEVEL2), just append @{e}
            if "_LEVEL" in ing_upper:
                return f"{ing_id}@{e}"

            # Refined resources use _LEVEL{e}@{e}
            if any(m in ing_upper for m in ["METALBAR", "BAR", "LEATHER", "CLOTH", "PLANKS", "STONEBLOCK", "BLOCK"]):
                return f"{ing_id}_LEVEL{e}@{e}"

            # Base equipment items (e.g. T4_CAPE -> T4_CAPE@4, T5_BAG -> T5_BAG@2, etc.)
            return f"{ing_id}@{e}"

        # Standard clean refining recipe helper
        REFINING_RAW_MAP = {
            "METALBAR": "ORE",
            "BAR": "ORE",
            "PLANKS": "WOOD",
            "CLOTH": "FIBER",
            "LEATHER": "HIDE",
            "STONEBLOCK": "ROCK",
            "BLOCK": "ROCK",
        }
        REFINING_QTY_MAP = {2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 5, 8: 5}

        import re

        def _generate_clean_refining_recipe(item_id: str) -> dict | None:
            upper = item_id.upper()
            m = re.match(r"^T([2-8])_(PLANKS|CLOTH|LEATHER|METALBAR|STONEBLOCK)(?:_LEVEL\d+)?(?:@\d+)?$", upper)
            if not m:
                return None
            tier = int(m.group(1))
            mat_type = m.group(2)

            enchant = 0
            if "@" in upper:
                try:
                    enchant = int(upper.split("@")[1])
                except ValueError:
                    enchant = 0
            elif "_LEVEL" in upper:
                try:
                    enchant = int(upper.split("_LEVEL")[1][0])
                except (ValueError, IndexError):
                    enchant = 0

            raw_type = REFINING_RAW_MAP[mat_type]
            raw_qty = REFINING_QTY_MAP.get(tier, 2)

            if enchant > 0:
                raw_id = f"T{tier}_{raw_type}_LEVEL{enchant}@{enchant}"
            else:
                raw_id = f"T{tier}_{raw_type}"

            ings = [{"item_id": raw_id, "quantity": float(raw_qty)}]

            # In Albion Online, refining enchanted resources ALWAYS requires the FLAT version of the previous tier!
            if tier > 2:
                prev_tier = tier - 1
                prev_id = f"T{prev_tier}_{mat_type}"
                ings.append({"item_id": prev_id, "quantity": 1.0})

            return {"ingredients": ings}

        rows = db.query(Recipe.crafted_item_id, Recipe.ingredient_item_id, Recipe.quantity).all()
        raw_recipes: dict[str, list[dict]] = {}
        for r in rows:
            if hasattr(r, "crafted_item_id"):
                cid, ing_id, quantity = r.crafted_item_id, r.ingredient_item_id, r.quantity
            else:
                cid, ing_id, quantity = r[0], r[1], r[2]

            cid_upper = cid.upper()

            # 1. Royal Sigils cannot be crafted/transmuted from lower-tier sigils
            if "ROYALSIGIL" in cid_upper or "ROYAL_SIGIL" in cid_upper or "QUESTITEM_TOKEN_ROYAL" in cid_upper:
                continue

            # 2. Raw artifacts (e.g. T6_ARTEFACT_2H_DUALAXE_KEEPER) are ingredients for crafting, not equipment
            if cid_upper.startswith("T") and "_ARTEFACT_" in cid_upper:
                continue

            # 3. Vanity skins, emotes, furniture, non-tradable items, arena/community tokens
            if any(v in cid_upper for v in ["UNIQUE_", "SKIN_", "FURNITURE", "_NON_TRADABLE", "NONTRADABLE"]):
                continue

            # 4. Raw unrefined materials (Hide, Ore, Wood, Fiber, Rock) are gathered, NOT crafted from lower-tier raw materials
            if any(raw in cid_upper for raw in ["_HIDE", "_ORE", "_WOOD", "_FIBER", "_ROCK", "_STONE"]) and not any(ref in cid_upper for ref in ["LEATHER", "BAR", "METALBAR", "CLOTH", "PLANKS", "BLOCK", "STONEBLOCK"]):
                continue

            # 5. Skip non-tradable arena, community, and dungeon map tokens
            if any(t in str(ing_id).upper() for t in ["ARENA", "GVG", "COMMUNITY", "DUNGEON_TOKEN"]):
                continue

            if cid not in raw_recipes:
                raw_recipes[cid] = []
            raw_recipes[cid].append(
                {
                    "item_id": ing_id,
                    "quantity": float(quantity or 1),
                }
            )

        recipes: dict[str, dict] = {}

        # 1. Process all base/flat and existing enchanted recipes with strict ingredient matching
        for cid, ings in raw_recipes.items():
            # Check if this is a refining resource
            clean_ref_rec = _generate_clean_refining_recipe(cid)
            if clean_ref_rec:
                recipes[cid] = clean_ref_rec
                continue

            # Handle Royal gear deduplication (take first base item SET1 + single token requirement)
            if "_ROYAL" in cid.upper():
                seen_base = False
                seen_token = False
                clean_ings = []
                for ing in ings:
                    ing_id = ing["item_id"]
                    if any(k in ing_id.upper() for k in ["_ARMOR_", "_HEAD_", "_SHOES_", "_MAIN_", "_2H_", "_OFF_", "_CAPE", "_BAG"]):
                        if not seen_base:
                            clean_ings.append(ing)
                            seen_base = True
                    elif "QUESTITEM_TOKEN_ROYAL" in ing_id.upper() or "ROYAL" in ing_id.upper():
                        if not seen_token:
                            clean_ings.append(ing)
                            seen_token = True
                    else:
                        clean_ings.append(ing)
                ings = clean_ings

            enchant_level = 0
            if "@" in cid:
                try:
                    enchant_level = int(cid.split("@")[1])
                except ValueError:
                    enchant_level = 0

            formatted_ings = []
            for ing in ings:
                ing_id = ing["item_id"]
                formatted_id = _format_enchanted_ingredient(ing_id, enchant_level)
                formatted_ings.append({
                    "item_id": formatted_id,
                    "quantity": ing["quantity"],
                })
            recipes[cid] = {"ingredients": formatted_ings}

        # 2. Generate missing enchanted recipes for flat items across .1, .2, .3, and .4
        enchanted_generated = {}
        for cid, recipe in recipes.items():
            if "@" in cid:
                continue

            for e in [1, 2, 3, 4]:
                enchanted_cid = f"{cid}@{e}"
                # Only generate if not already explicitly defined
                if enchanted_cid not in recipes:
                    modified_ingredients = []
                    for ing in recipe["ingredients"]:
                        ing_id = ing["item_id"]
                        modified_ingredients.append({
                            "item_id": _format_enchanted_ingredient(ing_id, e),
                            "quantity": ing["quantity"],
                        })
                    enchanted_generated[enchanted_cid] = {"ingredients": modified_ingredients}

        recipes.update(enchanted_generated)

        # 3. Explicitly guarantee all standard refining tiers and enchantments (.0 to .4) exist in recipes
        for t in range(2, 9):
            for mat in ["PLANKS", "CLOTH", "LEATHER", "METALBAR", "STONEBLOCK"]:
                flat_id = f"T{t}_{mat}"
                r_flat = _generate_clean_refining_recipe(flat_id)
                if r_flat:
                    recipes[flat_id] = r_flat
                if t >= 4:
                    for e in range(1, 5):
                        level_id = f"T{t}_{mat}_LEVEL{e}@{e}"
                        r_level = _generate_clean_refining_recipe(level_id)
                        if r_level:
                            recipes[level_id] = r_level

        return recipes

    # ── Main entry point ────────────────────────────────────────────────────

    async def scan_all(
        self, db: Session = None, scan_bm: bool = False, lookback_hours: float = 48.0
    ) -> tuple[list[dict], ...]:
        """
        Returns a 13-tuple of opportunity lists:
          (bm_arb, craft, arb, refining, mm, enchanting, quality, transmutation,
           island, bm_craft, bm_refining, bm_enchanting, bm_mm)
        All as plain dicts, sorted by score descending, ready for DB storage and Discord alerts.
        """
        from app.core import state
        from app.core.config import settings

        # Dynamic premium status & tax rate sync
        is_prem = getattr(settings, "is_premium", True)
        self.engine.is_premium = is_prem
        self.engine.tax = 0.04 if is_prem else 0.08

        # Use dynamic thresholds from state
        self.engine.min_arb_profit = self.default_min_arb_profit
        self.engine.min_craft_profit = state.min_craft_profit
        self.engine.min_bm_profit = state.min_bm_profit
        self.engine.allow_enchant_transport = getattr(state, "allow_enchant_transport", True)

        from contextlib import contextmanager

        @contextmanager
        def _maybe_open_session():
            """Open a new DB session only when the caller didn't pass one in."""
            if db is None:
                with get_db_session() as s:
                    yield s
            else:
                yield db

        with _maybe_open_session() as session:
            # Freshness: Tier-based progressive ladder (app.core.freshness)
            # Old flat max_age_bm/royal/crafting/mm_seconds removed — per-item tier lookup at scan time

            log.info("[UNIFIED SCANNER] Loading prices...")
            prices = self._load_prices(session, lookback_hours=lookback_hours, scan_bm=scan_bm)
            log.info(f"[UNIFIED SCANNER] {len(prices)} items loaded.")

            names, categories, values, weights = self._load_item_metadata(session)
            recipes = self._load_recipes(session)

            bm_arb_raw = []
            bm_enchant_raw = []
            bm_craft_raw = []
            bm_refine_raw = []
            bm_mm_raw = []

            if scan_bm:
                log.info("[UNIFIED SCANNER] Scanning Black Market Arbitrage...")
                bm_arb_raw = self.engine.scan_b_arbitrage(prices, names, recipes, categories, values, weights)
                log.info(f"[UNIFIED SCANNER] BM Arbitrage: {len(bm_arb_raw)} opportunities")

                log.info("[UNIFIED SCANNER] Scanning Black Market Enchanting...")
                bm_enchant_raw = self.engine.scan_b_enchanting(prices, names, categories)
                log.info(f"[UNIFIED SCANNER] BM Enchanting: {len(bm_enchant_raw)} opportunities")

                log.info("[UNIFIED SCANNER] Scanning Caerleon Market Making...")
                bm_mm_raw = self.engine.scan_b_market_making(prices, names, categories, weights)
                log.info(f"[UNIFIED SCANNER] Caerleon MM: {len(bm_mm_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Royal Crafting...")
            craft_raw = self.engine.scan_crafting(prices, names, recipes, categories, values, weights)
            log.info(f"[UNIFIED SCANNER] Royal Crafting: {len(craft_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Island Agriculture...")
            island_raw = self.engine.scan_island(prices, names, recipes, categories, values, weights)
            log.info(f"[UNIFIED SCANNER] Island: {len(island_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Royal Arbitrage...")
            arb_raw = self.engine.scan_arbitrage(prices, names, weights)
            log.info(f"[UNIFIED SCANNER] Royal Arbitrage: {len(arb_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Royal Refining...")
            refine_raw = self.engine.scan_refining(prices, names, recipes, categories, values, weights)
            log.info(f"[UNIFIED SCANNER] Royal Refining: {len(refine_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Royal Enchanting...")
            enchant_raw = self.engine.scan_enchanting(prices, names, categories)
            log.info(f"[UNIFIED SCANNER] Royal Enchanting: {len(enchant_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Royal Market Making...")
            mm_raw = self.engine.scan_market_making(prices, names, categories, weights)
            log.info(f"[UNIFIED SCANNER] Royal MM: {len(mm_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Transmutation...")
            transmute_raw = self.engine.scan_transmutation(prices, names)
            log.info(f"[UNIFIED SCANNER] Transmutation: {len(transmute_raw)} opportunities")

            log.info("[UNIFIED SCANNER] Scanning Quality Inversions...")
            quality_raw = self.engine.scan_quality_inversions(prices, names)
            log.info(f"[UNIFIED SCANNER] Quality Inversions: {len(quality_raw)} opportunities")

            from app.alerts.discord import _is_island_opportunity

            raw_craft_dicts = [self._craft_to_dict(o, categories.get(o.item_id, "Unknown")) for o in craft_raw]
            raw_island_dicts = [self._craft_to_dict(o, categories.get(o.item_id, "Unknown")) for o in island_raw]

            # Split pure crafting from island farming
            pure_craft = [o for o in raw_craft_dicts if not _is_island_opportunity(o)]
            extra_island = [o for o in raw_craft_dicts if _is_island_opportunity(o)]
            combined_island = raw_island_dicts + extra_island

            # Tag and normalize island route indicators & sub-sectors
            for o in combined_island:
                o["type"] = "island"
                # Extract clean island host city
                raw_craft = o.get("craft_city") or o.get("crafting_city") or "Royal"
                clean_host = (
                    raw_craft.replace("Personal Island (", "")
                    .replace(")", "")
                    .replace(" Island", "")
                    .strip()
                )
                if clean_host == "Royal" or not clean_host or clean_host == "Island":
                    clean_host = o.get("sell_city") or "Bridgewatch"

                raw_sell = o.get("sell_city") or clean_host
                clean_sell = (
                    raw_sell.replace("Personal Island (", "")
                    .replace(")", "")
                    .replace(" Island", "")
                    .replace(" Market", "")
                    .strip()
                )
                if not clean_sell:
                    clean_sell = clean_host

                o["craft_city"] = f"Personal Island ({clean_host})"
                o["crafting_city"] = f"Personal Island ({clean_host})"
                o["source_city"] = f"Personal Island ({clean_host})"
                o["destination_city"] = f"{clean_sell} Market"
                o["buy_city"] = clean_host
                o["sell_city"] = clean_sell

                item_upper = str(o.get("item_id", "")).upper()
                cat_lower = str(o.get("category", "")).lower()
                if "_POTION_" in item_upper or "potion" in cat_lower or "alchemy" in cat_lower:
                    o["category_key"] = "potions"
                elif any(k in item_upper for k in ["_MEAL_", "_STEW", "_SOUP", "_PIE", "_OMELETTE", "_ROAST", "_SANDWICH", "_SALAD", "_BUTCHER", "_MEAT"]):
                    o["category_key"] = "cooking"
                elif any(k in item_upper for k in ["_MOUNT_", "_HORSE", "_OX", "_STAG", "_WOLF", "_FOAL", "_CALF", "_PIG", "_SHEEP", "_GOAT", "_CHICKEN", "_GOOSE", "_RAM", "_BEAR", "_OWL"]):
                    o["category_key"] = "mounts"
                else:
                    o["category_key"] = "farming"

            return (
                [self._bm_to_dict(o, categories.get(o.item_id, "Unknown")) for o in bm_arb_raw],
                pure_craft,
                [self._arb_to_dict(o, categories.get(o.item_id, "Unknown")) for o in arb_raw],
                [self._refine_to_dict(o, categories.get(o.item_id, "Unknown")) for o in refine_raw],
                [self._mm_to_dict(o, categories.get(o.item_id, "Unknown")) for o in mm_raw],
                [self._enchant_to_dict(o, categories.get(o.target_item_id, "Unknown")) for o in enchant_raw],
                [self._quality_to_dict(o, categories.get(o.item_id, "Unknown")) for o in quality_raw],
                [self._transmute_to_dict(o, categories.get(o.item_id, "Unknown")) for o in transmute_raw],
                combined_island,
                [self._craft_to_dict(o, categories.get(o.item_id, "Unknown")) for o in bm_craft_raw],
                [self._refine_to_dict(o, categories.get(o.item_id, "Unknown")) for o in bm_refine_raw],
                [self._enchant_to_dict(o, categories.get(o.target_item_id, "Unknown")) for o in bm_enchant_raw],
                [self._mm_to_dict(o, categories.get(o.item_id, "Unknown")) for o in bm_mm_raw],
            )



    def _transmute_to_dict(self, o, category: str) -> dict[str, Any]:
        return {
            "item_id": o.item_id,
            "item_name": o.item_name,
            "source_item_id": o.source_item_id,
            "source_item_name": o.source_item_name,
            "source_price": o.source_price,
            "transmutation_fee": o.transmutation_fee,
            "total_cost": o.total_cost,
            "sell_price": o.sell_price,
            "source_city": o.source_city,
            "destination_city": o.sell_city,
            "estimated_profit": o.net_profit,
            "net_profit": o.net_profit,
            "profit": o.net_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "roi": o.roi,
            "daily_volume": o.daily_volume,
            "data_age_source": o.data_age_source,
            "data_age_sell": o.data_age_sell,
            "safe_limit": o.safe_limit,
            "score": o.score,
            "ev_score": o.score,
            "category": category,
            "category_key": "transmutation",
            "type": "transmutation",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

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
            "net_profit": o.net_profit,
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
            "score": o.score,
            "ev_score": o.score,
            "category": category,
            "category_key": "quality_inversion",
            "type": "quality_misprice",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _enchant_to_dict(self, o, category: str) -> dict[str, Any]:
        base_c = getattr(o, "base_city", "Caerleon")
        sell_c = getattr(o, "sell_city", "Black Market" if base_c == "Caerleon" else base_c)
        return {
            "item_id": o.target_item_id,
            "target_item_id": o.target_item_id,
            "item_name": self._enhance_name(o.target_item_id, o.target_item_name, getattr(o, "quality", 1)),
            "base_item_id": o.base_item_id,
            "base_price": o.base_price,
            "base_city": base_c,
            "base_quality": getattr(o, "base_quality", o.quality),
            "material_id": o.material_id,
            "material_qty": o.material_qty,
            "material_price": o.material_price,
            "bm_buy_price": o.bm_buy_price,
            "sell_price": o.bm_buy_price,
            "estimated_profit": o.net_profit,
            "net_profit": o.net_profit,
            "estimated_margin": getattr(o, "profit_margin", round((o.net_profit / o.bm_buy_price) * 100, 2) if o.bm_buy_price > 0 else 0.0),
            "profit": o.net_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": getattr(o, "profit_margin", round((o.net_profit / o.bm_buy_price) * 100, 2) if o.bm_buy_price > 0 else 0.0),
            "source_city": base_c,
            "destination_city": sell_c,
            "sell_city": sell_c,
            "total_cost": o.total_cost,
            "safe_limit": o.safe_limit,
            "roi": o.roi,
            "quality": o.quality,
            "score": getattr(o, "score", 0.0),
            "ev_score": getattr(o, "score", 0.0),
            "data_age_base": getattr(o, "data_age_base", 0),
            "data_age_material": getattr(o, "data_age_material", 0),
            "data_age_bm": getattr(o, "data_age_bm", 0),
            "data_age_sell": getattr(o, "data_age_bm", 0),
            "is_dangerous": getattr(o, "is_dangerous", False),
            "category": category,
            "category_key": "bm_enchanting" if base_c == "Caerleon" else "enchanting",
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
            "net_profit": o.effective_profit,
            "estimated_margin": o.profit_pct,
            "profit": o.effective_profit,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "roi": o.roi,
            "safe_limit": o.safe_limit,
            "profit_per_kg": o.profit_per_kg,
            "total_cost": int(o.effective_cost),
            "effective_cost": int(o.effective_cost),
            "mode": o.mode,  # "BUY+RUN" or "CRAFT+RUN"
            "craft_cost": o.craft_cost,
            "craft_city": o.craft_city,
            "can_be_crafted": o.can_be_crafted,
            "daily_volume": o.daily_volume,
            "coverage_suspect": (o.daily_volume == 0),
            "data_age_buy": o.data_age_buy,
            "data_age_bm": o.data_age_bm,
            "quality": o.quality,
            "order_quality": o.quality,
            "buy_quality": getattr(o, "buy_quality", o.quality),
            "score": o.score,
            "score": o.score,
            "ev_score": o.score,
            "risk_score": 0.5,  # BM always requires Caerleon run
            "type": "black_market",
            "category": category,
            "category_key": "bm_arbitrage",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _craft_to_dict(self, o: CraftingOpportunity, category: str) -> dict[str, Any]:
        cost = o.material_cost_net + o.station_fee
        roi_val = getattr(o, "roi", 0.0)
        if roi_val == 0.0 and cost > 0 and o.profit > 0:
            roi_val = round((o.profit / cost) * 100.0, 2)

        is_bm_craft = (o.sell_city == "Black Market" or o.craft_city == "Caerleon" or getattr(o, "sell_mode", "") == "BM")
        return {
            "item_id": o.item_id,
            "item_name": self._enhance_name(o.item_id, o.item_name, getattr(o, "quality", 1)),
            "craft_city": o.craft_city,
            "crafting_city": o.craft_city,
            "source_city": o.craft_city,
            "sell_city": o.sell_city,
            "destination_city": o.sell_city,
            "sell_mode": o.sell_mode,  # "BM" or "MARKET"
            "craft_cost": cost,
            "total_cost": cost,
            "material_cost_gross": o.material_cost_gross,
            "material_cost_net": o.material_cost_net,
            "station_fee": o.station_fee,
            "rrr_used": o.rrr_used,
            "sell_price": o.sell_price,
            "revenue_net": o.revenue_net,
            "profit": o.profit,
            "net_profit": o.profit,
            "estimated_profit": o.profit,
            "profit_margin": o.profit_pct,
            "estimated_margin": o.profit_pct,
            "profit_pct": o.profit_pct,
            "roi": roi_val,
            "daily_volume": o.daily_volume,
            "data_age_materials": o.data_age_materials,
            "data_age_sell": o.data_age_sell,
            "use_focus": o.use_focus,
            "quality": o.quality,
            "score": o.score,
            "ev_score": o.score,
            "ingredients": o.ingredients,
            "is_dangerous": getattr(o, "is_dangerous", False),
            "type": "crafting",
            "category": category,
            "category_key": "bm_crafting" if is_bm_craft else "crafting",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _refine_to_dict(self, o: RefiningOpportunity, category: str) -> dict[str, Any]:
        is_bm_refine = getattr(o, "refine_city", "") == "Caerleon" or getattr(o, "sell_city", "") == "Black Market"
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
            "total_cost": o.material_cost_net + o.station_fee,
            "sell_price": o.sell_price,
            "revenue_net": o.revenue_net,
            "profit": o.profit,
            "net_profit": o.profit,
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
            "score": o.score,
            "ev_score": o.score,
            "ingredients": getattr(o, "ingredients", []),
            "category": category,
            "category_key": "bm_refining" if is_bm_refine else "refining",
            "type": "refining",
            "is_premium": getattr(self.engine, "is_premium", True),
            "tax_rate": getattr(self.engine, "tax", 0.04),
            "detected_at": datetime.utcnow().isoformat(),
        }

    def _mm_to_dict(self, o: MarketMakingOpportunity, category: str) -> dict[str, Any]:
        is_bm_mm = o.source_city == "Caerleon" or getattr(o, "is_dangerous_route", False)
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
            "score": getattr(o, "score", 0.0),
            "ev_score": getattr(o, "score", 0.0),
            "category": category,
            "category_key": "bm_market_making" if is_bm_mm else "market_making",
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
            "net_profit": o.net_profit,
            "profit": o.net_profit,
            "estimated_margin": o.profit_pct,
            "profit_pct": o.profit_pct,
            "profit_margin": o.profit_pct,
            "roi": getattr(o, "roi", o.profit_pct),
            "safe_limit": getattr(o, "safe_limit", 1),
            "profit_per_kg": getattr(o, "profit_per_kg", 0.0),
            "tax_paid": o.tax_paid,
            "is_dangerous": o.is_dangerous_route,
            "daily_volume": o.daily_volume,
            "data_age_buy": o.data_age_buy,
            "data_age_sell": o.data_age_sell,
            "quality": o.quality,
            "score": o.score,
            "ev_score": o.score,
            "risk_score": 0.7 if o.is_dangerous_route else 0.2,
            "type": "arbitrage",
            "category": category,
            "category_key": "arbitrage",
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
        transmute_opps: list[dict] | None = None,
    ):
        """Save opportunities to the database, marking old ones as inactive."""
        from app.db.models import (
            ArbitrageOpportunity,
            CraftingOpportunity,
            RefiningOpportunity,
            MarketMakingOpportunity,
        )
        import json

        # --- Deactivate stale opportunities ---
        db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).update({"is_active": False})
        db.query(CraftingOpportunity).filter(CraftingOpportunity.is_active == True).update({"is_active": False})
        db.query(RefiningOpportunity).filter(RefiningOpportunity.is_active == True).update({"is_active": False})
        db.query(MarketMakingOpportunity).filter(MarketMakingOpportunity.is_active == True).update({"is_active": False})
        db.commit()

        # --- Save Arbitrage opportunities (Royal + BM combined) ---
        for o in arb_opps + bm_opps:
            db.add(ArbitrageOpportunity(
                item_id=o["item_id"],
                item_name=o["item_name"],
                source_city=o["source_city"],
                destination_city=o["destination_city"],
                buy_price=o["buy_price"],
                sell_price=o["sell_price"],
                estimated_profit=float(o["estimated_profit"]),
                estimated_margin=float(o["estimated_margin"]),
                risk_score=float(o.get("risk_score", 0.2)),
                daily_volume=int(o.get("daily_volume", 0)),
                volume_source=o.get("volume_source", "ESTIMATED"),
                safe_limit=o.get("safe_limit", 1),
                current_supply=o.get("current_supply", 0),
                market_gap=o.get("market_gap", 0),
                expected_hourly_profit=o.get("expected_hourly_profit", 0.0),
                ev_score=float(o.get("ev_score", 0.0)),
                volatility=o.get("volatility", 0.0),
                z_score=o.get("z_score", 0.0),
                persistence=o.get("persistence", 1),
                is_active=True,
            ))

        # --- Save Crafting opportunities (Royal + Island + BM combined) ---
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
                daily_volume=int(o.get("daily_volume", 0)),
                volume_source=o.get("volume_source", "ESTIMATED"),
                safe_limit=o.get("safe_limit", 1),
                current_supply=o.get("current_supply", 0),
                market_gap=o.get("market_gap", 0),
                ev_score=float(o.get("ev_score", 0.0)),
                volatility=o.get("volatility", 0.0),
                persistence=o.get("persistence", 1),
                ingredients_json=json.dumps(o.get("ingredients", [])),
                decision_log=o.get("decision_log", ""),
                is_active=True,
            ))

        # --- Save Refining opportunities ---
        for o in (refining_opps or []):
            db.add(RefiningOpportunity(
                item_id=o["item_id"],
                item_name=o.get("item_name", ""),
                refining_city=o.get("refine_city") or o.get("crafting_city", ""),
                sell_city=o.get("sell_city", ""),
                craft_cost=float(o.get("craft_cost", 0.0)),
                sell_price=float(o.get("sell_price", 0.0)),
                profit=float(o.get("profit", 0.0)),
                profit_margin=float(o.get("profit_margin", 0.0)),
                focus_cost=o.get("focus_cost", 0.0),
                profit_per_focus=o.get("profit_per_focus", 0.0),
                silver_per_nutrition=o.get("silver_per_nutrition", 0.0),
                journal_profit=o.get("journal_profit", 0.0),
                daily_volume=int(o.get("daily_volume", 0)),
                volume_source=o.get("volume_source", "ESTIMATED"),
                safe_limit=o.get("safe_limit", 1),
                ev_score=float(o.get("ev_score", 0.0)),
                volatility=o.get("volatility", 0.0),
                roi=o.get("roi", 0.0),
                profit_per_kg=o.get("profit_per_kg", 0.0),
                ingredients_json=json.dumps(o.get("ingredients", [])),
                is_active=True,
            ))

        # --- Save Market Making opportunities ---
        for o in (mm_opps or []):
            db.add(MarketMakingOpportunity(
                item_id=o["item_id"],
                item_name=o.get("item_name", ""),
                source_city=o.get("source_city", ""),
                destination_city=o.get("destination_city", ""),
                buy_price=int(o.get("buy_price", 0)),
                sell_price=int(o.get("sell_price", 0)),
                estimated_profit=float(o.get("estimated_profit", 0.0)),
                estimated_margin=float(o.get("estimated_margin", 0.0)),
                setup_fees=o.get("setup_fees", 0.0),
                tax_paid=o.get("tax_paid", 0.0),
                daily_volume=int(o.get("daily_volume", 0)),
                ev_score=float(o.get("ev_score", 0.0)),
                roi=o.get("roi", 0.0),
                profit_per_kg=o.get("profit_per_kg", 0.0),
                is_active=True,
            ))

        db.commit()
