import pytest
from unittest.mock import AsyncMock, patch
from app.alerts.discord import DiscordAlerter, _is_island_opportunity
from app.core.config import settings


def test_is_island_opportunity_detection():
    # Farming / crop items
    assert _is_island_opportunity({"item_id": "T4_TURNIP", "category": "farming"}) is True
    assert _is_island_opportunity({"item_id": "T3_WHEAT", "category": "farming"}) is True
    assert _is_island_opportunity({"item_id": "T4_SEED_CARROT", "category": "farming"}) is True
    assert _is_island_opportunity({"item_id": "T3_FARM_CHICKEN_GROWN", "category": "livestock"}) is True
    assert _is_island_opportunity({"item_id": "T3_MEAT", "category": "consumables"}) is True
    assert _is_island_opportunity({"item_id": "T4_POTION_HEAL", "category": "potions"}) is True
    assert _is_island_opportunity({"item_id": "T5_MEAL_ROAST", "category": "food"}) is True

    # Equipment items (Must NOT be flagged as island)
    assert _is_island_opportunity({"item_id": "T4_MAIN_SWORD", "category": "Equipment"}) is False
    assert _is_island_opportunity({"item_id": "T6_ARMOR_PLATE_SET1", "category": "Equipment"}) is False
    assert _is_island_opportunity({"item_id": "T8_2H_BOW", "category": "Equipment"}) is False
    assert _is_island_opportunity({"item_id": "T5_HEAD_LEATHER_MERCENARY", "category": "Equipment"}) is False
    assert _is_island_opportunity({"item_id": "T4_OFF_SHIELD", "category": "Equipment"}) is False


@pytest.mark.asyncio
async def test_island_opportunities_do_not_leak_to_crafting_webhook():
    alerter = DiscordAlerter()
    alerter.enabled = True
    alerter.crafting_webhook_url = "https://discord.com/api/webhooks/111/crafting"
    alerter.island_webhook_url = "https://discord.com/api/webhooks/222/island"

    craft_opps = [
        {"item_id": "T4_MAIN_SWORD", "crafting_city": "Martlock", "sell_city": "Bridgewatch", "category": "Equipment", "profit": 5000},
        {"item_id": "T4_TURNIP", "crafting_city": "Island", "sell_city": "Martlock", "category": "farming", "profit": 3000},
        {"item_id": "T3_FARM_CHICKEN_GROWN", "crafting_city": "Island", "sell_city": "Lymhurst", "category": "livestock", "profit": 4000},
    ]

    with patch.object(alerter, "_send_webhook", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        await alerter.send_batch_alerts(
            arb_opps=[],
            craft_opps=craft_opps,
            craft_limit=10,
        )

        sent_urls = [call.kwargs.get("webhook_url") for call in mock_send.call_args_list]

        # The equipment sword should go to crafting
        # The turnip and chicken should go to island webhook, NOT crafting!
        assert alerter.crafting_webhook_url in sent_urls
        assert alerter.island_webhook_url in sent_urls

        # Verify calls to crafting webhook ONLY contain equipment
        for call in mock_send.call_args_list:
            wh_url = call.kwargs.get("webhook_url")
            payload = call.args[0]
            embed = payload["embeds"][0]
            if wh_url == alerter.crafting_webhook_url:
                assert "TURNIP" not in embed["title"]
                assert "CHICKEN" not in embed["title"]


@pytest.mark.asyncio
async def test_island_alerts_skipped_when_island_webhook_unset():
    alerter = DiscordAlerter()
    alerter.enabled = True
    alerter.crafting_webhook_url = "https://discord.com/api/webhooks/111/crafting"
    alerter.island_webhook_url = ""  # No island webhook configured

    craft_opps = [
        {"item_id": "T4_MAIN_SWORD", "crafting_city": "Martlock", "sell_city": "Bridgewatch", "category": "Equipment", "profit": 5000},
        {"item_id": "T4_TURNIP", "crafting_city": "Island", "sell_city": "Martlock", "category": "farming", "profit": 3000},
    ]

    with patch.object(alerter, "_send_webhook", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        await alerter.send_batch_alerts(
            arb_opps=[],
            craft_opps=craft_opps,
            craft_limit=10,
        )

        sent_urls = [call.kwargs.get("webhook_url") for call in mock_send.call_args_list]

        # Only crafting webhook should receive alerts; island items must NEVER fallback to crafting!
        assert alerter.crafting_webhook_url in sent_urls
        assert len(sent_urls) == 1
