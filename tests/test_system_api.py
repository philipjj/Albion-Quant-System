"""
Unit tests for System API, Discord Alerts Toggle, and Web Dashboard Endpoints.
"""

from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from main import app
from app.core import state
from app.core.config import settings
from app.alerts.discord import DiscordAlerter


@pytest.fixture
def client():
    return TestClient(app)


def test_get_system_settings(client):
    """Verify GET /api/v1/system/settings returns expected fields."""
    resp = client.get("/api/v1/system/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "discord_alerts_enabled" in data
    assert "active_server" in data
    assert "tax_rate" in data
    assert "setup_fee" in data


def test_post_system_settings_toggle_discord_alerts(client):
    """Verify POST /api/v1/system/settings dynamically toggles Discord alerts."""
    # 1. Toggle OFF
    resp = client.post("/api/v1/system/settings", json={"discord_alerts_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["discord_alerts_enabled"] is False
    assert state.discord_alerts_enabled is False

    # 2. Toggle ON
    resp = client.post("/api/v1/system/settings", json={"discord_alerts_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["discord_alerts_enabled"] is True
    assert state.discord_alerts_enabled is True


def test_discord_alerts_suppression_when_disabled():
    """Verify Discord webhook alert is suppressed when discord_alerts_enabled is False."""
    alerter = DiscordAlerter()
    alerter.webhook_url = "https://discord.com/api/webhooks/dummy/dummy"

    # When enabled -> attempts to send (would fail with network/invalid webhook, but not bypassed)
    state.discord_alerts_enabled = False
    # Dispatch batch alerts
    res = alerter.send_batch_alerts(arb_opps=[{"item_id": "T4_BAG", "profit": 5000}])
    # Should return empty dict immediately without attempting network calls
    import asyncio
    out = asyncio.run(res)
    assert out == {}

    # Restore
    state.discord_alerts_enabled = True


def test_get_system_stats(client):
    """Verify GET /api/v1/system/stats returns database and LOB stats."""
    resp = client.get("/api/v1/system/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "items_in_database" in data
    assert "price_records_total" in data
    assert "active_server" in data
    assert "discord_alerts_enabled" in data


def test_web_dashboard_html_served(client):
    """Verify root / with text/html and /dashboard serve the HTML web dashboard."""
    resp = client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "ALBION QUANT" in resp.text
    assert "Discord Alerts" in resp.text

    resp2 = client.get("/dashboard")
    assert resp2.status_code == 200
    assert "text/html" in resp2.headers.get("content-type", "")
    assert "ALBION QUANT" in resp2.text


def test_post_system_opportunities_dismiss_bm_and_fresh_scan_unsuppression(client):
    """Verify POST /api/v1/system/opportunities/dismiss tracks BM filled buy orders and un-suppresses when fresh scan arrives."""
    from app.api.system import set_latest_opportunities_cache, is_opportunity_dismissed
    from app.core import state

    # Initial state with BM opportunity
    set_latest_opportunities_cache({
        "bm_enchanting": [{"item_id": "T6_MAIN_DAGGER@2", "quality": 1, "data_age_bm": 3600, "bm_buy_price": 50000}],
        "arbitrage": [{"item_id": "T4_BAG", "quality": 1, "sell_price": 2000}],
    })

    # Dismiss Black Market opportunity
    resp = client.post(
        "/api/v1/system/opportunities/dismiss",
        json={
            "item_id": "T6_MAIN_DAGGER@2",
            "category_key": "bm_enchanting",
            "quality": 1,
            "data_age_bm": 3600,
            "bm_price": 50000,
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "dismissed"
    assert data["is_black_market"] is True
    assert data["removed_from_cache"] == 1

    # Verify tracked in state.filled_bm_orders
    bm_key = "T6_MAIN_DAGGER@2:1"
    assert bm_key in state.filled_bm_orders

    # Verify that a stale scan with the same or older data age remains suppressed
    stale_opp = {"item_id": "T6_MAIN_DAGGER@2", "quality": 1, "data_age_bm": 3650, "bm_buy_price": 50000}
    now_ts = datetime.utcnow().timestamp()
    assert is_opportunity_dismissed(stale_opp, "bm_enchanting", now_ts) is True

    # Verify that a FRESH scan (data_age_bm = 300s, newer scan) unsuppresses the opportunity
    fresh_opp = {"item_id": "T6_MAIN_DAGGER@2", "quality": 1, "data_age_bm": 300, "bm_buy_price": 52000}
    assert is_opportunity_dismissed(fresh_opp, "bm_enchanting", now_ts) is False

    # Dismiss Royal opportunity (standard 15m)
    resp_royal = client.post(
        "/api/v1/system/opportunities/dismiss",
        json={"item_id": "T4_BAG", "category_key": "arbitrage"}
    )
    assert resp_royal.status_code == 200
    assert "T4_BAG" in state.dismissed_opportunities


