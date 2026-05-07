"""
APScheduler-based task scheduler for development.
Handles periodic market collection, arbitrage/crafting computation, and alerts.
"""

import asyncio
from datetime import datetime

from app.alerts.discord import DiscordAlerter
from app.arbitrage.scanner import ArbitrageScanner
from app.core.config import settings
from app.core.logging import log
from app.crafting.engine import CraftingEngine
from app.ingestion.collector import MarketCollector
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


class QuantScheduler:
    """Manages all scheduled jobs for the trading system."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.collector = MarketCollector()
        self.arb_scanner = ArbitrageScanner()
        self.craft_engine = CraftingEngine()
        self.alerter = DiscordAlerter()
        self._is_running = False

    async def job_collect_prices(self):
        """Collect market prices from API (High Frequency)."""
        log.info("[SCHEDULER] Step 1: Syncing Market Prices...")
        try:
            await self.collector.collect_prices()
            return True
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Price collection cancelled.")
            return False
        except Exception:
            import traceback
            log.error(f"[SCHEDULER] Price collection failed:\n{traceback.format_exc()}")
            return False

    async def job_refresh_volumes(self):
        """Refresh historical volumes (Low Frequency)."""
        log.info("[SCHEDULER] Periodic Task: Refreshing Market Volumes")
        try:
            await self.collector.collect_volumes()
        except Exception as e:
            log.error(f"[SCHEDULER] Volume refresh failed: {e}")

    async def job_compute_arbitrage(self):
        """Find inter-city arbitrage opportunities."""
        log.info("[SCHEDULER] Step 2: Running Arbitrage Analysis...")
        try:
            opps = await self.arb_scanner.scan(fast_sell=False)
            self.arb_scanner.store_opportunities()
            if opps:
                await self.alerter.send_batch_alerts(opps, [], arb_limit=settings.alert_limit_per_cycle)
            log.info(f"[SCHEDULER] Arbitrage Complete: {len(opps)} opportunities found")
        except Exception as e:
            log.error(f"[SCHEDULER] Arbitrage failed: {e}")

    async def job_compute_crafting(self):
        """Find profitable crafting opportunities."""
        log.info("[SCHEDULER] Step 3: Running Crafting ROI Analysis...")
        try:
            opps = await self.craft_engine.scan()
            self.craft_engine.store_opportunities()
            if opps:
                await self.alerter.send_batch_alerts([], opps, craft_limit=settings.alert_limit_per_cycle)
            log.info(f"[SCHEDULER] Crafting Complete: {len(opps)} opportunities found")
        except Exception as e:
            log.error(f"[SCHEDULER] Crafting failed: {e}")

    async def master_cycle(self):
        """The Master Cycle: Ensures sequential execution (Ingest -> Analyze -> Alert)."""
        log.info("═══ STARTING MASTER QUANT CYCLE ═══")
        start_time = datetime.utcnow()

        try:
            # 1. Ingest Data
            success = await self.job_collect_prices()
            if not success:
                log.warning("[SCHEDULER] Cycle aborted: Ingest failed or was cancelled.")
                return

            # 2. Analyze (sequentially to avoid DB locks and use latest data)
            await self.job_compute_arbitrage()
            await self.job_compute_crafting()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            log.info(f"═══ MASTER QUANT CYCLE COMPLETE ({duration:.1f}s) ═══")

        except Exception as e:
            log.error(f"❌ MASTER CYCLE FAILED: {e}", exc_info=True)

    async def job_snapshot(self):
        """Archive live prices to snapshots table."""
        from app.analytics.snapshots import create_market_snapshot
        log.info("[SCHEDULER] Periodic Task: Market Snapshot")
        try:
            with self.arb_scanner.db_session() as db:
                create_market_snapshot(db)
        except Exception as e:
            log.error(f"[SCHEDULER] Snapshot failed: {e}")

    async def job_cleanup(self):
        """Delete old records."""
        from app.db.session import get_db_session
        from app.db.models import MarketPrice
        from datetime import timedelta
        
        log.info("[SCHEDULER] Periodic Task: Database Cleanup")
        try:
            cutoff = datetime.utcnow() - timedelta(days=settings.market_data_retention_days)
            with get_db_session() as db:
                deleted = db.query(MarketPrice).filter(MarketPrice.captured_at < cutoff).delete()
            log.info(f"[SCHEDULER] Cleanup: removed {deleted} old records")
        except Exception as e:
            log.error(f"[SCHEDULER] Cleanup failed: {e}")

    def start(self):
        """Start the background scheduler with sequential master cycle."""
        if self._is_running:
            return

        self.scheduler.remove_all_jobs()
        log.info(f"🚀 Starting AQS Master Scheduler (Cycle: {settings.market_poll_interval} min)")

        now = datetime.utcnow()

        # The Master Cycle handles all core data work sequentially
        self.scheduler.add_job(
            self.master_cycle,
            IntervalTrigger(minutes=settings.market_poll_interval),
            id="master_cycle",
            name="Master Quant Cycle",
            next_run_time=now,
            misfire_grace_time=60,
            coalesce=True,
        )

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

        if not self.scheduler.running:
            self.scheduler.start()
            
        self._is_running = True
        log.info("✅ AQS sequential background loop is now ACTIVE")

    def stop(self):
        """Pause the scheduler."""
        if self._is_running:
            self.scheduler.pause()
            self._is_running = False
            log.info("🛑 AQS background loop PAUSED")

    def shutdown(self):
        """Fully stop scheduler."""
        self.collector.request_stop()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self._is_running = False
        log.info("Scheduler shut down")

    def reschedule(self, minutes: int):
        """Update the master cycle interval."""
        settings.market_poll_interval = minutes
        if self._is_running:
            trigger = IntervalTrigger(minutes=minutes)
            self.scheduler.reschedule_job("master_cycle", trigger=trigger)
            log.info(f"📅 Master cycle updated to {minutes} min")
        else:
            log.info(f"📅 Cycle interval set to {minutes} min")

    def resume(self):
        """Resume if paused."""
        if not self._is_running:
            self.scheduler.resume()
            self._is_running = True
            log.info("Scheduler resumed")
