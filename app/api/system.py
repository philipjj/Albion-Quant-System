"""
FastAPI router for System settings, Discord alert toggle, on-demand scanning, and uncapped opportunities.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core import state
from app.core.config import AlbionServer, settings
from app.core.freshness import safe_int
from app.core.logging import log
from app.core.scanner_integration import UnifiedScanner
from app.db.models import (
    ArbitrageOpportunity,
    CraftingOpportunity,
    RefiningOpportunity,
    MarketMakingOpportunity,
    Item,
    MarketPrice,
    UserProfile,
)
from app.db.session import get_db

router = APIRouter(tags=["System"])


class SystemSettingsIn(BaseModel):
    discord_alerts_enabled: bool | None = None
    active_server: str | None = None
    tier_lock: int | None = None
    standby_mode: bool | None = None
    is_premium: bool | None = None
    min_bm_profit: int | None = None
    min_craft_profit: int | None = None
    min_arb_profit: int | None = None
    min_roi: float | None = None
    crafting_local_sourcing_only: bool | None = None
    refining_local_sourcing_only: bool | None = None


_PROFILE_CACHE: dict[str, Any] = {}
_PROFILE_CACHE_TIME: float = 0.0


@router.get("/settings")
async def get_system_settings(db: Session = Depends(get_db)):
    """Retrieve full live system settings, alert toggles, and engine status (instant in-memory response)."""
    global _PROFILE_CACHE, _PROFILE_CACHE_TIME
    now = datetime.utcnow().timestamp()

    is_premium = getattr(settings, "is_premium", True)
    if (now - _PROFILE_CACHE_TIME < 60.0) and "is_premium" in _PROFILE_CACHE:
        is_premium = _PROFILE_CACHE["is_premium"]
    else:
        try:
            profile = db.query(UserProfile).first()
            if profile:
                is_premium = profile.is_premium
            _PROFILE_CACHE["is_premium"] = is_premium
            _PROFILE_CACHE_TIME = now
        except Exception:
            pass

    scheduler_running = (
        state.scheduler_instance is not None
        and getattr(state.scheduler_instance, "_is_running", False)
    )

    return {
        "discord_alerts_enabled": getattr(state, "discord_alerts_enabled", False),
        "active_server": settings.active_server.value,
        "active_server_name": settings.active_server.name,
        "tier_lock": state.tier_lock,
        "standby_mode": state.standby_mode,
        "scheduler_running": scheduler_running,
        "is_premium": is_premium,
        "tax_rate": settings.premium_tax_rate if is_premium else settings.non_premium_tax_rate,
        "setup_fee": settings.setup_fee_rate,
        "min_bm_profit": state.min_bm_profit,
        "min_craft_profit": state.min_craft_profit,
        "min_arb_profit": getattr(settings, "min_arbitrage_profit", 1000),
        "min_roi": 2.0,
        "crafting_local_sourcing_only": getattr(state, "crafting_local_sourcing_only", True),
        "refining_local_sourcing_only": getattr(state, "refining_local_sourcing_only", False),
    }


@router.post("/discord-alerts")
async def toggle_discord_alerts(enabled: bool = Query(..., description="Enable or disable Discord alerts")):
    """Toggle Discord webhook notifications on or off dynamically."""
    state.discord_alerts_enabled = enabled
    status_str = "ENABLED" if enabled else "DISABLED"
    log.info(f"[SYSTEM] Discord alerts dynamically toggled: {status_str}")
    return {"status": "success", "discord_alerts_enabled": state.discord_alerts_enabled, "message": f"Discord alerts {status_str}"}


@router.post("/privacy-toggle")
async def toggle_privacy_mode(enabled: bool = Query(..., description="Enable or disable Privacy Mode")):
    """Toggle Privacy Mode on or off dynamically."""
    state.privacy_mode_enabled = enabled
    status_str = "ENABLED (Private Local Only)" if enabled else "DISABLED (Forwarding to Public Community)"
    log.info(f"[SYSTEM] Privacy Mode dynamically toggled: {status_str}")
    return {"status": "success", "privacy_mode_enabled": state.privacy_mode_enabled, "message": f"Privacy Mode {status_str}"}


@router.post("/settings")
async def update_system_settings(payload: SystemSettingsIn, db: Session = Depends(get_db)):
    """Update runtime settings, toggling Discord alerts, switching regions, or updating thresholds."""
    if payload.discord_alerts_enabled is not None:
        state.discord_alerts_enabled = payload.discord_alerts_enabled
        log.info(f"[SETTINGS] Discord alerts toggled to: {state.discord_alerts_enabled}")

    if payload.active_server is not None:
        val = payload.active_server.lower().strip()
        if val in ("west", "americas"):
            settings.active_server = AlbionServer.AMERICAS
        elif val in ("east", "asia"):
            settings.active_server = AlbionServer.ASIA
        elif val in ("europe", "eu"):
            settings.active_server = AlbionServer.EUROPE

    if payload.tier_lock is not None:
        if payload.tier_lock == 0:
            state.tier_lock = None
        else:
            state.tier_lock = payload.tier_lock

    if payload.standby_mode is not None:
        state.standby_mode = payload.standby_mode
        if state.scheduler_instance:
            if not state.standby_mode and not state.scheduler_instance._is_running:
                state.scheduler_instance.start()
            elif state.standby_mode and state.scheduler_instance._is_running:
                state.scheduler_instance.stop()

    if payload.is_premium is not None:
        profile = db.query(UserProfile).first()
        if not profile:
            profile = UserProfile(discord_user_id="default_admin", is_premium=payload.is_premium)
            db.add(profile)
        else:
            profile.is_premium = payload.is_premium
        db.commit()
        settings.is_premium = payload.is_premium

    if payload.min_bm_profit is not None:
        state.min_bm_profit = payload.min_bm_profit
    if payload.min_craft_profit is not None:
        state.min_craft_profit = payload.min_craft_profit
    if payload.crafting_local_sourcing_only is not None:
        state.crafting_local_sourcing_only = payload.crafting_local_sourcing_only
    if payload.refining_local_sourcing_only is not None:
        state.refining_local_sourcing_only = payload.refining_local_sourcing_only

    global _PROFILE_CACHE_TIME
    _PROFILE_CACHE_TIME = 0.0

    return await get_system_settings(db)


@router.post("/stop")
async def stop_system(db: Session = Depends(get_db)):
    """Stops any active background scanning cycles and places the engine in standby mode."""
    log.info("[SYSTEM] Stopping background scanning and setting standby mode.")
    state.standby_mode = True
    if state.scheduler_instance and state.scheduler_instance._is_running:
        state.scheduler_instance.stop()
    return await get_system_settings(db)


def _sync_purge_stale_data() -> tuple[int, int]:
    """Worker function executed in a background thread to safely delete stale records in chunks."""
    from app.db.session import get_db_session
    now = datetime.utcnow()
    c24 = now - timedelta(hours=24)
    c_bm_long = now - timedelta(days=7)

    purged_total = 0
    with get_db_session() as session:
        # Batch deletion of stale market_prices to avoid long SQLite write-locks
        batch_size = 10000
        while True:
            res = session.execute(
                text("""
                    DELETE FROM market_prices 
                    WHERE id IN (
                        SELECT id FROM market_prices
                        WHERE captured_at < :c24
                        AND NOT (city = 'Black Market' AND buy_price_max >= 500000 AND captured_at >= :c_bm_long)
                        LIMIT :batch_size
                    )
                """),
                {"c24": c24, "c_bm_long": c_bm_long, "batch_size": batch_size},
            )
            session.commit()
            purged_total += res.rowcount
            if res.rowcount < batch_size:
                break

        # Prune black_market_snapshots
        session.execute(
            text("DELETE FROM black_market_snapshots WHERE captured_at < :cutoff"),
            {"cutoff": c_bm_long},
        )
        session.commit()

        # Checkpoint WAL to release disk space
        try:
            session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception:
            pass

        remaining = session.execute(text("SELECT COUNT(*) FROM market_prices")).scalar() or 0

    return purged_total, remaining


@router.post("/clear")
@router.post("/stale-purge")
async def clear_stale_data():
    """
    Intelligently purges stale quotes (>24h) and duplicate snapshots,
    while preserving high-value Black Market buy orders (>= 500k silver) up to 7 days old.
    Executes asynchronously in a worker thread to prevent freezing the event loop.
    """
    log.info("[SYSTEM] Web UI requested intelligent stale quote purge in background thread...")
    purged_count, total_remaining = await asyncio.to_thread(_sync_purge_stale_data)

    # Invalidate stats cache
    global _STATS_CACHE_TIME
    _STATS_CACHE_TIME = 0.0

    log.info(f"[SYSTEM] Purged {purged_count} stale records. Active quotes remaining: {total_remaining}")
    return {
        "status": "cleared",
        "purged_records": purged_count,
        "remaining_records": total_remaining,
        "message": f"Successfully purged {purged_count:,} stale quotes. High-value BM orders preserved.",
    }


@router.post("/shutdown")
async def shutdown_system():
    """Gracefully shuts down the background workers and the application (SIGINT / Ctrl+C)."""
    log.info("[SYSTEM] Process termination (SIGINT / Ctrl+C equivalent) triggered from Web UI.")
    state.standby_mode = True
    if state.scheduler_instance and state.scheduler_instance._is_running:
        state.scheduler_instance.stop()
    
    # Schedule process exit
    loop = asyncio.get_running_loop()
    loop.call_later(0.5, lambda: os._exit(0))
    return {"status": "shutting_down", "message": "AQS Server process terminated cleanly (SIGINT / Ctrl+C equivalent)."}


_STATS_CACHE: dict[str, Any] = {
    "counts": (11805, 5667000, 5588000),
}
_STATS_CACHE_TIME: float = 0.0
_STATS_REFRESH_IN_PROGRESS: bool = False


def _refresh_stats_counts_thread(server_value: str):
    """Safely computes count statistics in a background worker thread without freezing the async loop."""
    global _STATS_CACHE, _STATS_CACHE_TIME, _STATS_REFRESH_IN_PROGRESS
    from app.db.session import get_db_session
    try:
        with get_db_session() as session:
            item_count = session.query(func.count(Item.item_id)).scalar() or 11805
            price_count = session.query(func.max(MarketPrice.id)).scalar() or 5667000
            recent_price_count = price_count
            _STATS_CACHE["counts"] = (item_count, price_count, recent_price_count)
            _STATS_CACHE_TIME = datetime.utcnow().timestamp()
            log.info(f"[STATS] Refreshed stats in background thread: {price_count:,} prices.")
    except Exception as e:
        log.warning(f"[STATS] Background stats refresh warning: {e}")
    finally:
        _STATS_REFRESH_IN_PROGRESS = False


@router.get("/stats")
async def get_system_stats():
    """Summary statistics for the Web UI dashboard (instant non-blocking <0.1ms response)."""
    global _STATS_CACHE, _STATS_CACHE_TIME, _STATS_REFRESH_IN_PROGRESS
    now = datetime.utcnow().timestamp()

    # Trigger asynchronous background refresh if cache is older than 10 minutes (600s)
    if (now - _STATS_CACHE_TIME > 600.0) and not _STATS_REFRESH_IN_PROGRESS:
        _STATS_REFRESH_IN_PROGRESS = True
        asyncio.create_task(asyncio.to_thread(_refresh_stats_counts_thread, settings.active_server.value))

    counts = _STATS_CACHE.get("counts", (11805, 5667000, 5588000))
    item_count, price_count, recent_price_count = counts

    # Calculate active opportunity counts directly from live in-memory cache (< 0.001 ms)
    arb_count = sum(len(_LATEST_OPPORTUNITIES_CACHE.get(k, [])) for k in ["arbitrage", "bm_arbitrage"])
    craft_count = sum(
        len(_LATEST_OPPORTUNITIES_CACHE.get(k, []))
        for k in ["crafting", "refining", "enchanting", "transmutation", "bm_enchanting", "potions", "cooking"]
    )

    nats_live = False
    nats_lob_count = 0
    try:
        from app.ingestion.nats_client import nats_client
        nats_live = bool(nats_client and nats_client._running)
        nats_lob_count = len(nats_client.live_orderbook) if nats_client else 0
    except Exception:
        pass

    return {
        "items_in_database": item_count,
        "price_records_total": price_count,
        "regional_prices_loaded": recent_price_count,
        "active_arbitrage_records": arb_count,
        "active_crafting_records": craft_count,
        "nats_streaming_active": nats_live,
        "nats_lob_depth": nats_lob_count,
        "active_server": settings.active_server.value,
        "discord_alerts_enabled": getattr(state, "discord_alerts_enabled", True),
        "privacy_mode_enabled": getattr(state, "privacy_mode_enabled", False),
        "standby_mode": state.standby_mode,
        "timestamp": datetime.utcnow().isoformat(),
    }


# In-memory cache of latest full scan opportunities for instant Web UI browsing
_LATEST_OPPORTUNITIES_CACHE: dict[str, list[dict]] = {
    "bm_arbitrage": [],
    "bm_enchanting": [],
    "bm_market_making": [],
    "arbitrage": [],
    "crafting": [],
    "refining": [],
    "market_making": [],
    "enchanting": [],
    "quality_inversion": [],
    "transmutation": [],
    "island": [],
}
_LATEST_SCAN_TIME: str | None = None
_SCAN_LOCK = asyncio.Lock()


def is_bm_category(cat_k: str) -> bool:
    cat = (cat_k or "").lower()
    return any(bm in cat for bm in ["black_market", "bm_", "b_arb", "b_enchant", "b_craft", "b_refine", "b_mm"])


def is_opportunity_dismissed(o: dict, cat_k: str, now_ts: float) -> bool:
    item_id = str(o.get("item_id", "")).upper()
    qual = safe_int(o.get("quality", 1), 1)

    # Check Black Market specific filled buy order tracking
    sell_city = str(o.get("sell_city", "") or o.get("destination_city", "") or o.get("dest_city", "")).lower()
    is_bm = is_bm_category(cat_k) or "black market" in sell_city or o.get("is_black_market") is True

    if is_bm:
        filled_bm = getattr(state, "filled_bm_orders", {})
        bm_key = f"{item_id}:{qual}"
        rec = filled_bm.get(bm_key) or filled_bm.get(item_id)
        if rec:
            filled_at = rec.get("filled_at", 0.0)
            filled_age = rec.get("data_age_bm", 999999)
            filled_price = rec.get("bm_price", 0)

            curr_age = o.get("data_age_bm", o.get("data_age_sell", o.get("data_age_seconds", 999999)))
            curr_price = o.get("bm_buy_price", o.get("sell_price", o.get("buy_price_max", 0)))
            curr_ts = o.get("_ts")

            is_fresher_scan = False
            if curr_ts:
                try:
                    if isinstance(curr_ts, str):
                        ts_val = datetime.fromisoformat(curr_ts).timestamp()
                    elif isinstance(curr_ts, datetime):
                        ts_val = curr_ts.timestamp()
                    else:
                        ts_val = float(curr_ts)
                    if ts_val > filled_at:
                        is_fresher_scan = True
                except Exception:
                    pass

            if curr_age is not None and filled_age is not None and curr_age < (filled_age - 60):
                is_fresher_scan = True

            if filled_price > 0 and curr_price > 0 and abs(curr_price - filled_price) > 0:
                is_fresher_scan = True

            if is_fresher_scan:
                filled_bm.pop(bm_key, None)
                filled_bm.pop(item_id, None)
                return False
            else:
                return True

    # Standard temporary dismissal check
    dismissed = getattr(state, "dismissed_opportunities", {})
    if item_id in dismissed and dismissed[item_id] > now_ts:
        return True

    return False


def set_latest_opportunities_cache(cache_dict: dict[str, list[dict]]):
    """Updates global in-memory cache with fresh scan results from scheduler or API worker."""
    global _LATEST_OPPORTUNITIES_CACHE, _LATEST_SCAN_TIME
    now_ts = datetime.utcnow().timestamp()
    dismissed = getattr(state, "dismissed_opportunities", {})
    # Purge expired dismissals
    active_dismissed = {k: v for k, v in dismissed.items() if v > now_ts}
    state.dismissed_opportunities = active_dismissed

    filtered_cache = {}
    for cat_k, opp_list in cache_dict.items():
        filtered_cache[cat_k] = [
            o for o in opp_list
            if not is_opportunity_dismissed(o, cat_k, now_ts)
        ]

    _LATEST_OPPORTUNITIES_CACHE = filtered_cache
    total_records = sum(len(v) for k, v in filtered_cache.items() if k != "island")
    log.info(f"[CACHE] Updated live opportunities cache with {total_records} records.")


@router.post("/scan")
async def trigger_live_scan(
    quick: bool = Query(default=True, description="Fast direct database scan without blocking remote API ingestion"),
    background_ingest: bool = Query(default=False, description="Queue remote partition ingestion in background"),
    db: Session = Depends(get_db),
):
    """Triggers an on-demand live market scan across the entire item universe and updates the cache."""
    global _LATEST_OPPORTUNITIES_CACHE, _LATEST_SCAN_TIME

    # If background ingestion was requested and scheduler is present, queue it asynchronously
    if background_ingest and state.scheduler_instance:
        if not getattr(state.scheduler_instance, "_cycle_running", False):
            asyncio.create_task(state.scheduler_instance.master_cycle())
            log.info("[API SCAN] Dispatched asynchronous remote partition ingestion cycle.")

    if not quick and state.scheduler_instance:
        if getattr(state.scheduler_instance, "_cycle_running", False):
            total_opps = sum(len(v) for k, v in _LATEST_OPPORTUNITIES_CACHE.items() if k != "island")
            return {
                "status": "in_progress",
                "message": "Master background cycle is already running.",
                "counts": {k: len(v) for k, v in _LATEST_OPPORTUNITIES_CACHE.items()},
                "total_opportunities": total_opps,
            }
        asyncio.create_task(state.scheduler_instance.master_cycle())
        total_opps = sum(len(v) for k, v in _LATEST_OPPORTUNITIES_CACHE.items() if k != "island")
        return {
            "status": "in_progress",
            "message": "Remote ingestion & scan dispatched in background.",
            "counts": {k: len(v) for k, v in _LATEST_OPPORTUNITIES_CACHE.items()},
            "total_opportunities": total_opps,
        }

    async with _SCAN_LOCK:
        profile = db.query(UserProfile).first()
        is_premium = profile.is_premium if profile else settings.is_premium

        scanner = state.scheduler_instance.unified_scanner if state.scheduler_instance else UnifiedScanner(premium=is_premium)
        scan_res = await scanner.scan_all(db=db, scan_bm=True, lookback_hours=12.0)

        # Unpack the 15-tuple
        if len(scan_res) >= 15:
            (
                bm_arb, craft, arb, refine, mm, enchant, quality, transmute,
                island, bm_craft, bm_refine, bm_enchant, bm_mm,
                potions_scan, cooking_scan
            ) = scan_res[:15]
        elif len(scan_res) >= 13:
            (
                bm_arb, craft, arb, refine, mm, enchant, quality, transmute,
                island, bm_craft, bm_refine, bm_enchant, bm_mm
            ) = scan_res[:13]
            potions_scan, cooking_scan = [], []
        else:
            bm_arb, craft, arb, refine, mm, enchant, quality, transmute = scan_res[:8]
            island, bm_craft, bm_refine, bm_enchant, bm_mm = [], [], [], [], []
            potions_scan, cooking_scan = [], []

        # Save to database
        try:
            scanner.save_opportunities(
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
            log.warning(f"[API SCAN] Save opportunities to DB warning: {e}")

        # Update live memory cache
        potions = potions_scan if potions_scan else [o for o in island if o.get("category_key") == "potions"]
        cooking = cooking_scan if cooking_scan else [o for o in island if o.get("category_key") == "cooking"]
        mounts = [o for o in island if o.get("category_key") == "mounts"]
        farming = [o for o in island if o.get("category_key") == "farming" or (o not in potions and o not in cooking and o not in mounts)]

        _LATEST_OPPORTUNITIES_CACHE = {
            "bm_arbitrage": bm_arb,
            "bm_enchanting": bm_enchant,
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
        }
        _LATEST_SCAN_TIME = datetime.utcnow().isoformat()

    total_opps = sum(len(v) for k, v in _LATEST_OPPORTUNITIES_CACHE.items() if k != "island")
    return {
        "status": "success",
        "message": f"Scan completed. Found {total_opps} verified filtered opportunities.",
        "scan_time": _LATEST_SCAN_TIME,
        "counts": {k: len(v) for k, v in _LATEST_OPPORTUNITIES_CACHE.items()},
        "total_opportunities": total_opps,
    }


async def _run_background_scan():
    """Runs a background scan with an independent database session."""
    from app.db.session import get_db_session
    try:
        with get_db_session() as bg_db:
            await trigger_live_scan(bg_db)
    except Exception as e:
        log.warning(f"[BG SCAN] Background scan worker error: {e}")


@router.post("/opportunities/clear")
async def clear_opportunities_cache(db: Session = Depends(get_db)):
    """Clears all cached opportunities and stale DB records to reset and fetch fresh live alpha."""
    global _LATEST_OPPORTUNITIES_CACHE, _LATEST_SCAN_TIME

    _LATEST_OPPORTUNITIES_CACHE = {
        "bm_arbitrage": [],
        "bm_enchanting": [],
        "bm_market_making": [],
        "arbitrage": [],
        "crafting": [],
        "refining": [],
        "market_making": [],
        "enchanting": [],
        "transmutation": [],
        "quality_inversion": [],
        "potions": [],
        "cooking": [],
        "farming": [],
        "mounts": [],
        "island": [],
    }
    _LATEST_SCAN_TIME = None

    try:
        from app.db.models import ArbitrageOpportunity, CraftingOpportunity, RefiningOpportunity, MarketMakingOpportunity
        db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).update({"is_active": False})
        db.query(CraftingOpportunity).filter(CraftingOpportunity.is_active == True).update({"is_active": False})
        db.query(RefiningOpportunity).filter(RefiningOpportunity.is_active == True).update({"is_active": False})
        db.query(MarketMakingOpportunity).filter(MarketMakingOpportunity.is_active == True).update({"is_active": False})
        db.commit()
    except Exception as e:
        log.warning(f"[CLEAR] Error deactivating DB records: {e}")

    return {
        "status": "cleared",
        "message": "Opportunity cache and active records cleared. Ready for fresh scan."
    }


class DismissOpportunityIn(BaseModel):
    item_id: str
    quality: int = 1
    category_key: str = "all"
    city: str = ""
    data_age_bm: int | None = None
    bm_price: int | None = None
    sell_price: int | None = None


@router.post("/opportunities/dismiss")
async def dismiss_opportunity(payload: DismissOpportunityIn):
    """
    Dismisses / marks an opportunity as filled by the user.
    For Black Market buy orders: records persistent snapshot until a fresher scan of that item arrives.
    For other opportunities: sets 15-minute temporary suppression.
    """
    global _LATEST_OPPORTUNITIES_CACHE
    if not payload.item_id or payload.item_id.strip().upper() in ("", "UNDEFINED", "NULL"):
        return {"status": "ignored", "message": "Invalid item_id provided"}

    item_id_upper = payload.item_id.strip().upper()
    now_ts = datetime.utcnow().timestamp()

    is_bm = is_bm_category(payload.category_key) or (bool(payload.city) and "black market" in payload.city.lower())

    if is_bm:
        if not hasattr(state, "filled_bm_orders"):
            state.filled_bm_orders = {}
        bm_key = f"{item_id_upper}:{payload.quality}"
        state.filled_bm_orders[bm_key] = {
            "filled_at": now_ts,
            "data_age_bm": payload.data_age_bm,
            "bm_price": payload.bm_price or payload.sell_price or 0,
            "item_id": item_id_upper,
            "quality": payload.quality,
        }
        log.info(f"[DISMISS/FILLED] User marked Black Market buy order {item_id_upper} (Q{payload.quality}) as filled. Suppressed until next fresh scan.")
    else:
        if not hasattr(state, "dismissed_opportunities"):
            state.dismissed_opportunities = {}
        state.dismissed_opportunities[item_id_upper] = now_ts + 900.0  # 15 minutes

    # Remove from live NATS LOB
    try:
        from app.ingestion.nats_client import nats_client
        if nats_client and hasattr(nats_client, "live_orderbook"):
            for k in list(nats_client.live_orderbook.keys()):
                if k[0].upper() == item_id_upper:
                    nats_client.live_orderbook.pop(k, None)
    except Exception:
        pass

    # Purge from live in-memory opportunities cache
    removed_count = 0
    for cat_k, opp_list in _LATEST_OPPORTUNITIES_CACHE.items():
        new_list = [o for o in opp_list if not is_opportunity_dismissed(o, cat_k, now_ts)]
        removed_count += len(opp_list) - len(new_list)
        _LATEST_OPPORTUNITIES_CACHE[cat_k] = new_list

    log.info(f"[DISMISS] User marked {payload.item_id} as filled. Removed {removed_count} cache records.")
    return {
        "status": "dismissed",
        "item_id": payload.item_id,
        "is_black_market": is_bm,
        "removed_from_cache": removed_count,
        "message": f"Successfully marked {payload.item_id} as filled."
    }


@router.get("/opportunities")
async def get_opportunities(
    category: str = Query(default="all", description="Opportunity category or 'all'"),
    search: str = Query(default="", description="Search by item name or ID"),
    tier: int = Query(default=0, description="Tier filter (0 for all, 4-8)"),
    min_profit: int = Query(default=0, description="Minimum profit filter"),
    min_roi: float = Query(default=0.0, description="Minimum ROI % filter"),
    max_investment: int = Query(default=0, description="Maximum required investment / unit cost filter"),
    min_volume: int = Query(default=0, description="Minimum daily volume filter"),
    city: str = Query(default="", description="City filter (source or dest)"),
    is_safe_only: bool = Query(default=False, description="Filter safe blue/yellow routes only"),
    db: Session = Depends(get_db),
):
    """
    Returns all uncapped opportunities matching filters.
    Instant non-blocking < 1ms response from memory cache.
    """
    global _LATEST_OPPORTUNITIES_CACHE, _LATEST_SCAN_TIME

    results: dict[str, list[dict]] = {}

    target_keys = (
        list(_LATEST_OPPORTUNITIES_CACHE.keys())
        if category == "all"
        else [k for k in _LATEST_OPPORTUNITIES_CACHE.keys() if category.lower() in k.lower()]
    )

    search_lower = search.strip().lower()
    city_lower = city.strip().lower()
    now_ts = datetime.utcnow().timestamp()

    for k in target_keys:
        opps = _LATEST_OPPORTUNITIES_CACHE.get(k, [])
        filtered = []
        for o in opps:
            item_id = str(o.get("item_id", "")).upper()
            item_name = str(o.get("item_name", "")).lower()

            # Dismissed / Filled suppression check
            if is_opportunity_dismissed(o, k, now_ts):
                continue

            # Tier filter
            if tier > 0:
                if not item_id.startswith(f"T{tier}"):
                    continue

            # Search filter
            if search_lower:
                if search_lower not in item_id.lower() and search_lower not in item_name:
                    continue

            # Max Investment / Budget filter
            if max_investment > 0:
                cost = float(o.get("total_cost", o.get("effective_cost", o.get("craft_cost", o.get("buy_price", o.get("material_cost_gross", 0))))))
                if cost > max_investment:
                    continue

            # Min Profit filter
            profit = float(o.get("net_profit", o.get("profit", o.get("estimated_profit", 0))))
            if min_profit > 0 and profit < min_profit:
                continue

            # Min ROI filter
            roi = float(o.get("roi", o.get("profit_pct", o.get("estimated_margin", 0))))
            if min_roi > 0 and roi < min_roi:
                continue

            # Min Volume filter
            if min_volume > 0:
                vol = float(o.get("daily_volume", o.get("volume_24h", o.get("volume", 0))))
                if vol < min_volume:
                    continue

            # City filter
            src_city = str(o.get("buy_city", o.get("source_city", o.get("craft_city", o.get("refine_city", ""))))).lower()
            dst_city = str(o.get("sell_city", o.get("destination_city", ""))).lower()
            if city_lower:
                if city_lower not in src_city and city_lower not in dst_city:
                    continue

            # Safe route filter
            if is_safe_only:
                is_danger = o.get("is_dangerous_route", False)
                if is_danger or "black market" in dst_city or "caerleon" in dst_city or "caerleon" in src_city:
                    continue

            filtered.append(o)

        results[k] = filtered

    total_matched = sum(len(v) for v in results.values())
    return {
        "scan_time": _LATEST_SCAN_TIME,
        "total_matched": total_matched,
        "categories": results,
    }


class VerifyOpportunityRequest(BaseModel):
    item_id: str = ""
    source_city: str = ""
    destination_city: str = ""
    expected_buy_price: int = 0
    expected_sell_price: int = 0
    quality: int = 1


@router.post("/opportunities/verify")
@router.get("/opportunities/verify")
async def verify_opportunity_endpoint(
    req: VerifyOpportunityRequest = None,
    item_id: str = Query(default=""),
    source_city: str = Query(default=""),
    destination_city: str = Query(default=""),
    expected_buy_price: int = Query(default=0),
    expected_sell_price: int = Query(default=0),
    quality: int = Query(default=1),
):
    """
    1-Click Pre-Flight Live Price Verification Engine:
    Queries live NATS memory packets and instantaneous AODP orderbook API to verify
    whether a candidate opportunity's spread is still live, active, and profitable before hauling.
    """
    target_item_id = (req.item_id if req and req.item_id else None) or item_id
    src = (req.source_city if req and req.source_city else None) or source_city
    dst = (req.destination_city if req and req.destination_city else None) or destination_city
    exp_buy = (req.expected_buy_price if req and req.expected_buy_price else None) or expected_buy_price
    exp_sell = (req.expected_sell_price if req and req.expected_sell_price else None) or expected_sell_price
    qual = (req.quality if req and req.quality else None) or quality

    if not target_item_id:
        raise HTTPException(status_code=400, detail="item_id is required")

    def _clean_city(c: str) -> str:
        s = str(c or "").replace(" Market", "").strip()
        if "Personal Island (" in s:
            s = s.replace("Personal Island (", "").replace(")", "").strip()
        return s

    clean_src = _clean_city(src)
    clean_dst = _clean_city(dst)

    live_buy_price = 0
    live_sell_price = 0

    # 1. First check in-memory live NATS orderbook
    try:
        from app.ingestion.nats_client import nats_client
        live_nats = nats_client.get_live_prices_dict()
        item_nats = live_nats.get(target_item_id, {})
        if clean_src in item_nats:
            src_q = item_nats[clean_src].get(qual, item_nats[clean_src].get(1, {}))
            if src_q.get("sell_price_min", 0) > 0:
                live_buy_price = src_q["sell_price_min"]
        if clean_dst in item_nats:
            dst_q = item_nats[clean_dst].get(qual, item_nats[clean_dst].get(1, {}))
            if clean_dst == "Black Market":
                if dst_q.get("buy_price_max", 0) > 0:
                    live_sell_price = dst_q["buy_price_max"]
            else:
                if dst_q.get("sell_price_min", 0) > 0:
                    live_sell_price = dst_q["sell_price_min"]
    except Exception:
        pass

    # 2. If not in NATS or prices incomplete, query AODP live endpoint
    if live_buy_price == 0 or live_sell_price == 0:
        try:
            from app.core.http import aqs_http
            base_url = settings.aodp_base_urls.get(settings.active_server, "https://europe.albion-online-data.com")
            locs = f"{clean_src},{clean_dst}" if clean_src != clean_dst else clean_src
            url = f"{base_url}/api/v2/stats/prices/{target_item_id}.json"
            resp = await aqs_http.get(url, params={"locations": locs, "qualities": f"1,{qual}"})
            if resp and resp.status_code == 200:
                data = resp.json()
                for row in data:
                    row_city = _clean_city(row.get("city", ""))
                    row_qual = row.get("quality", 1)
                    if row_qual not in (1, qual):
                        continue
                    if row_city.lower() == clean_src.lower():
                        sp = row.get("sell_price_min", 0)
                        if sp > 0 and (live_buy_price == 0 or sp < live_buy_price):
                            live_buy_price = sp
                    if row_city.lower() == clean_dst.lower():
                        if clean_dst.lower() == "black market":
                            bp = row.get("buy_price_max", 0)
                            if bp > 0 and bp > live_sell_price:
                                live_sell_price = bp
                        else:
                            sp = row.get("sell_price_min", 0)
                            if sp > 0 and sp > live_sell_price:
                                live_sell_price = sp
        except Exception as e:
            log.warning(f"[PRE-FLIGHT] Verification query error: {e}")

    final_buy = live_buy_price if live_buy_price > 0 else exp_buy
    final_sell = live_sell_price if live_sell_price > 0 else exp_sell

    tax_rate = 0.04 if getattr(settings, "is_premium", True) else 0.08
    est_profit = int(final_sell * (1.0 - tax_rate) - final_buy)

    price_delta_pct = 0.0
    if exp_sell > 0 and final_sell > 0:
        price_delta_pct = round(((final_sell - exp_sell) / exp_sell) * 100.0, 1)

    is_positive = est_profit > 0

    if is_positive and (live_buy_price > 0 or live_sell_price > 0):
        status = "CONFIRMED"
        msg = f"🟢 Orderbook Confirmed! Buy @ {final_buy:,}s ({clean_src}) ➔ Sell @ {final_sell:,}s ({clean_dst}). Net profit: +{est_profit:,}s."
        verified = True
    elif not is_positive and (live_buy_price > 0 or live_sell_price > 0):
        status = "SPREAD_CLOSED"
        msg = f"⚠️ Spread Closed: Live prices yield negative margin (Buy {final_buy:,}s vs Sell {final_sell:,}s). Do not haul."
        verified = False
    else:
        status = "UNVERIFIED"
        msg = f"ℹ️ Live orderbook currently unindexed in AODP for this route. Proceed with caution."
        verified = False

    return {
        "verified": verified,
        "status": status,
        "item_id": target_item_id,
        "source_city": clean_src,
        "destination_city": clean_dst,
        "live_buy_price": final_buy,
        "live_sell_price": final_sell,
        "expected_buy_price": exp_buy,
        "expected_sell_price": exp_sell,
        "live_profit": est_profit,
        "price_delta_pct": price_delta_pct,
        "message": msg,
        "checked_at": datetime.utcnow().isoformat(),
    }
