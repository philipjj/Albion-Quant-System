"""
APScheduler-based task scheduler for development.
Handles periodic market collection, arbitrage/crafting computation, and alerts.
"""

import asyncio

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
        """Collect market prices from API."""
        log.info("[SCHEDULER] Running: collect_market_prices")
        try:
            stats = await self.collector.collect_all_prices()
            log.info(f"[SCHEDULER] Price collection complete: {stats}")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Price collection cancelled.")
            raise
        except Exception as e:
            log.error(f"[SCHEDULER] Price collection failed: {e}")

    async def job_collect_history(self):
        """Collect real market volume history."""
        log.info("[SCHEDULER] Running: collect_market_history")
        try:
            stats = await self.collector.collect_market_history()
            log.info(f"[SCHEDULER] History collection complete: {stats}")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] History collection cancelled.")
            raise
        except Exception as e:
            log.error(f"[SCHEDULER] History collection failed: {e}")

    async def job_compute_arbitrage(self):
        """Compute arbitrage opportunities and send alerts."""
        log.info("[SCHEDULER] Running: compute_arbitrage")
        try:
            # Force fast_sell=True to ensure instant profit directly to buy orders
            opps = await self.arb_scanner.scan(fast_sell=True)
            self.arb_scanner.store_opportunities()

            if opps:
                # Use higher limits for background jobs to fill categories
                await self.alerter.send_batch_alerts(opps, [], arb_limit=10)

            log.info(f"[SCHEDULER] Arbitrage: {len(opps)} opportunities found")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Arbitrage computation cancelled.")
            raise
        except Exception as e:
            log.error(f"[SCHEDULER] Arbitrage computation failed: {e}")

    async def job_compute_crafting(self):
        """Compute crafting ROI and send alerts."""
        log.info("[SCHEDULER] Running: compute_crafting_roi")
        try:
            opps = await self.craft_engine.compute()
            self.craft_engine.store_opportunities()

            if opps:
                # Use higher limits for background jobs to fill categories
                await self.alerter.send_batch_alerts([], opps, craft_limit=15)

            log.info(f"[SCHEDULER] Crafting: {len(opps)} opportunities found")
        except asyncio.CancelledError:
            log.info("[SCHEDULER] Crafting computation cancelled.")
            raise
        except Exception as e:
            log.error(f"[SCHEDULER] Crafting computation failed: {e}")

    async def job_snapshot(self):
        """Create hourly market snapshot."""
        log.info("[SCHEDULER] Running: snapshot_market_state")
        try:
            count = await self.collector.create_snapshot()
            log.info(f"[SCHEDULER] Snapshot: {count} records")
        except Exception as e:
            log.error(f"[SCHEDULER] Snapshot failed: {e}")

    async def job_cleanup(self):
        """Clean up old cache/price data."""
        log.info("[SCHEDULER] Running: cleanup_old_cache")
        try:
            deleted = await self.collector.cleanup_old_prices(keep_hours=48)
            log.info(f"[SCHEDULER] Cleanup: {deleted} old records removed")
        except Exception as e:
            log.error(f"[SCHEDULER] Cleanup failed: {e}")

    def start(self):
        """Start all scheduled jobs."""
        if self._is_running:
            return

        # After stop(), jobs stay registered and the scheduler is only paused —
        # resuming avoids duplicate job IDs on a second start().
        if self.scheduler.get_jobs():
            self.scheduler.resume()
            self._is_running = True
            log.info("Scheduler resumed (existing jobs)")
            return

        log.info("Starting scheduler with intervals:")
        log.info(f"  Market collection: every {settings.market_poll_interval} min")
        log.info(f"  Arbitrage compute: every {settings.arbitrage_compute_interval} min")
        log.info(f"  Crafting compute:  every {settings.crafting_compute_interval} min")
        log.info(f"  Snapshot:          every {settings.snapshot_interval} min")

        self.scheduler.add_job(
            self.job_collect_prices,
            IntervalTrigger(minutes=settings.market_poll_interval),
            id="collect_prices",
            name="Collect Market Prices",
        )

        self.scheduler.add_job(
            self.job_compute_arbitrage,
            IntervalTrigger(minutes=settings.arbitrage_compute_interval),
            id="compute_arbitrage",
            name="Compute Arbitrage",
        )

        self.scheduler.add_job(
            self.job_compute_crafting,
            IntervalTrigger(minutes=settings.crafting_compute_interval),
            id="compute_crafting",
            name="Compute Crafting ROI",
        )

        self.scheduler.add_job(
            self.job_snapshot,
            IntervalTrigger(minutes=settings.snapshot_interval),
            id="snapshot",
            name="Market Snapshot",
        )

        self.scheduler.add_job(
            self.job_cleanup,
            IntervalTrigger(minutes=settings.snapshot_interval),
            id="cleanup",
            name="Cleanup Old Data",
        )

        self.scheduler.add_job(
            self.job_collect_history,
            IntervalTrigger(hours=4), # Run history every 4h for stability
            id="collect_history",
            name="Collect Market History",
        )

        self.scheduler.start()
        self._is_running = True
        log.info("Scheduler started successfully")

    def stop(self):
        """Pause the scheduler (stops all background polling)."""
        if self._is_running:
            self.scheduler.pause()
            self._is_running = False
            log.info("Scheduler paused")

    def shutdown(self):
        """Fully stop scheduler and signal running jobs to exit quickly."""
        self.collector.request_stop()
        if self.scheduler.running:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception as e:
                log.warning(f"Scheduler shutdown warning: {e}")
        self._is_running = False
        log.info("Scheduler shut down")

    def resume(self):
        """Resume the scheduler if paused."""
        if not self._is_running:
            self.scheduler.resume()
            self._is_running = True
            log.info("Scheduler resumed")
