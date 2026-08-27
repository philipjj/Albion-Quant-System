"""
APScheduler-based task scheduler for development.
Handles periodic market collection, arbitrage/crafting computation, and alerts.
"""

import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.alerts.discord import DiscordAlerter
from app.core.config import settings
from app.core.logging import log
from app.core.scanner_integration import UnifiedScanner
from app.db.session import get_db_session
from app.ingestion.collector import MarketCollector


class QuantScheduler:
    """Manages all scheduled jobs for the trading system."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.collector = MarketCollector()
        self.unified_scanner = UnifiedScanner()
        self.alerter = DiscordAlerter()
        self._is_running = False
        self._current_partition = 0  # Rotates through scan_partitions
        self._alert_history = {}  # Tracks last alert time for (type, item, source, dest)
        self._cycle_running = False

    def _prune_alert_history(self):
        """Evict entries older than 2× the alert cooldown to prevent unbounded memory growth."""
        max_age_seconds = settings.alert_cooldown_minutes * 60 * 2
        now = datetime.utcnow()
        stale_keys = [
            k for k, ts in self._alert_history.items()
            if (now - ts).total_seconds() > max_age_seconds
        ]
        for k in stale_keys:
            del self._alert_history[k]
        if stale_keys:
            log.debug(f"[SCHEDULER] Pruned {len(stale_keys)} stale alert history entries.")



    async def master_cycle(self):
        """
        Partitioned Master Cycle — Ingest → Scan → Alert in ~10 minutes.

        Instead of collecting ALL items (700+ batches, 25+ min) then scanning,
        we split the item universe into N partitions and rotate through them.
        Each cycle:
          1. Ingest 1/N of items (fast — ~3-8 min depending on partition size)
          2. Scan the FULL DB (all recent data, including prior partitions)
          3. Send alerts immediately

        After N cycles the entire universe has been refreshed. The scanner always
        sees fresh data from the most recent partition PLUS still-valid data from
        older partitions (within the lookback window).
        """
        if self._cycle_running:
            log.warning("[SCHEDULER] Master cycle already running. Skipping this run.")
            return

        self._cycle_running = True
        self._prune_alert_history()

        num_partitions = max(1, settings.scan_partitions)
        partition_idx = self._current_partition % num_partitions

        log.info(f"═══ PARTITION CYCLE {partition_idx + 1}/{num_partitions} ═══")
        start_time = datetime.utcnow()

        try:
            # 1. Ingest only this partition's items
            log.info(
                f"[SCHEDULER] Step 1: Ingesting Partition {partition_idx + 1}/{num_partitions}..."
            )
            batches_done = await self.collector.collect_partition(partition_idx, num_partitions)
            if batches_done == 0 and not self.collector._stop_requested:
                log.warning(
                    f"[SCHEDULER] Partition {partition_idx + 1} yielded 0 batches. Advancing to next."
                )
                self._current_partition += 1
                return

            if self.collector._stop_requested:
                log.info("[SCHEDULER] Cycle aborted: stop requested during ingestion.")
                return

            # 2. Scan the FULL DB — scanner sees all data within lookback window,
            #    not just this partition's items.
            log.info("[SCHEDULER] Step 2: Running Unified Scanner (full DB)...")
            scan_res = await self.unified_scanner.scan_all(scan_bm=True, lookback_hours=12.0)
            if len(scan_res) >= 13:
                bm_arb, craft, arb, refine, mm, enchant, quality, transmute, island, bm_craft, bm_refine, bm_enchant, bm_mm = scan_res[:13]
            elif len(scan_res) >= 9:
                bm_arb, craft, arb, refine, mm, enchant, quality, transmute, island = scan_res[:9]
                bm_craft, bm_refine, bm_enchant, bm_mm = [], [], [], []
            else:
                bm_arb, craft, arb, refine, mm, enchant, quality, transmute = scan_res[:8]
                island, bm_craft, bm_refine, bm_enchant, bm_mm = [], [], [], [], []

            # Update live memory cache for instant Web UI browsing
            try:
                from app.api.system import set_latest_opportunities_cache

                potions = [o for o in island if o.get("category_key") == "potions"]
                cooking = [o for o in island if o.get("category_key") == "cooking"]
                mounts = [o for o in island if o.get("category_key") == "mounts"]
                farming = [o for o in island if o.get("category_key") == "farming" or (o not in potions and o not in cooking and o not in mounts)]

                set_latest_opportunities_cache({
                    "bm_arbitrage": bm_arb,
                    "bm_crafting": bm_craft,
                    "bm_enchanting": bm_enchant,
                    "bm_refining": bm_refine,
                    "bm_market_making": bm_mm,
                    "arbitrage": arb,
                    "crafting": craft,
                    "refining": refine,
                    "market_making": mm,
                    "enchanting": enchant,
                    "transmutation": transmute,
                    "quality_inversion": quality,
                    "potions": potions,
                    "cooking": cooking,
                    "farming": farming,
                    "mounts": mounts,
                    "island": island,
                })
            except Exception as e:
                log.warning(f"[SCHEDULER] Memory cache update warning: {e}")

            # Save opportunities to database so API endpoints & status are always fresh
            try:
                with get_db_session() as db:
                    self.unified_scanner.save_opportunities(
                        db,
                        bm_arb,
                        craft,
                        arb,
                        refining_opps=refine,
                        mm_opps=mm,
                        enchant_opps=enchant,
                        quality_opps=quality,
                        transmute_opps=transmute,
                    )
            except Exception as e:
                log.error(f"[SCHEDULER] Failed to persist opportunities to database: {e}")

            # 3. Alert
            log.info(
                f"[SCHEDULER] Step 3: Sending alerts across 12 channels ("
                f"Transmute: {len(transmute)}, Island: {len(island)}, "
                f"B-MM: {len(bm_mm)}, B-Refine: {len(bm_refine)}, B-Enchant: {len(bm_enchant)}, B-Craft: {len(bm_craft)}, B-Arb: {len(bm_arb)}, "
                f"MM: {len(mm)}, Refine: {len(refine)}, Enchant: {len(enchant)}, Craft: {len(craft)}, Arb: {len(arb)})"
            )

            def _is_valid_budget(o: dict) -> bool:
                cost = o.get("buy_price", 0) or o.get("craft_cost", 0) or o.get("total_cost", 0) or o.get("material_cost_gross", 0)
                revenue = o.get("sell_price", 0) or o.get("revenue_net", 0)
                if revenue == 0 and cost > 0:
                    revenue = cost + o.get("estimated_profit", o.get("profit", 0))
                
                if settings.max_investment_silver > 0 and cost > settings.max_investment_silver:
                    return False
                if settings.min_revenue_silver > 0 and revenue < settings.min_revenue_silver:
                    return False
                return True

            from collections import defaultdict
            from app.core import state
            from app.alerts.discord import _is_island_opportunity

            cooldown_seconds = settings.alert_cooldown_minutes * 60
            now_time = datetime.utcnow()
            tier_prefix = f"T{state.tier_lock}_" if state.tier_lock is not None else None
            limit = getattr(settings, "alert_limit_per_cycle", 10)

            def _filter_and_group(opps: list[dict], key_fn, enable_flag: bool = True, sort_key="ev_score") -> list[dict]:
                if not enable_flag:
                    return []
                fresh = []
                for o in opps:
                    item_id = o.get("item_id") or o.get("target_item_id") or ""
                    if tier_prefix and not item_id.upper().startswith(tier_prefix):
                        continue
                    if not _is_valid_budget(o):
                        continue

                    # Filter unrealistic Royal crafting / lone-ask margin bait in safe cities
                    roi = float(o.get("roi", o.get("profit_pct", 0)))
                    cost = float(o.get("buy_price", 0) or o.get("craft_cost", 0) or o.get("total_cost", 0) or o.get("material_cost_gross", 0))
                    vol = float(o.get("daily_volume", 0))
                    src = str(o.get("craft_city", o.get("buy_city", o.get("source_city", o.get("base_city", "")))))
                    dst = str(o.get("sell_city", o.get("destination_city", "")))
                    from app.core.constants import ROYAL_SAFE_CITIES

                    # Dead inventory protection: High cost items (>500k silver) require confirmed daily volume (except Black Market)
                    is_bm = (
                        dst.lower() == "black market"
                        or "black market" in dst.lower()
                        or o.get("is_black_market", False)
                        or str(o.get("category_key", "")).startswith("bm_")
                        or str(o.get("category", "")).lower().startswith("bm_")
                        or str(o.get("type", "")).startswith("bm_")
                    )

                    if not is_bm:
                        # Category-specific Royal margin ceilings
                        is_enchant = o.get("material_id") or "enchant" in str(o.get("category_key", "")).lower() or "enchant" in str(o.get("category", "")).lower()
                        is_craft = o.get("ingredients") or "craft" in str(o.get("category_key", "")).lower() or "craft" in str(o.get("category", "")).lower()

                        if is_enchant and roi > 22.0:
                            continue
                        elif is_craft and roi > 40.0:
                            continue
                        elif roi > 45.0:
                            continue

                        if cost > 500_000 and vol < 1:
                            continue



                    key = key_fn(o, item_id)
                    if key in self._alert_history:
                        last_time = self._alert_history[key]
                        if (now_time - last_time).total_seconds() < cooldown_seconds:
                            continue
                    fresh.append((key, o))


                grouped = defaultdict(list)
                for key, o in fresh:
                    grouped[o.get("category", "Unknown")].append((key, o))

                final = []
                for cat, items in grouped.items():
                    items.sort(key=lambda x: x[1].get(sort_key, x[1].get("estimated_profit", 0)), reverse=True)
                    for key, o in items[:10]:
                        final.append(o)
                        self._alert_history[key] = now_time
                final.sort(key=lambda x: (x.get("category", "Unknown"), -x.get(sort_key, x.get("estimated_profit", 0))))
                return final

            # 1. Transmutation (Royal safe cities)
            final_transmute = _filter_and_group(
                transmute,
                lambda o, iid: f"transmute:{iid}:{o.get('source_city', '')}:{o.get('source_item_id', '')}",
                getattr(settings, "enable_alerts_transmute", True)
            )

            # 2. Island (Royal safe cities)
            all_island = island + [o for o in craft if _is_island_opportunity(o)]
            final_island = _filter_and_group(
                all_island,
                lambda o, iid: f"island:{iid}:{o.get('sell_city', o.get('destination_city', 'Any'))}",
                getattr(settings, "enable_alerts_island", True)
            )

            # 3. B-Market Making (Caerleon)
            final_bm_mm = _filter_and_group(
                bm_mm,
                lambda o, iid: f"bm_mm:{iid}:{o.get('source_city', 'Caerleon')}",
                getattr(settings, "enable_alerts_bm_mm", True)
            )

            # 4. B-Refining (Caerleon)
            final_bm_refine = _filter_and_group(
                bm_refine,
                lambda o, iid: f"bm_refine:{iid}:{o.get('crafting_city', 'Caerleon')}",
                getattr(settings, "enable_alerts_bm_refining", True)
            )

            # 5. B-Enchanting (Caerleon -> BM)
            final_bm_enchant = _filter_and_group(
                bm_enchant,
                lambda o, iid: f"bm_enchant:{iid}:{o.get('target_item_id', '')}",
                getattr(settings, "enable_alerts_bm_enchanting", True),
                sort_key="estimated_profit"
            )

            # 6. B-Crafting (Caerleon -> BM)
            final_bm_craft = _filter_and_group(
                [o for o in bm_craft if not _is_island_opportunity(o)],
                lambda o, iid: f"bm_craft:{iid}:{o.get('crafting_city', 'Caerleon')}:{o.get('sell_city', 'Black Market')}",
                getattr(settings, "enable_alerts_bm_crafting", True)
            )

            # 7. B-Arbitrage (Royal -> BM)
            final_bm_arb = _filter_and_group(
                bm_arb,
                lambda o, iid: f"bm_arb:{iid}:{o.get('source_city', '')}:{o.get('destination_city', 'Black Market')}",
                getattr(settings, "enable_alerts_bm_arb", True)
            )

            # 8. Market Making (Royal safe cities)
            final_mm = _filter_and_group(
                mm,
                lambda o, iid: f"mm:{iid}:{o.get('source_city', '')}",
                getattr(settings, "enable_alerts_mm", True)
            )

            # 9. Refining (Royal safe cities)
            final_refine = _filter_and_group(
                refine,
                lambda o, iid: f"refine:{iid}:{o.get('crafting_city', '')}:{o.get('sell_city', '')}",
                getattr(settings, "enable_alerts_refining", True)
            )

            # 10. Enchanting (Royal safe cities only)
            safe_enchant = [
                o for o in enchant
                if o.get("destination_city") not in ["Black Market", "Caerleon"]
                and o.get("source_city") not in ["Black Market", "Caerleon"]
                and o.get("base_city") not in ["Black Market", "Caerleon"]
            ]
            final_enchant = _filter_and_group(
                safe_enchant,
                lambda o, iid: f"enchant:{iid}:{o.get('source_city', '')}:{o.get('destination_city', '')}",
                getattr(settings, "enable_alerts_enchanting", True),
                sort_key="estimated_profit"
            )

            # 11. Crafting (Royal safe cities)
            final_craft = _filter_and_group(
                [o for o in craft if not _is_island_opportunity(o)],
                lambda o, iid: f"craft:{iid}:{o.get('crafting_city', '')}:{o.get('sell_city', '')}",
                getattr(settings, "enable_alerts_crafting", True)
            )

            # 12. Arbitrage (Royal safe cities)
            final_arb = _filter_and_group(
                arb,
                lambda o, iid: f"arb:{iid}:{o.get('source_city', '')}:{o.get('destination_city', '')}",
                getattr(settings, "enable_alerts_arb", True)
            )

            # Quality Misprice
            final_quality = _filter_and_group(
                quality,
                lambda o, iid: f"quality:{iid}:{o.get('source_city', o.get('city', ''))}:{o.get('buy_quality', 1)}",
                True,
                sort_key="estimated_profit"
            )

            # Sync fresh filtered opportunities to WebApp memory cache cumulatively across P1 -> P6
            try:
                import app.api.system as system_api

                is_first_partition = (partition_idx == 0)

                def _merge_cumulative_opps(existing_list: list[dict], new_list: list[dict], reset_sweep: bool = False) -> list[dict]:
                    def _opp_key(o: dict) -> str:
                        item_id = str(o.get("item_id") or o.get("target_item_id") or "")
                        src = str(o.get("craft_city") or o.get("buy_city") or o.get("source_city") or "")
                        dst = str(o.get("sell_city") or o.get("destination_city") or "")
                        q = str(o.get("quality") or o.get("buy_quality") or 1)
                        return f"{item_id}:{src}:{dst}:{q}"

                    merged = {}
                    if not reset_sweep:
                        for o in existing_list:
                            merged[_opp_key(o)] = o

                    for o in new_list:
                        o["scanned_partition"] = partition_idx + 1
                        o["scanned_at"] = datetime.utcnow().isoformat()
                        merged[_opp_key(o)] = o

                    res = list(merged.values())
                    res.sort(key=lambda x: x.get("score", x.get("ev_score", x.get("net_profit", x.get("profit", 0)))), reverse=True)
                    return res

                new_partition_cache = {
                    "bm_arbitrage": final_bm_arb,
                    "bm_crafting": final_bm_craft,
                    "bm_enchanting": final_bm_enchant,
                    "bm_refining": final_bm_refine,
                    "bm_market_making": final_bm_mm,
                    "arbitrage": final_arb,
                    "crafting": final_craft,
                    "refining": final_refine,
                    "market_making": final_mm,
                    "enchanting": final_enchant,
                    "transmutation": final_transmute,
                    "quality_inversion": final_quality,
                    "island": final_island,
                }

                for cat_key, incoming_items in new_partition_cache.items():
                    existing_items = system_api._LATEST_OPPORTUNITIES_CACHE.get(cat_key, [])
                    system_api._LATEST_OPPORTUNITIES_CACHE[cat_key] = _merge_cumulative_opps(
                        existing_items, incoming_items, reset_sweep=is_first_partition
                    )

                system_api._LATEST_SCAN_TIME = datetime.utcnow().isoformat()
            except Exception as se:
                log.warning(f"[SCHEDULER] Failed to sync cache to web API: {se}")

            # Dispatch alerts across all 12 channels
            await self.alerter.send_batch_alerts(
                arb_opps=final_arb,
                arb_limit=limit,
                craft_opps=final_craft,
                craft_limit=limit,
                refine_opps=final_refine,
                refine_limit=limit,
                enchant_opps=final_enchant,
                enchant_limit=limit,
                mm_opps=final_mm,
                mm_limit=limit,
                transmute_opps=final_transmute,
                transmute_limit=limit,
                island_opps=final_island,
                island_limit=limit,
                bm_arb_opps=final_bm_arb,
                bm_arb_limit=limit,
                bm_craft_opps=final_bm_craft,
                bm_craft_limit=limit,
                bm_refine_opps=final_bm_refine,
                bm_refine_limit=limit,
                bm_enchant_opps=final_bm_enchant,
                bm_enchant_limit=limit,
                bm_mm_opps=final_bm_mm,
                bm_mm_limit=limit,
                quality_opps=final_quality,
                quality_limit=limit,
            )

            duration = (datetime.utcnow() - start_time).total_seconds()
            self._current_partition += 1
            next_part = (self._current_partition % num_partitions) + 1
            log.info(
                f"═══ PARTITION {partition_idx + 1}/{num_partitions} COMPLETE ({duration:.1f}s) — Next: P{next_part} ═══"
            )

        except Exception as e:
            log.error(f"❌ PARTITION CYCLE FAILED: {e}", exc_info=True)
            self._current_partition += 1  # Don't get stuck on a failing partition
        finally:
            self._cycle_running = False

    async def job_cleanup(self):
        """Delete old records and vacuum database."""
        from datetime import timedelta
        import os
        import shutil

        from app.db.models import (
            ArbitrageOpportunity,
            BlackMarketSnapshot,
            CraftingOpportunity,
            MarketHistory,
            MarketPrice,
            MarketSnapshot,
        )
        from app.db.session import get_db_session, engine

        log.info("[SCHEDULER] Periodic Task: Database & File Cleanup")
        try:
            # 1. Clean up SQLAlchemy Database records
            cutoff = datetime.utcnow() - timedelta(days=settings.market_data_retention_days)
            with get_db_session() as db:
                d1 = db.query(MarketPrice).filter(MarketPrice.captured_at < cutoff).delete()
                d2 = db.query(MarketSnapshot).filter(MarketSnapshot.captured_at < cutoff).delete()
                d3 = db.query(BlackMarketSnapshot).filter(BlackMarketSnapshot.captured_at < cutoff).delete()
                d4 = db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.detected_at < cutoff).delete()
                d5 = db.query(CraftingOpportunity).filter(CraftingOpportunity.detected_at < cutoff).delete()
                d6 = db.query(MarketHistory).filter(MarketHistory.timestamp < cutoff).delete()
            log.info(f"[SCHEDULER] Cleanup removed old records: MP:{d1} MS:{d2} BMS:{d3} Arb:{d4} Craft:{d5} Hist:{d6}")

            # 2. Reclaim SQLite file space via VACUUM
            if settings.database_url.startswith("sqlite"):
                from sqlalchemy import text
                try:
                    with engine.connect() as conn:
                        conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
                    log.info("[SCHEDULER] SQLite database VACUUM complete.")
                except Exception as ve:
                    log.warning(f"[SCHEDULER] SQLite database VACUUM failed (skipping): {ve}")

            # 3. Clean up stale historical Parquet files
            hist_path = "data/historical"
            if os.path.exists(hist_path):
                hist_cutoff = datetime.utcnow() - timedelta(days=settings.historical_data_retention_days)
                deleted_folders = 0
                for yr_dir in os.listdir(hist_path):
                    yr_path = os.path.join(hist_path, yr_dir)
                    if not os.path.isdir(yr_path) or not yr_dir.startswith("year="):
                        continue
                    try:
                        year = int(yr_dir.split("=")[1])
                    except ValueError:
                        continue
                    for mo_dir in os.listdir(yr_path):
                        mo_path = os.path.join(yr_path, mo_dir)
                        if not os.path.isdir(mo_path) or not mo_dir.startswith("month="):
                            continue
                        try:
                            month = int(mo_dir.split("=")[1])
                        except ValueError:
                            continue
                        for dy_dir in os.listdir(mo_path):
                            dy_path = os.path.join(mo_path, dy_dir)
                            if not os.path.isdir(dy_path) or not dy_dir.startswith("day="):
                                continue
                            try:
                                day = int(dy_dir.split("=")[1])
                                folder_date = datetime(year, month, day)
                            except ValueError:
                                continue
                            if folder_date < hist_cutoff:
                                log.info(f"[SCHEDULER] Deleting stale parquet partition: {dy_path}")
                                try:
                                    shutil.rmtree(dy_path)
                                    deleted_folders += 1
                                except Exception as e:
                                    log.error(f"[SCHEDULER] Failed to delete {dy_path}: {e}")
                        # Clean empty month directories
                        try:
                            if os.path.exists(mo_path) and not os.listdir(mo_path):
                                os.rmdir(mo_path)
                        except Exception:
                            pass
                    # Clean empty year directories
                    try:
                        if os.path.exists(yr_path) and not os.listdir(yr_path):
                            os.rmdir(yr_path)
                    except Exception:
                        pass
                if deleted_folders > 0:
                    log.info(f"[SCHEDULER] Parquet historical cleanup complete: deleted {deleted_folders} stale partition(s).")

            # Retention cleanup for SQLite operational tables (keep last 48 hours to prevent unbounded table growth)
            try:
                from app.db.session import get_db_session
                from sqlalchemy import text
                with get_db_session() as db:
                    now = datetime.utcnow()
                    c24 = now - timedelta(hours=24)
                    c_bm_long = now - timedelta(days=7)
                    res_mp = db.execute(
                        text("""
                            DELETE FROM market_prices 
                            WHERE captured_at < :c24
                            AND NOT (city = 'Black Market' AND buy_price_max >= 500000 AND captured_at >= :c_bm_long)
                        """),
                        {"c24": c24, "c_bm_long": c_bm_long},
                    )
                    res_bm = db.execute(
                        text("DELETE FROM black_market_snapshots WHERE captured_at < :cutoff"),
                        {"cutoff": c_bm_long},
                    )
                    db.commit()
                    if res_mp.rowcount > 0 or res_bm.rowcount > 0:
                        log.info(
                            f"[SCHEDULER] DB retention cleanup: pruned {res_mp.rowcount} stale market prices and {res_bm.rowcount} stale BM snapshots (preserved BM buy orders >= 500k up to 7d)."
                        )
            except Exception as e:
                log.error(f"[SCHEDULER] DB retention cleanup failed: {e}")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Cleanup task cancelled.")
        except Exception as e:
            log.error(f"[SCHEDULER] Cleanup failed: {e}")

    async def job_refresh_volumes(self):
        """Periodic volume sync (Task 5)."""
        log.info("[SCHEDULER] Periodic Task: Market Volume Refresh")
        try:
            await self.collector.collect_volumes()
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Volume refresh task cancelled.")
        except Exception as e:
            log.error(f"[SCHEDULER] Volume refresh failed: {e}")

    async def _continuous_cycle_loop(self):
        log.info("[SCHEDULER] Starting continuous cycle loop.")
        try:
            while self._is_running:
                await self.master_cycle()
                # Dynamic pause calculated to balance low CPU/disk usage with fresh market data
                num_partitions = max(1, settings.scan_partitions)
                target_pause = max(10.0, float(settings.market_poll_interval * 60) / float(num_partitions))
                await asyncio.sleep(target_pause)
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Continuous cycle loop stopped.")

    def start(self):
        """Start the background scheduler with sequential master cycle."""
        if self._is_running:
            return

        self.scheduler.remove_all_jobs()
        log.info(f"🚀 Starting AQS Master Scheduler (Cycle: {settings.market_poll_interval} min)")

        self._is_running = True
        self._stop_requested = False

        # Safely obtain running loop
        try:
            loop = asyncio.get_running_loop()
            self._loop_task = loop.create_task(self._continuous_cycle_loop())
        except RuntimeError:
            from app.core import state
            if hasattr(state, "main_loop") and state.main_loop and state.main_loop.is_running():
                self._loop_task = state.main_loop.create_task(self._continuous_cycle_loop())
            else:
                log.warning("[SCHEDULER] No active event loop found to attach continuous cycle.")

        # Secondary maintenance tasks
        try:
            self.scheduler.add_job(
                self.job_refresh_volumes,
                IntervalTrigger(minutes=settings.volume_refresh_interval),
                id="volume_refresh",
                name="Market Volume Refresh",
                misfire_grace_time=300,
            )
        except Exception:
            pass

        self.scheduler.add_job(
            self.job_cleanup,
            IntervalTrigger(days=1),
            id="cleanup",
            name="Daily Cleanup",
            misfire_grace_time=3600,
        )

        if not self.scheduler.running:
            self.scheduler.start()

        self._is_running = True
        log.info("✅ AQS sequential background loop is now ACTIVE")

    def stop(self):
        """Pause the scheduler and stop any active ingestion cycle immediately."""
        self._is_running = False
        self._cycle_running = False
        try:
            self.collector.request_stop()
        except Exception:
            pass
        if hasattr(self, "scheduler") and self.scheduler.running:
            try:
                self.scheduler.pause()
            except Exception:
                pass
        if hasattr(self, "_loop_task") and self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        log.info("🛑 AQS background loop PAUSED")

    def shutdown(self):
        """Fully stop scheduler and release all background workers."""
        self._is_running = False
        self._cycle_running = False
        try:
            self.collector.request_stop()
        except Exception:
            pass
        if hasattr(self, "_loop_task") and self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        if hasattr(self, "scheduler") and self.scheduler.running:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception:
                pass
        log.info("Scheduler shut down")

    def reschedule(self, minutes: int):
        """Update the master cycle interval."""
        settings.market_poll_interval = minutes
        log.info(f"📅 Cycle interval set to {minutes} min")

    def resume(self):
        """Resume if paused."""
        if not self._is_running:
            self.scheduler.resume()
            self._is_running = True
            log.info("Scheduler resumed")
