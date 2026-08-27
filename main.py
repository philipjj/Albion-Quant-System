"""
Albion Quant Trading System — Main Entry Point
================================================
Production-oriented market intelligence platform for Albion Online.
"""

import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    try:
        # Avoid Windows Proactor assertion errors and socket cancellations on Python 3.14
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

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
    loop = asyncio.get_running_loop()
    state.main_loop = loop

    def _windows_proactor_exception_handler(current_loop, context):
        exc = context.get("exception")
        handle_str = str(context.get("handle", ""))
        msg = context.get("message", "")
        # Suppress known Windows Proactor shutdown race condition (BaseProactorEventLoop._start_serving assert self._sockets is not None)
        if isinstance(exc, AssertionError) and ("_attach" in handle_str or "_start_serving" in handle_str or "base_events" in str(context)):
            return
        if "BaseProactorEventLoop._start_serving" in handle_str or "proactor_events" in str(context):
            return
        if isinstance(exc, asyncio.CancelledError):
            return
        if msg or exc:
            log.warning(f"[ASYNCIO] Event loop notification: {msg or exc}")

    loop.set_exception_handler(_windows_proactor_exception_handler)

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

    # Initialize scheduler
    from app.workers.scheduler import QuantScheduler

    state.scheduler_instance = QuantScheduler()
    if getattr(settings, "auto_start_scheduler", False):
        state.scheduler_instance.start()
        state.standby_mode = False
        log.info("🚀 Master continuous background scanner ACTIVE (AUTO_START_SCHEDULER=True)")
    else:
        state.standby_mode = True
        log.info("[OK] Scheduler initialized in STANDBY mode — scans execute on-demand (⚡ Scan Now or Discord !start)")



    # Start Discord Bot
    from app.alerts.bot import start_discord_bot

    bot_task = asyncio.create_task(start_discord_bot())

    # Start NATS Ingestion
    from app.ingestion.nats_client import nats_client
    nats_task = asyncio.create_task(nats_client.start())

    try:
        yield
    except (asyncio.CancelledError, KeyboardInterrupt):
        log.info("[SHUTDOWN] Cancellation signal received. Cleaning up...")
    finally:
        # Graceful, non-blocking shutdown with strict timeouts
        from app.alerts.bot import stop_discord_bot

        try:
            await asyncio.wait_for(stop_discord_bot(), timeout=1.0)
        except Exception:
            pass

        if 'bot_task' in locals() and not bot_task.done():
            bot_task.cancel()

        try:
            await asyncio.wait_for(nats_client.stop(), timeout=1.0)
        except Exception:
            pass

        if 'nats_task' in locals() and not nats_task.done():
            nats_task.cancel()

        if state.scheduler_instance:
            try:
                state.scheduler_instance.shutdown()
            except Exception:
                pass

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


class SuppressCancelASGIMiddleware:
    """Pure ASGI middleware that absorbs CancelledError during server teardown so uvicorn exits cleanly."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass


app.add_middleware(SuppressCancelASGIMiddleware)


# Routers
from app.api import arbitrage, crafting, export, fees, market, system, user, ingest
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

app.include_router(market.router, prefix="/api/v1/market", tags=["Market"])
app.include_router(arbitrage.router, prefix="/api/v1/arbitrage", tags=["Alpha"])
app.include_router(crafting.router, prefix="/api/v1/crafting", tags=["Alpha"])
app.include_router(fees.router, prefix="/api/v1/fees", tags=["Market"])
app.include_router(user.router, prefix="/api/v1/user", tags=["System"])
app.include_router(export.router, prefix="/api/v1/export", tags=["Alerts"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(system.router, prefix="/api/system", tags=["System"], include_in_schema=False)
app.include_router(ingest.router)

WEB_DIR = Path(__file__).resolve().parent / "app" / "web"
if not WEB_DIR.exists():
    WEB_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


from fastapi import FastAPI, Request
from fastapi.responses import Response

@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    svg_icon = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="46" fill="#151A23" stroke="#D4A017" stroke-width="6"/>
        <text x="50" y="68" font-size="52" text-anchor="middle" font-family="'Cinzel', serif" font-weight="900" fill="#FFE599">⚔</text>
    </svg>"""
    return Response(content=svg_icon, media_type="image/svg+xml")

@app.get("/health", tags=["System"])
@app.get("/api/v1/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "AQS", "server": settings.active_server.value}

@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
async def serve_dashboard(request: Request):
    accept = request.headers.get("accept", "")
    ua = request.headers.get("user-agent", "")
    
    # Serve HTML dashboard to browsers, /dashboard path, or explicit html requests
    index_file = WEB_DIR / "index.html"
    is_browser = "text/html" in accept or "Mozilla" in ua or request.url.path == "/dashboard"
    
    if is_browser and index_file.exists():
        return FileResponse(str(index_file))
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
        arb_count = (
            db.query(func.count(ArbitrageOpportunity.id))
            .filter(ArbitrageOpportunity.is_active == True)
            .scalar()
        )
        craft_count = (
            db.query(func.count(CraftingOpportunity.id))
            .filter(CraftingOpportunity.is_active == True)
            .scalar()
        )
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
        "scheduler": "running"
        if state.scheduler_instance and state.scheduler_instance._is_running
        else "stopped",
        "config": {
            "api_server": settings.albion_api_server,
            "min_arb_margin": settings.min_arbitrage_margin,
            "min_arb_profit": settings.min_arbitrage_profit,
            "is_premium": settings.is_premium,
            "tax_rate": settings.premium_tax_rate
            if settings.is_premium
            else settings.non_premium_tax_rate,
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
    await parser.run_full_pipeline()
    log.info("Initialization complete.")


async def cmd_collect():
    from app.ingestion.collector import MarketCollector

    collector = MarketCollector()
    await collector.collect_prices()


async def cmd_scan():
    from app.core.scanner_integration import UnifiedScanner
    from app.db.session import get_db_session

    log.info("=" * 60)
    log.info("AQS UNIFIED MARKET SCAN")
    log.info("=" * 60)

    with get_db_session() as db:
        from app.db.models import UserProfile
        profile = db.query(UserProfile).first()
        is_premium = profile.is_premium if profile else True
        
        scanner = UnifiedScanner(premium=is_premium)
        scan_res = await scanner.scan_all(db=db, scan_bm=True, lookback_hours=48.0)
        if len(scan_res) >= 13:
            bm_arb, crafting, arb, ref, mm, enchant, quality, transmute, island, bm_craft, bm_ref, bm_enchant, bm_mm = scan_res[:13]
        elif len(scan_res) >= 9:
            bm_arb, crafting, arb, ref, mm, enchant, quality, transmute, island = scan_res[:9]
            bm_craft, bm_ref, bm_enchant, bm_mm = [], [], [], []
        else:
            bm_arb, crafting, arb, ref, mm, enchant, quality, transmute = scan_res[:8]
            island, bm_craft, bm_ref, bm_enchant, bm_mm = [], [], [], [], []

        scanner.save_opportunities(db, bm_arb, crafting, arb, ref, mm, enchant, quality_opps=quality, transmute_opps=transmute)

    log.info(
        f"Scan complete: "
        f"Royal [Transmute: {len(transmute)}, Island: {len(island)}, Craft: {len(crafting)}, Refine: {len(ref)}, Enchant: {len(enchant)}, Arb: {len(arb)}, MM: {len(mm)}] | "
        f"Caerleon/BM [B-Arb: {len(bm_arb)}, B-Enchant: {len(bm_enchant)}, B-MM: {len(bm_mm)}]"
    )


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
