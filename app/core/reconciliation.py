"""
Stateful Opportunity Reconciliation & Orderbook Delta Fill Engine
================================================================
Tracks opportunity lifecycles across scan sweeps, detects Black Market buy order
fulfillment via orderbook deltas, and prevents premature eviction of valid active alerts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session

from app.core import state
from app.core.config import settings
from app.core.logging import log
from app.core.opportunity_engine import get_max_allowed_bm_age_seconds
from app.db.models import MarketPrice


def get_opportunity_key(o: dict[str, Any], category_key: str = "") -> str:
    """Computes a deterministic unique key for an opportunity across scans."""
    item_id = str(o.get("target_item_id") or o.get("item_id") or "").strip().upper()
    src = str(o.get("craft_city") or o.get("buy_city") or o.get("source_city") or o.get("base_city") or "").strip().lower()
    dst = str(o.get("sell_city") or o.get("destination_city") or "").strip().lower()
    q = str(o.get("quality") or o.get("order_quality") or o.get("buy_quality") or 1)
    cat = str(category_key or o.get("category_key") or o.get("type") or "").strip().lower()
    return f"{cat}:{item_id}:{src}:{dst}:{q}"


def check_bm_order_fulfillment(
    item_id: str,
    target_quality: int,
    recorded_buy_price: int,
    alert_detected_at: datetime | float | str | None,
    db: Session | None,
    server: str,
) -> tuple[bool, str, int]:
    """
    Checks whether a Black Market buy order has been filled in game.
    Returns: (is_filled, reason, current_bm_price)
    """
    if db is None or recorded_buy_price <= 0:
        return False, "no_db_session", recorded_buy_price

    # Parse alert detection timestamp
    alert_ts = 0.0
    if isinstance(alert_detected_at, (int, float)):
        alert_ts = float(alert_detected_at)
    elif isinstance(alert_detected_at, datetime):
        alert_ts = alert_detected_at.timestamp()
    elif isinstance(alert_detected_at, str):
        try:
            alert_ts = datetime.fromisoformat(alert_detected_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            alert_ts = 0.0

    try:
        # Fetch the freshest Black Market observation in the database for this item and quality
        latest_row = (
            db.query(
                MarketPrice.buy_price_max,
                MarketPrice.captured_at,
                MarketPrice.data_age_seconds,
            )
            .filter(
                MarketPrice.item_id == item_id,
                MarketPrice.city == "Black Market",
                MarketPrice.quality == target_quality,
                MarketPrice.server == server,
            )
            .order_by(MarketPrice.captured_at.desc())
            .first()
        )

        if not latest_row:
            return False, "no_market_record", recorded_buy_price

        current_bp = int(latest_row.buy_price_max or 0)
        captured_at = latest_row.captured_at

        cap_ts = 0.0
        if isinstance(captured_at, datetime):
            cap_ts = captured_at.timestamp()
        elif isinstance(captured_at, str):
            try:
                cap_ts = datetime.fromisoformat(captured_at).timestamp()
            except Exception:
                cap_ts = 0.0

        # Check if fresher Black Market data arrived AFTER the alert was recorded
        is_fresher_snapshot = (cap_ts > (alert_ts + 5.0)) if alert_ts > 0 else False

        if is_fresher_snapshot:
            # If the buy order dropped below recorded buy price, or dropped to 0, it was FILLED!
            if current_bp < recorded_buy_price or current_bp == 0:
                log.info(
                    f"🎯 [FILL DETECTED] {item_id} (Q{target_quality}) at Black Market was FILLED! "
                    f"(Recorded bid: {recorded_buy_price:,}s -> Current bid: {current_bp:,}s)"
                )
                return True, "order_eaten_or_cleared", current_bp
            else:
                # Order still active (or ticked up!)
                return False, "order_reconfirmed_active", current_bp

        # No fresher snapshot has arrived yet; order is presumed still waiting in game
        return False, "awaiting_fresher_snapshot", recorded_buy_price

    except Exception as e:
        log.warning(f"[RECONCILIATION] Error checking BM order fulfillment for {item_id}: {e}")
        return False, f"error_{e}", recorded_buy_price


def reconcile_opportunities_cache(
    existing_cache: dict[str, list[dict[str, Any]]],
    incoming_cache: dict[str, list[dict[str, Any]]],
    db: Session | None = None,
    server: str = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Stateful Reconciling Merge:
    1. Keeps unfulfilled valid opportunities alive across scans instead of purging them.
    2. Detects filled Black Market buy orders from orderbook deltas and cleans them up.
    3. Seamlessly updates incoming fresh opportunities and preserves still-valid previous alerts.
    """
    if server is None:
        server = settings.active_server.value

    now_utc = datetime.utcnow()
    now_ts = now_utc.timestamp()

    from app.api.system import is_opportunity_dismissed

    reconciled_cache: dict[str, list[dict[str, Any]]] = {}
    all_categories = set(list(existing_cache.keys()) + list(incoming_cache.keys()))

    total_retained = 0
    total_evicted_filled = 0
    total_evicted_stale = 0

    for cat_key in all_categories:
        existing_list = existing_cache.get(cat_key, [])
        incoming_list = incoming_cache.get(cat_key, [])

        merged_map: dict[str, dict[str, Any]] = {}

        # 1. Index incoming fresh items
        incoming_keys = set()
        for opp in incoming_list:
            key = get_opportunity_key(opp, cat_key)
            opp["lifecycle_status"] = "fresh"
            opp["last_verified_at"] = now_utc.isoformat()
            merged_map[key] = opp
            incoming_keys.add(key)

        # 2. Reconcile existing items
        for old_opp in existing_list:
            key = get_opportunity_key(old_opp, cat_key)

            # If already refreshed and present in incoming, incoming takes precedence
            if key in incoming_keys:
                continue

            # Check if user marked this opportunity as filled
            if is_opportunity_dismissed(old_opp, cat_key, now_ts):
                continue

            item_id = str(old_opp.get("target_item_id") or old_opp.get("item_id") or "").strip().upper()
            dst_city = str(old_opp.get("sell_city") or old_opp.get("destination_city") or "")
            quality = int(old_opp.get("quality") or old_opp.get("order_quality") or 1)
            is_bm = (
                dst_city.lower() == "black market"
                or "black market" in dst_city.lower()
                or cat_key.startswith("bm_")
            )

            # Check age against tier retention ceiling
            cost = float(old_opp.get("buy_price", 0) or old_opp.get("craft_cost", 0) or old_opp.get("total_cost", 0))
            sell_price = float(old_opp.get("sell_price", 0) or old_opp.get("bm_buy_price", 0))

            if is_bm:
                max_retention_sec = get_max_allowed_bm_age_seconds(item_id, sell_price)
            else:
                max_retention_sec = 86_400  # 24 hours for RoyalContinent

            # Estimate total age since first detection
            detected_at = old_opp.get("detected_at")
            age_sec = 0.0
            if detected_at:
                try:
                    det_dt = datetime.fromisoformat(str(detected_at).replace("Z", "+00:00"))
                    age_sec = (now_utc - det_dt.replace(tzinfo=None)).total_seconds()
                except Exception:
                    age_sec = 0.0

            if age_sec > max_retention_sec:
                total_evicted_stale += 1
                log.debug(f"[RECONCILIATION] Stale eviction: {item_id} (Age: {int(age_sec)}s > Max: {max_retention_sec}s)")
                continue

            # Orderbook Delta Fill Detection for Black Market opportunities
            if is_bm and sell_price > 0:
                is_filled, reason, current_price = check_bm_order_fulfillment(
                    item_id=item_id,
                    target_quality=quality,
                    recorded_buy_price=int(sell_price),
                    alert_detected_at=detected_at,
                    db=db,
                    server=server,
                )

                if is_filled:
                    total_evicted_filled += 1
                    # Record into state.filled_bm_orders so user dismissal suppression also stays in sync
                    if not hasattr(state, "filled_bm_orders"):
                        state.filled_bm_orders = {}
                    bm_suppress_key = f"{item_id}:{quality}"
                    state.filled_bm_orders[bm_suppress_key] = {
                        "filled_at": now_ts,
                        "data_age_bm": 0,
                        "bm_price": sell_price,
                        "item_id": item_id,
                        "quality": quality,
                    }
                    continue  # EVICTED: Buy order fulfilled in game!

            # The opportunity is STILL VALID and UNFILLED — PRESERVE IT!
            old_opp["lifecycle_status"] = "reconfirmed"
            old_opp["is_persisted_alert"] = True
            merged_map[key] = old_opp
            total_retained += 1

        reconciled_list = list(merged_map.values())
        reconciled_list.sort(
            key=lambda x: x.get("score", x.get("ev_score", x.get("net_profit", x.get("profit", 0)))),
            reverse=True,
        )
        reconciled_cache[cat_key] = reconciled_list

    log.info(
        f"🔄 [RECONCILIATION] Complete: Retained {total_retained} active unfilled opportunities | "
        f"Evicted {total_evicted_filled} filled orders | Evicted {total_evicted_stale} stale orders."
    )
    return reconciled_cache
