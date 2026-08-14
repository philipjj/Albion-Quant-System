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
from app.db.models import PatchEventModel
from app.db.session import get_db_session
from app.ingestion.collector import MarketCollector
from app.meta.impact_forecast import PatchImpactForecaster
from app.meta.loadouts import LoadoutTracker
from app.meta.patch_parser import PatchParser
from app.meta.patch_tracker import PatchTracker

# Phase 15 Imports
from app.meta.pvp_meta import PvPMetaEngine


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

        # Phase 15 Initializations
        if settings.active_server.value == "europe":
            self.meta_engine = PvPMetaEngine(
                base_api_url="https://gameinfo-ams.albiononline.com/api/gameinfo"
            )
        elif settings.active_server.value == "asia":
            self.meta_engine = PvPMetaEngine(
                base_api_url="https://gameinfo-sgp.albiononline.com/api/gameinfo"
            )
        else:
            self.meta_engine = PvPMetaEngine()
        self.patch_tracker = PatchTracker()
        self.patch_parser = PatchParser()
        self.impact_forecaster = PatchImpactForecaster()
        self.loadout_tracker = LoadoutTracker()



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
            scan_res = await self.unified_scanner.scan_all(scan_bm=True)
            if len(scan_res) >= 9:
                bm, crafting, arb, refining, mm, enchant, quality, transmute, island = scan_res[:9]
            else:
                bm, crafting, arb, refining, mm, enchant, quality, transmute = scan_res[:8]
                island = []

            # 3. Alert
            log.info(
                f"[SCHEDULER] Step 3: Sending alerts (BM: {len(bm)}, Craft: {len(crafting)}, Arb: {len(arb)}, Refine: {len(refining)}, MM: {len(mm)}, Enchant: {len(enchant)}, Quality: {len(quality)}, Transmute: {len(transmute)}, Island: {len(island)})"
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

            # Combine Arb and BM for alerts
            all_arb = arb + bm

            # Cooldown filtering to prevent repeating stale alerts
            cooldown_seconds = settings.alert_cooldown_minutes * 60
            now_time = datetime.utcnow()

            # Check for global tier lock
            from app.core import state
            from app.alerts.discord import _is_island_opportunity

            tier_prefix = f"T{state.tier_lock}_" if state.tier_lock is not None else None

            # Filter Arb
            fresh_arb = []
            for o in all_arb:
                item_id = o.get("item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue

                src = o.get("source_city", o.get("buy_city", "Unknown"))
                dest = o.get("destination_city", o.get("sell_city", "Unknown"))
                
                is_bm = dest == "Black Market" or o.get("type") == "black_market"
                if is_bm and not settings.enable_alerts_bm_arb:
                    continue
                if not is_bm and not settings.enable_alerts_arb:
                    continue
                if not _is_valid_budget(o):
                    continue
                
                key = f"arb:{item_id}:{src}:{dest}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_arb.append((key, o))

            # Group fresh Arb by category
            from collections import defaultdict

            grouped_arb = defaultdict(list)
            for key, o in fresh_arb:
                grouped_arb[o.get("category", "Unknown")].append((key, o))

            final_arb = []
            for cat, ops in grouped_arb.items():
                ops.sort(key=lambda x: x[1].get("ev_score", 0), reverse=True)
                top_ops = ops[:10]  # Top 10 per category
                for key, o in top_ops:
                    final_arb.append(o)
                    self._alert_history[key] = now_time
            final_arb.sort(key=lambda x: (x.get("category", "Unknown"), -x.get("ev_score", 0)))

            # Filter Pure Equipment Crafting (Exclude any island / farming items)
            fresh_craft = []
            for o in crafting:
                if _is_island_opportunity(o):
                    continue
                item_id = o.get("item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue

                craft_c = o.get("crafting_city", o.get("source_city", "Unknown"))
                sell_c = o.get("sell_city", o.get("destination_city", "Any"))
                
                is_bm = sell_c == "Black Market" or o.get("sell_mode") == "BM"
                if is_bm and not settings.enable_alerts_bm_crafting:
                    continue
                if not is_bm and not settings.enable_alerts_crafting:
                    continue
                if not _is_valid_budget(o):
                    continue
                
                key = f"craft:{item_id}:{craft_c}:{sell_c}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_craft.append((key, o))

            grouped_craft = defaultdict(list)
            for key, o in fresh_craft:
                grouped_craft[o.get("category", "Unknown")].append((key, o))

            final_craft = []
            for cat, ops in grouped_craft.items():
                ops.sort(key=lambda x: x[1].get("ev_score", 0), reverse=True)
                top_ops = ops[:10]  # Top 10 per category
                for key, o in top_ops:
                    final_craft.append(o)
                    self._alert_history[key] = now_time
            final_craft.sort(key=lambda x: (x.get("category", "Unknown"), -x.get("ev_score", 0)))

            # Filter Island Agriculture / Farming
            all_island = island + [o for o in crafting if _is_island_opportunity(o)]
            fresh_island = []
            for o in all_island:
                item_id = o.get("item_id", "")
                if not settings.enable_alerts_island:
                    continue
                if not _is_valid_budget(o):
                    continue
                sell_c = o.get("sell_city", o.get("destination_city", "Any"))
                key = f"island:{item_id}:{sell_c}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_island.append((key, o))

            grouped_island = defaultdict(list)
            for key, o in fresh_island:
                grouped_island[o.get("category", "Unknown")].append((key, o))

            final_island = []
            for cat, ops in grouped_island.items():
                ops.sort(key=lambda x: x[1].get("ev_score", 0), reverse=True)
                top_ops = ops[:10]
                for key, o in top_ops:
                    final_island.append(o)
                    self._alert_history[key] = now_time

            # Filter Refining
            fresh_refine = []
            for o in refining:
                item_id = o.get("item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue

                ref_c = o.get("crafting_city", o.get("refine_city", o.get("source_city", "Unknown")))
                sell_c = o.get("sell_city", o.get("destination_city", "Any"))
                
                is_bm = sell_c == "Black Market"
                if is_bm and not settings.enable_alerts_bm_refining:
                    continue
                if not is_bm and not settings.enable_alerts_refining:
                    continue
                if not _is_valid_budget(o):
                    continue
                
                key = f"refine:{item_id}:{ref_c}:{sell_c}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_refine.append((key, o))

            grouped_refine = defaultdict(list)
            for key, o in fresh_refine:
                grouped_refine[o.get("category", "Unknown")].append((key, o))

            final_refine = []
            for cat, ops in grouped_refine.items():
                ops.sort(key=lambda x: x[1].get("ev_score", 0), reverse=True)
                top_ops = ops[:10]  # Top 10 per category
                for key, o in top_ops:
                    final_refine.append(o)
                    self._alert_history[key] = now_time
            final_refine.sort(key=lambda x: (x.get("category", "Unknown"), -x.get("ev_score", 0)))

            # Filter Market Making
            fresh_mm = []
            for o in mm:
                item_id = o.get("item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue

                src = o.get("source_city", "Unknown")
                is_bm = src == "Black Market"
                if is_bm and not settings.enable_alerts_bm_mm:
                    continue
                if not is_bm and not settings.enable_alerts_mm:
                    continue
                if not _is_valid_budget(o):
                    continue
                
                key = f"mm:{item_id}:{src}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_mm.append((key, o))

            grouped_mm = defaultdict(list)
            for key, o in fresh_mm:
                grouped_mm[o.get("category", "Unknown")].append((key, o))

            final_mm = []
            for cat, ops in grouped_mm.items():
                ops.sort(key=lambda x: x[1].get("ev_score", 0), reverse=True)
                top_ops = ops[:10]  # Top 10 per category
                for key, o in top_ops:
                    final_mm.append(o)
                    self._alert_history[key] = now_time
            final_mm.sort(key=lambda x: (x.get("category", "Unknown"), -x.get("ev_score", 0)))

            # Filter Enchanting
            fresh_enchant = []
            for o in enchant:
                item_id = o.get("target_item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue

                is_bm = o.get("destination_city") == "Black Market"
                if is_bm and not settings.enable_alerts_bm_enchanting:
                    continue
                if not is_bm and not settings.enable_alerts_enchanting:
                    continue
                if not getattr(state, "allow_enchant_transport", False) and (o.get("source_city") != "Caerleon" and o.get("base_city") != "Caerleon"):
                    continue
                if not _is_valid_budget(o):
                    continue

                key = f"enchant:{item_id}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_enchant.append((key, o))

            grouped_enchant = defaultdict(list)
            for key, o in fresh_enchant:
                grouped_enchant[o.get("category", "Unknown")].append((key, o))

            final_enchant = []
            for cat, ops in grouped_enchant.items():
                ops.sort(key=lambda x: x[1].get("estimated_profit", 0), reverse=True)
                top_ops = ops[:10]  # Top 10 per category
                for key, o in top_ops:
                    final_enchant.append(o)
                    self._alert_history[key] = now_time
            final_enchant.sort(key=lambda x: (x.get("category", "Unknown"), -x.get("estimated_profit", 0)))

            if final_arb:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts(final_arb, [], arb_limit=limit)
                log.info(f"[SCHEDULER] Sent {len(final_arb)} arb alerts after cooldown filtering.")
            if final_craft:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], final_craft, craft_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_craft)} craft alerts after cooldown filtering."
                )
            if final_refine:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], [], refine_opps=final_refine, refine_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_refine)} refine alerts after cooldown filtering."
                )
            if final_mm:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], [], mm_opps=final_mm, mm_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_mm)} MM alerts after cooldown filtering."
                )
            if final_enchant:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], [], enchant_opps=final_enchant, enchant_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_enchant)} enchant alerts after cooldown filtering."
                )

            # Filter Quality Misprice
            fresh_quality = []
            for o in quality:
                item_id = o.get("item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue
                if not _is_valid_budget(o):
                    continue
                city = o.get("source_city", "") or o.get("city", "")
                key = f"quality:{item_id}:{city}:{o.get('buy_quality', 1)}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_quality.append((key, o))

            grouped_quality = defaultdict(list)
            for key, o in fresh_quality:
                grouped_quality[o.get("category", "Unknown")].append((key, o))

            final_quality = []
            for cat, ops in grouped_quality.items():
                ops.sort(key=lambda x: x[1].get("estimated_profit", 0), reverse=True)
                top_ops = ops[:10]
                for key, o in top_ops:
                    final_quality.append(o)
                    self._alert_history[key] = now_time

            if final_quality:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], [], quality_opps=final_quality, quality_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_quality)} quality misprice alerts after cooldown filtering."
                )

            # Filter Transmutation
            fresh_transmute = []
            for o in transmute:
                item_id = o.get("item_id", "")
                if tier_prefix and not item_id.upper().startswith(tier_prefix):
                    continue
                dest = o.get("destination_city", "") or o.get("sell_city", "")
                is_bm = dest == "Black Market" or o.get("source_city") == "Caerleon"
                if is_bm and not getattr(settings, "enable_alerts_bm_transmute", True):
                    continue
                if not is_bm and not getattr(settings, "enable_alerts_transmute", True):
                    continue
                if not _is_valid_budget(o):
                    continue
                src = o.get("source_city", "")
                key = f"transmute:{item_id}:{src}:{o.get('source_item_id', '')}"
                if key in self._alert_history:
                    last_time = self._alert_history[key]
                    if (now_time - last_time).total_seconds() < cooldown_seconds:
                        continue
                fresh_transmute.append((key, o))

            grouped_transmute = defaultdict(list)
            for key, o in fresh_transmute:
                grouped_transmute[o.get("category", "Unknown")].append((key, o))

            final_transmute = []
            for cat, ops in grouped_transmute.items():
                ops.sort(key=lambda x: x[1].get("estimated_profit", 0), reverse=True)
                top_ops = ops[:10]
                for key, o in top_ops:
                    final_transmute.append(o)
                    self._alert_history[key] = now_time

            if final_transmute:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], [], transmute_opps=final_transmute, transmute_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_transmute)} transmute alerts after cooldown filtering."
                )

            if final_island:
                limit = getattr(settings, "alert_limit_per_cycle", 10)
                await self.alerter.send_batch_alerts([], [], island_opps=final_island, island_limit=limit)
                log.info(
                    f"[SCHEDULER] Sent {len(final_island)} island alerts after cooldown filtering."
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

    async def job_snapshot(self):
        """Archive live prices to snapshots table."""
        from app.analytics.snapshots import create_market_snapshot

        log.info("[SCHEDULER] Periodic Task: Market Snapshot")
        try:
            with get_db_session() as db:
                create_market_snapshot(db)
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Market Snapshot task cancelled.")
        except Exception as e:
            log.error(f"[SCHEDULER] Snapshot failed: {e}")

    async def job_cleanup(self):
        """Delete old records."""
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
                            if not os.listdir(mo_path):
                                os.rmdir(mo_path)
                        except Exception:
                            pass
                    # Clean empty year directories
                    try:
                        if not os.listdir(yr_path):
                            os.rmdir(yr_path)
                    except Exception:
                        pass
                if deleted_folders > 0:
                    log.info(f"[SCHEDULER] Parquet historical cleanup complete: deleted {deleted_folders} stale partition(s).")
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

    # Phase 15 Jobs
    async def job_meta_scan(self):
        """Scan PvP meta and update scores."""
        log.info("[SCHEDULER] Meta Task: Scanning PvP Meta")
        try:
            scores = await self.meta_engine.update_meta()
            # In a real system, we would store these in DB
            log.info(f"[SCHEDULER] Meta Scan Complete: {len(scores)} items scored")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Meta Scan task cancelled.")
        except Exception as e:
            log.error(f"[SCHEDULER] Meta Scan failed: {e}")

    async def job_patch_monitor(self):
        """Monitor patch notes and NDA updates."""
        log.info("[SCHEDULER] Meta Task: Monitoring Patch Notes")
        try:
            updates = await self.patch_tracker.check_for_updates()
            with get_db_session() as db:
                for update in updates:
                    # Check if already processed
                    exists = (
                        db.query(PatchEventModel)
                        .filter(PatchEventModel.title == update.title)
                        .first()
                    )
                    if exists:
                        continue

                    changes = self.patch_parser.parse_content(update.content)
                    forecasts = self.impact_forecaster.forecast_impact(changes)

                    # Send alerts for each change
                    for change in changes:
                        await self.alerter.send_patch_alert(
                            {
                                "title": update.title,
                                "content": f"{change.item} was {change.change}ed.",
                                "impact": f"Expected market impact: {change.expected_market_impact}",
                                "confidence": "HIGH" if change.severity > 0.7 else "MEDIUM",
                                "window": "24-72h",
                            }
                        )

                    # Save to DB so we don't alert again
                    db.add(PatchEventModel(title=update.title, content=update.content))
                    db.commit()

            log.info(f"[SCHEDULER] Patch Monitor Complete: {len(updates)} updates processed")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Patch Monitor task cancelled.")
        except Exception as e:
            log.error(f"[SCHEDULER] Patch Monitor failed: {e}")

    async def job_loadout_clustering(self):
        """Cluster popular loadouts."""
        log.info("[SCHEDULER] Meta Task: Loadout Clustering")
        try:
            loadouts = await self.loadout_tracker.get_popular_loadouts()
            log.info(f"[SCHEDULER] Loadout Clustering Complete: {len(loadouts)} loadouts tracked")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Loadout Clustering task cancelled.")
        except Exception as e:
            log.error(f"[SCHEDULER] Loadout Clustering failed: {e}")

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

        now = datetime.utcnow()

        # The Master Cycle handles all core data work sequentially in a continuous loop
        self._loop_task = asyncio.create_task(self._continuous_cycle_loop())

        # Secondary maintenance tasks
        self.scheduler.add_job(
            self.job_snapshot,
            IntervalTrigger(minutes=settings.snapshot_interval),
            id="snapshot",
            name="Market Snapshot",
            misfire_grace_time=300,
        )

        self.scheduler.add_job(
            self.job_refresh_volumes,
            IntervalTrigger(minutes=settings.volume_refresh_interval),
            id="volume_refresh",
            name="Market Volume Refresh",
            misfire_grace_time=300,
        )

        self.scheduler.add_job(
            self.job_cleanup,
            IntervalTrigger(days=1),
            id="cleanup",
            name="Daily Cleanup",
            misfire_grace_time=3600,
        )

        # Phase 15 Jobs Added to Scheduler
        self.scheduler.add_job(
            self.job_meta_scan,
            IntervalTrigger(minutes=10),
            id="meta_scan",
            name="Meta Scan",
            misfire_grace_time=60,
        )

        self.scheduler.add_job(
            self.job_patch_monitor,
            IntervalTrigger(minutes=30),
            id="patch_monitor",
            name="Patch Monitor",
            misfire_grace_time=60,
        )

        self.scheduler.add_job(
            self.job_loadout_clustering,
            IntervalTrigger(minutes=20),
            id="loadout_clustering",
            name="Loadout Clustering",
            misfire_grace_time=60,
        )

        if not self.scheduler.running:
            self.scheduler.start()

        self._is_running = True
        log.info("✅ AQS sequential background loop is now ACTIVE")

    def stop(self):
        """Pause the scheduler."""
        if self._is_running:
            self.scheduler.pause()
            self._is_running = False
            if hasattr(self, "_loop_task") and self._loop_task:
                self._loop_task.cancel()
            log.info("🛑 AQS background loop PAUSED")

    def shutdown(self):
        """Fully stop scheduler."""
        self.collector.request_stop()
        if hasattr(self, "_loop_task") and self._loop_task:
            self._loop_task.cancel()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self._is_running = False
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
