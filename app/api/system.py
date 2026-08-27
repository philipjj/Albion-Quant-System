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


@router.get("/settings")
async def get_system_settings(db: Session = Depends(get_db)):
    """Retrieve full live system settings, alert toggles, and engine status."""
    profile = db.query(UserProfile).first()
    is_premium = profile.is_premium if profile else settings.is_premium

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

    return await get_system_settings(db)


@router.post("/stop")
async def stop_system(db: Session = Depends(get_db)):
    """Stops any active background scanning cycles and places the engine in standby mode."""
    log.info("[SYSTEM] Stopping background scanning and setting standby mode.")
    state.standby_mode = True
    if state.scheduler_instance and state.scheduler_instance._is_running:
        state.scheduler_instance.stop()
    return await get_system_settings(db)


@router.post("/clear")
@router.post("/opportunities/clear")
async def clear_stale_data(db: Session = Depends(get_db)):
    """
    Intelligently purges stale quotes (>24h) and duplicate snapshots,
    while preserving high-value Black Market buy orders (>= 500k silver) up to 7 days old.
    """
    log.info("[SYSTEM] Web UI requested intelligent stale quote purge...")
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

    # Clear in-memory opportunity cache
    try:
        from app.api.opportunities import _cached_opportunities
        _cached_opportunities.clear()
    except Exception:
        pass

    total_remaining = db.execute(text("SELECT COUNT(*) FROM market_prices")).scalar() or 0
    log.info(f"[SYSTEM] Purged {res_mp.rowcount} stale records. Active quotes remaining: {total_remaining}")
    return {
        "status": "cleared",
        "purged_records": res_mp.rowcount,
        "remaining_records": total_remaining,
        "message": f"Successfully purged {res_mp.rowcount:,} stale quotes. High-value BM orders preserved.",
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


@router.get("/stats")
async def get_system_stats(db: Session = Depends(get_db)):

    """Summary statistics for the Web UI dashboard."""
    item_count = db.query(func.count(Item.item_id)).scalar() or 0
    price_count = db.query(func.count(MarketPrice.id)).scalar() or 0

    recent_price_count = (
        db.query(func.count(MarketPrice.id))
        .filter(MarketPrice.server == settings.active_server.value)
        .scalar()
        or 0
    )

    arb_count = (
        db.query(func.count(ArbitrageOpportunity.id))
        .filter(ArbitrageOpportunity.is_active == True)
        .scalar()
        or 0
    )
    craft_count = (
        db.query(func.count(CraftingOpportunity.id))
        .filter(CraftingOpportunity.is_active == True)
        .scalar()
        or 0
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
        "standby_mode": state.standby_mode,
        "timestamp": datetime.utcnow().isoformat(),
    }


# In-memory cache of latest full scan opportunities for instant Web UI browsing
_LATEST_OPPORTUNITIES_CACHE: dict[str, list[dict]] = {
    "bm_arbitrage": [],
    "arbitrage": [],
    "crafting": [],
    "refining": [],
    "market_making": [],
    "enchanting": [],
    "quality_inversion": [],
    "transmutation": [],
    "island": [],
    "caerleon_crafting": [],
    "caerleon_refining": [],
    "caerleon_enchanting": [],
    "caerleon_market_making": [],
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
    _LATEST_SCAN_TIME = datetime.utcnow().isoformat()
    log.info(f"[CACHE] Updated live opportunities cache with {sum(len(v) for v in filtered_cache.values())} records.")


@router.post("/scan")
async def trigger_live_scan(db: Session = Depends(get_db)):
    """Triggers an on-demand live market scan across the entire item universe and updates the cache."""
    global _LATEST_OPPORTUNITIES_CACHE, _LATEST_SCAN_TIME

    async with _SCAN_LOCK:
        if state.scheduler_instance:
            log.info("[API SCAN] Executing partition cycle ingestion and filtered universe scan...")
            await state.scheduler_instance.master_cycle()
        else:
            profile = db.query(UserProfile).first()
            is_premium = profile.is_premium if profile else settings.is_premium

            scanner = UnifiedScanner(premium=is_premium)
            scan_res = await scanner.scan_all(db=db, scan_bm=True, lookback_hours=12.0)

            # Unpack the 13-tuple
            if len(scan_res) >= 13:
                (
                    bm_arb, craft, arb, refine, mm, enchant, quality, transmute,
                    island, bm_craft, bm_refine, bm_enchant, bm_mm
                ) = scan_res[:13]
            else:
                bm_arb, craft, arb, refine, mm, enchant, quality, transmute = scan_res[:8]
                island, bm_craft, bm_refine, bm_enchant, bm_mm = [], [], [], [], []

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
            potions = [o for o in island if o.get("category_key") == "potions"]
            cooking = [o for o in island if o.get("category_key") == "cooking"]
            mounts = [o for o in island if o.get("category_key") == "mounts"]
            farming = [o for o in island if o.get("category_key") == "farming" or (o not in potions and o not in cooking and o not in mounts)]

            _LATEST_OPPORTUNITIES_CACHE = {
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
            }
            _LATEST_SCAN_TIME = datetime.utcnow().isoformat()

        total_opps = sum(len(v) for v in _LATEST_OPPORTUNITIES_CACHE.values())
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
        "bm_crafting": [],
        "bm_enchanting": [],
        "bm_refining": [],
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
    item_id_upper = payload.item_id.upper()
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
