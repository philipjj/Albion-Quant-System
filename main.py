"""
Albion Quant Trading System — Main Entry Point
================================================
Production-oriented market intelligence platform for Albion Online.
"""

import asyncio
import sys
from contextlib import asynccontextmanager

import uvicorn

# ═══════════════════════════════════════════════════════════════
# FASTAPI APP SETUP
# ═══════════════════════════════════════════════════════════════
from app.core import state
from app.core.config import settings
from app.core.logging import log
from app.db.session import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core import state
    log.info("[START] Albion Quant Trading System starting up...")

    # Initialize database tables
    init_db()
    
    # [SAFETY] Model Integrity Check (Task 5.4)
    from app.db.models import Item
    required_fields = ["item_id", "tier", "category"]
    for field in required_fields:
        if not hasattr(Item, field):
            log.critical(f"FATAL: Item model missing required field: {field}")
            sys.exit(1)
            
    log.info("[OK] Database and Models verified")

    if settings.disable_background_tasks:
        state.scheduler_instance = None
        log.info("⏭️ Background tasks disabled (DISABLE_BACKGROUND_TASKS); API only.")
        yield
        log.info("[STOP] Albion Quant Trading System shut down")
        return

    # Initialize and START scheduler automatically
    from app.workers.scheduler import QuantScheduler
    state.scheduler_instance = QuantScheduler()
    state.scheduler_instance.start()
    log.info("[OK] Background scheduler started automatically")

    # Start Discord Bot
    from app.alerts.bot import start_discord_bot
    bot_task = asyncio.create_task(start_discord_bot())

    yield

    # Shutdown
    from app.alerts.bot import stop_discord_bot
    await stop_discord_bot()

    if not bot_task.done():
        bot_task.cancel()

    if state.scheduler_instance:
        state.scheduler_instance.shutdown()
    log.info("[STOP] Albion Quant Trading System shut down")


app = FastAPI(
    title="Albion Quant Trading System",
    description="Market intelligence platform for Albion Online — arbitrage, crafting ROI, and alerts.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.api import arbitrage, crafting, export, fees, market, user

app.include_router(market.router, prefix="/api/v1/market", tags=["Market"])
app.include_router(arbitrage.router, prefix="/api/v1/arbitrage", tags=["Alpha"])
app.include_router(crafting.router, prefix="/api/v1/crafting", tags=["Alpha"])
app.include_router(fees.router, prefix="/api/v1/fees", tags=["Market"])
app.include_router(user.router, prefix="/api/v1/user", tags=["System"])
app.include_router(export.router, prefix="/api/v1/export", tags=["Alerts"])

@app.get("/", tags=["System"])
def root():
    return {"message": "Albion Quant Trading System API", "status": "online"}


@app.get("/status", tags=["System"])
def system_status():
    """Detailed system status."""
    from app.analytics.quality import quality_snapshot
    from app.core.feature_gate import feature_gate
    from app.db.models import ArbitrageOpportunity, CraftingOpportunity, Item, MarketPrice
    from app.db.session import get_db_session
    from sqlalchemy import func

    with get_db_session() as db:
        item_count = db.query(func.count(Item.item_id)).scalar()
        price_count = db.query(func.count(MarketPrice.id)).scalar()
        arb_count = db.query(func.count(ArbitrageOpportunity.id)).filter(
            ArbitrageOpportunity.is_active == True
        ).scalar()
        craft_count = db.query(func.count(CraftingOpportunity.id)).filter(
            CraftingOpportunity.is_active == True
        ).scalar()
        quality = quality_snapshot(db, lookback_hours=2)

    return {
        "database": {
            "items": item_count,
            "price_records": price_count,
            "active_arbitrage": arb_count,
            "active_crafting": craft_count,
        },
        "data_quality": quality,
        "feature_gate": {
            "prices_supported": bool(feature_gate.prices_supported),
            "history_supported": bool(feature_gate.history_supported),
            "orders_supported": bool(feature_gate.orders_supported),
            "is_rate_limited": bool(feature_gate.is_rate_limited),
        },
        "scheduler": "running" if state.scheduler_instance and state.scheduler_instance._is_running else "stopped",
        "config": {
            "api_server": settings.albion_api_server,
            "min_arb_margin": settings.min_arbitrage_margin,
            "min_arb_profit": settings.min_arbitrage_profit,
            "is_premium": settings.is_premium,
            "tax_rate": settings.premium_tax_rate if settings.is_premium else settings.non_premium_tax_rate,
        },
    }


# ═══════════════════════════════════════════════════════════════
# CLI COMMANDS
# ═══════════════════════════════════════════════════════════════

async def cmd_init():
    """Initialize: create DB tables + download/parse static data."""
    from app.staticdata.parser import StaticDataParser

    log.info("=" * 60)
    log.info("AQS INITIALIZATION SEQUENCE")
    log.info("=" * 60)

    init_db()
    parser = StaticDataParser()
    await parser.full_rebuild()
    log.info("Initialization complete.")


async def cmd_collect():
    from app.ingestion.collector import MarketCollector
    collector = MarketCollector()
    await collector.collect_all_prices()


async def cmd_scan():
    from app.arbitrage.scanner import ArbitrageScanner
    scanner = ArbitrageScanner()
    await scanner.scan()
    scanner.store_opportunities()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()

    if args.init:
        asyncio.run(cmd_init())
    elif args.collect:
        asyncio.run(cmd_collect())
    elif args.scan:
        asyncio.run(cmd_scan())
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
