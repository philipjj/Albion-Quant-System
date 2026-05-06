"""
Albion Quant Trading System — Main Entry Point
================================================
Production-oriented market intelligence platform for Albion Online.

Usage:
    python main.py              # Start API server + scheduler
    python main.py --init       # Initialize database + download static data
    python main.py --collect    # Run one-shot market collection
    python main.py --scan       # Run one-shot arbitrage + crafting scan
"""

import asyncio
import sys
from contextlib import asynccontextmanager

import uvicorn
from app.core.config import settings
from app.core.logging import log
from app.db.session import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ═══════════════════════════════════════════════════════════════
# FASTAPI APP SETUP
# ═══════════════════════════════════════════════════════════════

scheduler_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start scheduler on startup, stop on shutdown."""
    global scheduler_instance
    log.info("🚀 Albion Quant Trading System starting up...")

    # Initialize database tables
    init_db()
    log.info("✅ Database initialized")

    if settings.disable_background_tasks:
        scheduler_instance = None
        log.info("⏭️ Background tasks disabled (DISABLE_BACKGROUND_TASKS); API only.")
        yield
        log.info("🛑 Albion Quant Trading System shut down")
        return

    # Start scheduler
    from workers.scheduler import QuantScheduler
    scheduler_instance = QuantScheduler()
    scheduler_instance.start()
    log.info("✅ Scheduler started")

    # Start Discord Bot
    from app.alerts.bot import start_discord_bot
    bot_task = asyncio.create_task(start_discord_bot())

    # Run initial collection on startup without blocking the lifespan
    async def initial_run():
        try:
            log.info("📊 Running initial data collection in the background...")
            await scheduler_instance.job_collect_prices()
            await scheduler_instance.job_collect_history()
            await scheduler_instance.job_compute_arbitrage()
            await scheduler_instance.job_compute_crafting()
        except asyncio.CancelledError:
            log.info("Initial run cancelled during shutdown.")
        except Exception as e:
            log.error(f"Error in initial run: {e}")

    init_task = asyncio.create_task(initial_run())

    yield

    # Shutdown
    from app.alerts.bot import stop_discord_bot
    await stop_discord_bot()

    if not bot_task.done():
        bot_task.cancel()

    if not init_task.done():
        init_task.cancel()
        try:
            await init_task
        except asyncio.CancelledError:
            pass

    if scheduler_instance:
        scheduler_instance.shutdown()
    log.info("🛑 Albion Quant Trading System shut down")


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
    # Browsers reject allow_credentials=True with wildcard origins
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
from app.api.arbitrage import router as arbitrage_router
from app.api.crafting import router as crafting_router
from app.api.export import router as export_router
from app.api.market import router as market_router
from app.api.user import router as user_router

app.include_router(market_router)
app.include_router(arbitrage_router)
app.include_router(crafting_router)
app.include_router(export_router)
app.include_router(user_router)


@app.get("/", tags=["System"])
def root():
    """System health check."""
    return {
        "system": "Albion Quant Trading System",
        "version": "0.1.0",
        "status": "operational",
        "endpoints": {
            "market": "/market/item/{item_id}",
            "market_volume": "/market/top-volume",
            "market_trending": "/market/trending",
            "arbitrage_top": "/arbitrage/top",
            "arbitrage_item": "/arbitrage/item/{item_id}",
            "crafting_top": "/crafting/top",
            "crafting_item": "/crafting/item/{item_id}",
            "docs": "/docs",
        },
    }


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
        "scheduler": "running" if scheduler_instance and scheduler_instance._is_running else "stopped",
        "config": {
            "api_server": settings.albion_api_server,
            "min_arb_margin": settings.min_arbitrage_margin,
            "min_arb_profit": settings.min_arbitrage_profit,
            "is_premium": settings.is_premium,
            "tax_rate": settings.tax_rate,
        },
    }


# ═══════════════════════════════════════════════════════════════
# CLI COMMANDS
# ═══════════════════════════════════════════════════════════════

async def cmd_init():
    """Initialize: create DB tables + download/parse static data."""
    from app.staticdata.parser import StaticDataParser

    log.info("=" * 60)
    log.info("INITIALIZATION — Database + Static Data")
    log.info("=" * 60)

    init_db()
    log.info("✅ Database tables created")

    parser = StaticDataParser()
    stats = await parser.run_full_pipeline()
    log.info(f"✅ Static data loaded: {stats}")


async def cmd_collect():
    """Run one-shot market price collection."""
    from app.ingestion.collector import MarketCollector

    init_db()
    collector = MarketCollector()
    stats = await collector.collect_all_prices()
    log.info(f"✅ Collection complete: {stats}")


async def cmd_scan():
    """Run one-shot arbitrage + crafting scan."""
    from app.alerts.discord import DiscordAlerter
    from app.arbitrage.scanner import ArbitrageScanner
    from app.crafting.engine import CraftingEngine
    from rich.console import Console
    from rich.table import Table

    init_db()
    console = Console(force_terminal=True)

    # Arbitrage
    scanner = ArbitrageScanner()
    arb_opps = await scanner.scan()
    scanner.store_opportunities()

    if arb_opps:
        table = Table(title="[ARBITRAGE] Top Opportunities", show_lines=True)
        table.add_column("Item", style="cyan")
        table.add_column("Buy City", style="green")
        table.add_column("Sell City", style="yellow")
        table.add_column("Buy", justify="right")
        table.add_column("Sell", justify="right")
        table.add_column("Profit", justify="right", style="bold green")
        table.add_column("Margin", justify="right", style="bold")
        table.add_column("Risk", justify="right")

        for opp in arb_opps[:15]:
            table.add_row(
                opp["item_name"][:30],
                opp["source_city"],
                opp["destination_city"],
                f"{opp['buy_price']:,}",
                f"{opp['sell_price']:,}",
                f"{opp['estimated_profit']:,.0f}",
                f"{opp['estimated_margin']:.1f}%",
                f"{opp['risk_score']:.2f}",
            )
        console.print(table)
    else:
        log.info("No arbitrage opportunities found")

    # Crafting
    engine = CraftingEngine()
    craft_opps = await engine.compute()
    engine.store_opportunities()

    if craft_opps:
        table2 = Table(title="[CRAFTING] Top Opportunities", show_lines=True)
        table2.add_column("Item", style="cyan")
        table2.add_column("Craft City", style="green")
        table2.add_column("Cost", justify="right")
        table2.add_column("Profit", justify="right", style="bold green")
        table2.add_column("+Journal", justify="right", style="dim")
        table2.add_column("Margin", justify="right", style="bold")
        table2.add_column("P/Focus", justify="right")
        table2.add_column("Vol/Day", justify="right", style="blue")
        table2.add_column("Ingredients (Summary)", style="dim")

        for opp in craft_opps[:15]:
            ing_summary = ", ".join([f"{i['quantity']}x {i['name']}" for i in opp.get("ingredients_detail", [])[:2]])
            if len(opp.get("ingredients_detail", [])) > 2:
                ing_summary += "..."

            table2.add_row(
                opp["item_name"][:25],
                opp["crafting_city"],
                f"{opp['craft_cost']:,.0f}",
                f"{opp['profit']:,.0f}",
                f"{opp.get('journal_profit', 0):,.0f}",
                f"{opp['profit_margin']:.1f}%",
                f"{opp.get('profit_per_focus', 0):,.1f}",
                f"{opp.get('daily_volume', 0):,}",
                ing_summary,
            )
        console.print(table2)
    else:
        log.info("No crafting opportunities found")

    # Send alerts
    alerter = DiscordAlerter()
    await alerter.send_batch_alerts(arb_opps, craft_opps, arb_limit=15, craft_limit=20)

    log.info(f"✅ Scan complete: {len(arb_opps)} arbitrage, {len(craft_opps)} crafting")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Main entry point with CLI argument handling."""
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower().strip("-")

        if cmd == "init":
            asyncio.run(cmd_init())
        elif cmd == "collect":
            asyncio.run(cmd_collect())
        elif cmd == "scan":
            asyncio.run(cmd_scan())
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python main.py [--init | --collect | --scan]")
            sys.exit(1)
    else:
        # Default: start API server with scheduler
        import os
        listen_port = int(os.getenv("PORT", 8000))
        log.info(f"Starting Albion Quant API server on http://localhost:{listen_port}")
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=listen_port,
            reload=False,
            log_level="info",
        )


if __name__ == "__main__":
    main()
