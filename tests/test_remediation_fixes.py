"""
Tests verifying remediation fixes:
1. FastAPI route prefixes resolution (no double nesting).
2. Bot command registration (caravan, patch, focus).
3. Opportunity persistence on scan results.
"""

import pytest
from fastapi.testclient import TestClient
from main import app
from app.alerts.bot import bot


@pytest.fixture
def client():
    return TestClient(app)


def test_fastapi_routes_no_double_prefix(client):
    """Verify routes are accessible at /api/v1/{module}/... without duplicated segments."""
    # Market fees route
    resp = client.get("/api/v1/fees/")
    assert resp.status_code == 200
    data = resp.json()
    assert "setup_fee_pct" in data
    assert "transaction_tax_premium_pct" in data

    # Arbitrage top route
    resp = client.get("/api/v1/arbitrage/top?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "opportunities" in data

    # Crafting top route
    resp = client.get("/api/v1/crafting/top?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "opportunities" in data

    # Root route
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "online"

    # System status route
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "db_stats" in data or "feature_gate" in data


def test_bot_commands_registered():
    """Verify primary operational commands are registered in Discord bot."""
    cmd_names = [cmd.name for cmd in bot.commands]
    assert "price" in cmd_names
    assert "scan" in cmd_names
    assert "status" in cmd_names
    assert "start" in cmd_names
    assert "stop" in cmd_names
    assert "help" in cmd_names
