import pytest
from app.alerts.discord import DiscordAlerter
from app.core import state
from app.core.opportunity_engine import OpportunityScanner
import httpx


def test_discord_alerter_persistent_client():
    """Verify DiscordAlerter initializes with connection pooling, robust timeouts, and compliant User-Agent."""
    alerter = DiscordAlerter()
    client = alerter._get_client()
    assert isinstance(client, httpx.AsyncClient)
    assert client.timeout.connect == 15.0
    assert client.timeout.read == 25.0
    assert client.timeout.pool == 15.0
    assert "DiscordBot" in client.headers.get("User-Agent", "")
    assert client.headers.get("Content-Type") == "application/json"
    # Calling again returns same client instance
    assert alerter._get_client() is client


@pytest.mark.asyncio
async def test_shared_webhook_no_starvation():
    """Verify that multiple categories sharing the same fallback webhook URL do not starve each other."""
    from unittest.mock import AsyncMock, patch

    alerter = DiscordAlerter()
    alerter.enabled = True
    shared_url = "https://discord.com/api/webhooks/shared/fallback"
    alerter.webhook_url = shared_url
    alerter.crafting_webhook_url = ""
    alerter.refining_webhook_url = ""
    alerter.enchanting_webhook_url = ""

    craft_opps = [{"item_id": "T4_BAG", "crafting_city": "Martlock", "sell_city": "Bridgewatch", "category": "Equipment", "profit": 5000}]
    refine_opps = [{"item_id": "T4_PLANKS", "crafting_city": "Fort Sterling", "sell_city": "Lymhurst", "profit": 3000}]
    enchant_opps = [{"item_id": "T4_BAG@1", "base_city": "Thetford", "destination_city": "Thetford", "profit": 4000}]

    with patch.object(alerter, "_send_webhook", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        await alerter.send_batch_alerts(
            craft_opps=craft_opps,
            refine_opps=refine_opps,
            enchant_opps=enchant_opps,
            max_per_channel=10,
        )

        # All 3 categories should have been sent to the shared webhook URL without getting starved
        assert mock_send.call_count == 3
        urls = [c.kwargs.get("webhook_url") for c in mock_send.call_args_list]
        assert all(u == shared_url for u in urls)


def test_single_city_crafting_sourcing():
    """Verify that when crafting_local_sourcing_only is True, items with missing local ingredients are rejected."""
    scanner = OpportunityScanner(crafting_local_sourcing_only=True)
    state.crafting_local_sourcing_only = True

    recipe = {
        "item_id": "T4_BAG",
        "ingredients": [
            {"item_id": "T4_CLOTH", "quantity": 8},
            {"item_id": "T4_LEATHER", "quantity": 8},
        ],
    }

    # Prices where T4_CLOTH exists in Martlock, but T4_LEATHER is missing in Martlock and only exists in Lymhurst
    prices = {
        "T4_CLOTH": {
            "Martlock": {1: {"sell_price_min": 500, "buy_price_max": 450, "data_age_seconds": 10, "volume_24h": 100}}
        },
        "T4_LEATHER": {
            "Lymhurst": {1: {"sell_price_min": 600, "buy_price_max": 550, "data_age_seconds": 10, "volume_24h": 100}}
        },
    }

    # Under strict local sourcing (Martlock), this craft should fail because T4_LEATHER is not in Martlock
    cost, ings, age = scanner._calc_material_cost("T4_BAG", recipe, prices, "Martlock", 1)
    assert cost == 0.0
    assert len(ings) == 0

    # If both ingredients exist locally in Martlock, it succeeds
    prices["T4_LEATHER"]["Martlock"] = {1: {"sell_price_min": 650, "buy_price_max": 600, "data_age_seconds": 10, "volume_24h": 100}}
    cost, ings, age = scanner._calc_material_cost("T4_BAG", recipe, prices, "Martlock", 1)
    assert cost > 0.0
    assert len(ings) == 2
    assert all(ing["buy_city"] == "Martlock" for ing in ings)


def test_multi_city_sourcing_fallback_when_disabled():
    """Verify fallback ladder works when local_only is explicitly False."""
    scanner = OpportunityScanner(crafting_local_sourcing_only=False)
    state.crafting_local_sourcing_only = False

    recipe = {
        "item_id": "T4_BAG",
        "ingredients": [
            {"item_id": "T4_CLOTH", "quantity": 8},
            {"item_id": "T4_LEATHER", "quantity": 8},
        ],
    }

    prices = {
        "T4_CLOTH": {
            "Martlock": {1: {"sell_price_min": 500, "buy_price_max": 450, "data_age_seconds": 10, "volume_24h": 100}}
        },
        "T4_LEATHER": {
            "Lymhurst": {1: {"sell_price_min": 600, "buy_price_max": 550, "data_age_seconds": 10, "volume_24h": 100}}
        },
    }

    cost, ings, age = scanner._calc_material_cost("T4_BAG", recipe, prices, "Martlock", 1)
    assert cost > 0.0
    assert len(ings) == 2
    cities = {ing["buy_city"] for ing in ings}
    assert "Martlock" in cities
    assert "Lymhurst" in cities

    # Reset state
    state.crafting_local_sourcing_only = True


def test_refining_single_city_sourcing_and_max_2_cities():
    """Verify refining enforces all ingredients from one single city and max 2 unique cities in route."""
    scanner = OpportunityScanner()
    recipes = {
        "T5_CLOTH": {
            "item_id": "T5_CLOTH",
            "ingredients": [
                {"item_id": "T5_FIBER", "quantity": 3},
                {"item_id": "T4_CLOTH", "quantity": 1},
            ],
        }
    }
    # T5_FIBER is in Bridgewatch and Lymhurst
    # T4_CLOTH is in Thetford and Lymhurst
    # If single-city sourcing is enforced, Bridgewatch (missing T4_CLOTH) and Thetford (missing T5_FIBER) cannot be mixed!
    # Only Lymhurst (where both exist) can form a valid opportunity.
    prices = {
        "T5_FIBER": {
            "Bridgewatch": {1: {"sell_price_min": 100, "buy_price_max": 90, "data_age_seconds": 10, "volume_24h": 1000}},
            "Lymhurst": {1: {"sell_price_min": 120, "buy_price_max": 110, "data_age_seconds": 10, "volume_24h": 1000}},
        },
        "T4_CLOTH": {
            "Thetford": {1: {"sell_price_min": 150, "buy_price_max": 140, "data_age_seconds": 10, "volume_24h": 1000}},
            "Lymhurst": {1: {"sell_price_min": 160, "buy_price_max": 150, "data_age_seconds": 10, "volume_24h": 1000}},
        },
        "T5_CLOTH": {
            "Lymhurst": {1: {"sell_price_min": 800, "buy_price_max": 750, "data_age_seconds": 10, "volume_24h": 500}},
            "Martlock": {1: {"sell_price_min": 850, "buy_price_max": 800, "data_age_seconds": 10, "volume_24h": 500}},
        },
    }
    names = {"T5_CLOTH": "Fine Cloth", "T5_FIBER": "Hemp", "T4_CLOTH": "Neat Cloth"}
    categories = {"T5_CLOTH": "cloth"}
    values = {"T5_CLOTH": 100.0}
    weights = {"T5_CLOTH": 1.0}

    opps = scanner.scan_refining(prices, names, recipes, categories, values, weights)
    assert len(opps) > 0
    opp = opps[0]

    # Verify all ingredients in the opportunity came from ONE single buy city (Lymhurst)
    assert len(opp.ingredients) == 2
    buy_cities = {ing["buy_city"] for ing in opp.ingredients}
    assert len(buy_cities) == 1
    assert "Lymhurst" in buy_cities

    # Verify total unique cities in route is at most 2
    route_cities = {opp.buy_city, opp.refine_city, opp.sell_city}
    assert len(route_cities) <= 2

