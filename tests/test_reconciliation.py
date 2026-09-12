import pytest
from datetime import datetime, timedelta
from app.core.reconciliation import (
    reconcile_opportunities_cache,
    check_bm_order_fulfillment,
    get_opportunity_key,
)
from app.db.session import get_db_session
from app.db.models import MarketPrice
from app.core.config import settings

def test_opportunity_key():
    opp = {
        "target_item_id": "T6_MAIN_DAGGER_HELL@1",
        "base_city": "Caerleon",
        "sell_city": "Black Market",
        "quality": 1,
    }
    key = get_opportunity_key(opp, "bm_enchanting")
    assert key == "bm_enchanting:T6_MAIN_DAGGER_HELL@1:caerleon:black market:1"

def test_unfilled_opportunity_persistence():
    """Verify that an unfilled Black Market alert persists across scans when not re-scanned."""
    demonfang_opp = {
        "item_id": "T6_MAIN_DAGGER_HELL@1",
        "target_item_id": "T6_MAIN_DAGGER_HELL@1",
        "item_name": "Master's Demonfang .1",
        "source_city": "Caerleon",
        "destination_city": "Black Market",
        "sell_city": "Black Market",
        "base_city": "Caerleon",
        "bm_buy_price": 247475,
        "sell_price": 247475,
        "total_cost": 195304,
        "net_profit": 42272,
        "profit": 42272,
        "estimated_profit": 42272,
        "roi": 21.64,
        "score": 7264,
        "quality": 1,
        "category_key": "bm_enchanting",
        "detected_at": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
    }

    existing_cache = {"bm_enchanting": [demonfang_opp]}
    # Second scan returns other items, but NOT Demonfang
    other_opp = {
        "item_id": "T8_SHOES_PLATE_SET1@2",
        "target_item_id": "T8_SHOES_PLATE_SET1@2",
        "item_name": "Elder's Soldier Boots .2",
        "source_city": "Caerleon",
        "destination_city": "Black Market",
        "sell_city": "Black Market",
        "bm_buy_price": 1500000,
        "sell_price": 1500000,
        "total_cost": 1320000,
        "net_profit": 52300,
        "profit": 52300,
        "estimated_profit": 52300,
        "roi": 3.95,
        "score": 19235,
        "quality": 1,
        "category_key": "bm_enchanting",
        "detected_at": datetime.utcnow().isoformat(),
    }
    incoming_cache = {"bm_enchanting": [other_opp]}

    reconciled = reconcile_opportunities_cache(
        existing_cache=existing_cache,
        incoming_cache=incoming_cache,
        db=None,
        server=settings.active_server.value,
    )

    bm_list = reconciled.get("bm_enchanting", [])
    item_ids = [o.get("target_item_id") for o in bm_list]
    
    # Both items must be present! Demonfang was not dropped!
    assert "T6_MAIN_DAGGER_HELL@1" in item_ids
    assert "T8_SHOES_PLATE_SET1@2" in item_ids

    # Find Demonfang in reconciled list
    df = next(o for o in bm_list if o.get("target_item_id") == "T6_MAIN_DAGGER_HELL@1")
    assert df["is_persisted_alert"] is True
    assert df["lifecycle_status"] == "reconfirmed"

def test_fill_detection_via_orderbook_delta():
    """Verify that if a fresher snapshot shows the Black Market buy order dropped, it is evicted as FILLED."""
    now = datetime.utcnow()
    with get_db_session() as db:
        # Insert test price record simulating fresh observation showing order was eaten (price dropped to 100k)
        test_price = MarketPrice(
            item_id="TEST_FILL_ITEM@1",
            city="Black Market",
            quality=1,
            sell_price_min=0,
            buy_price_max=100000,
            data_age_seconds=30,
            captured_at=now,
            server=settings.active_server.value,
        )
        db.merge(test_price)
        db.commit()

        # Existing alert had recorded buy price of 250,000 captured 10 minutes ago
        alert_detected_at = now - timedelta(minutes=10)
        is_filled, reason, curr_price = check_bm_order_fulfillment(
            item_id="TEST_FILL_ITEM@1",
            target_quality=1,
            recorded_buy_price=250000,
            alert_detected_at=alert_detected_at,
            db=db,
            server=settings.active_server.value,
        )

        assert is_filled is True
        assert reason == "order_eaten_or_cleared"
        assert curr_price == 100000

        # Clean up test row
        db.query(MarketPrice).filter(MarketPrice.item_id == "TEST_FILL_ITEM@1").delete()
        db.commit()

def test_still_active_if_no_fresher_snapshot():
    """Verify that if no newer snapshot exists, the order is NOT falsely flagged as filled."""
    now = datetime.utcnow()
    with get_db_session() as db:
        # Snapshot was captured at the same time as the alert
        test_price = MarketPrice(
            item_id="TEST_ACTIVE_ITEM@1",
            city="Black Market",
            quality=1,
            sell_price_min=0,
            buy_price_max=250000,
            data_age_seconds=600,
            captured_at=now,
            server=settings.active_server.value,
        )
        db.merge(test_price)
        db.commit()

        # Alert detected right now (same snapshot)
        is_filled, reason, curr_price = check_bm_order_fulfillment(
            item_id="TEST_ACTIVE_ITEM@1",
            target_quality=1,
            recorded_buy_price=250000,
            alert_detected_at=now,
            db=db,
            server=settings.active_server.value,
        )

        assert is_filled is False
        assert reason == "awaiting_fresher_snapshot"

        # Clean up test row
        db.query(MarketPrice).filter(MarketPrice.item_id == "TEST_ACTIVE_ITEM@1").delete()
        db.commit()
