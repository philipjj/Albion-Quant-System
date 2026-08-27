import pytest
from unittest.mock import AsyncMock, patch
from app.alerts.discord import DiscordAlerter, _is_island_opportunity
from app.core.config import settings
from app.core import state


@pytest.fixture(autouse=True)
def enable_discord_alerts_for_routing_tests():
    old = getattr(state, "discord_alerts_enabled", False)
    state.discord_alerts_enabled = True
    yield
    state.discord_alerts_enabled = old


def test_is_island_opportunity_detection():
    # Farming / crop items
    assert _is_island_opportunity({"item_id": "T4_TURNIP", "category": "farming"}) is True
    assert _is_island_opportunity({"item_id": "T3_WHEAT", "category": "farming"}) is True
    assert _is_island_opportunity({"item_id": "T4_SEED_CARROT", "category": "farming"}) is True
    assert _is_island_opportunity({"item_id": "T3_FARM_CHICKEN_GROWN", "category": "livestock"}) is True
    assert _is_island_opportunity({"item_id": "T3_MEAT", "category": "consumables"}) is True
    assert _is_island_opportunity({"item_id": "T4_POTION_HEAL", "category": "potions"}) is True
    assert _is_island_opportunity({"item_id": "T5_MEAL_ROAST", "category": "food"}) is True

    # Farm-raised animals, calfs, foals, baby mounts, saddled mounts
    assert _is_island_opportunity({"item_id": "T4_FARM_OX_BABY", "category": "livestock"}) is True
    assert _is_island_opportunity({"item_id": "T5_FARM_HORSE_BABY", "category": "animals"}) is True
    assert _is_island_opportunity({"item_id": "T6_FARM_DIREWOLF_BABY", "category": "animals"}) is True
    assert _is_island_opportunity({"item_id": "T5_FARM_SWIFTCLAW_BABY", "category": "animals"}) is True
    assert _is_island_opportunity({"item_id": "T8_FARM_MAMMOTH_BABY", "category": "animals"}) is True
    assert _is_island_opportunity({"item_id": "T5_MOUNT_SWIFTCLAW", "category": "mounts"}) is True
    assert _is_island_opportunity({"item_id": "T5_MOUNT_ARMORED_HORSE", "category": "mounts"}) is True
    assert _is_island_opportunity({"item_id": "T4_MOUNT_GIANTSTAG", "category": "mounts"}) is True

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


@pytest.mark.asyncio
async def test_enchanting_isolation_and_formatting():
    from app.core.opportunity_engine import OpportunityScanner

    scanner = OpportunityScanner()
    prices = {
        "T6_ARMOR_LEATHER_SET1@2": {
            "Lymhurst": {1: {"sell_price_min": 560000, "buy_price_max": 520000, "data_age_seconds": 10, "volume_24h": 50}},
            "Black Market": {1: {"buy_price_max": 900000, "data_age_seconds": 10, "volume_24h": 50}},
        },
        "T6_ARMOR_LEATHER_SET1@1": {
            "Lymhurst": {1: {"sell_price_min": 300000, "buy_price_max": 280000, "data_age_seconds": 10, "volume_24h": 50}},
            "Caerleon": {1: {"sell_price_min": 320000, "buy_price_max": 300000, "data_age_seconds": 10, "volume_24h": 50}},
        },
        "T6_SOUL": {
            "Lymhurst": {1: {"sell_price_min": 800, "buy_price_max": 750, "data_age_seconds": 10, "volume_24h": 1000}},
            "Caerleon": {1: {"sell_price_min": 850, "buy_price_max": 800, "data_age_seconds": 10, "volume_24h": 1000}},
        },
    }

    names = {"T6_ARMOR_LEATHER_SET1@2": "Master's Mercenary Jacket .2"}

    # 1. Royal Enchanting Scan MUST NOT contain Black Market or Caerleon
    royal_enchant = scanner.scan_enchanting(prices, names)
    assert len(royal_enchant) > 0
    for opp in royal_enchant:
        assert opp.base_city != "Caerleon"
        assert opp.sell_city != "Black Market"
        assert opp.sell_city in ["Lymhurst", "Martlock", "Fort Sterling", "Bridgewatch", "Thetford"]

    # 2. Format embed for Royal Enchanting
    alerter = DiscordAlerter()
    royal_dict = {
        "item_id": "T6_ARMOR_LEATHER_SET1@2",
        "target_item_id": "T6_ARMOR_LEATHER_SET1@2",
        "item_name": "Master's Mercenary Jacket .2",
        "base_item_id": "T6_ARMOR_LEATHER_SET1@1",
        "base_city": "Lymhurst",
        "destination_city": "Lymhurst",
        "sell_city": "Lymhurst",
        "base_price": 300000,
        "material_id": "T6_SOUL",
        "material_qty": 192,
        "material_price": 800,
        "sell_price": 800000,
        "profit": 250000,
        "net_profit": 250000,
        "profit_pct": 35.0,
        "roi": 45.0,
        "quality": 1,
        "base_quality": 1,
    }
    embed = alerter._format_enchanting_embed(royal_dict)
    assert "ROYAL ENCHANTING" in embed["description"]
    assert "Caerleon" not in embed["description"]
    assert "Black Market" not in embed["description"]
    assert "Lymhurst (Buy Base, Enchant & Sell)" in embed["description"]


@pytest.mark.asyncio
async def test_quality_misprices_do_not_leak_to_arbitrage_webhook():
    alerter = DiscordAlerter()
    alerter.enabled = True
    alerter.arb_webhook_url = "https://discord.com/api/webhooks/111/arbitrage"
    alerter.quality_webhook_url = ""  # No quality webhook configured

    quality_opps = [
        {
            "item_id": "T4_HEAD_CLOTH_SET1@2",
            "item_name": "Adept's Druid Cowl .2 (Excellent)",
            "city": "Bridgewatch",
            "buy_price": 25600,
            "reference_price": 31000,
            "net_profit": 2100,
            "profit_pct": 6.8,
            "roi": 8.3,
            "daily_volume": 0,
            "data_age_seconds": 100,
            "inversion_type": "higher_quality_cheaper",
            "buy_quality": 4,
            "buy_quality_name": "Excellent",
            "reference_quality": 3,
            "reference_quality_name": "Outstanding",
            "safe_limit": 1,
        }
    ]

    with patch.object(alerter, "_send_webhook", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        await alerter.send_batch_alerts(
            arb_opps=[],
            quality_opps=quality_opps,
            quality_limit=10,
        )

        sent_urls = [call.kwargs.get("webhook_url") for call in mock_send.call_args_list]

        # Quality misprices must NEVER leak into arbitrage webhook when quality webhook is unset!
        assert alerter.arb_webhook_url not in sent_urls
        assert len(sent_urls) == 0


@pytest.mark.asyncio
async def test_quality_alerts_route_to_dedicated_quality_webhook():
    alerter = DiscordAlerter()
    alerter.enabled = True
    alerter.arb_webhook_url = "https://discord.com/api/webhooks/111/arbitrage"
    alerter.quality_webhook_url = "https://discord.com/api/webhooks/333/quality"

    quality_opps = [
        {
            "item_id": "T4_HEAD_CLOTH_SET1@2",
            "item_name": "Adept's Druid Cowl .2 (Excellent)",
            "city": "Bridgewatch",
            "buy_price": 25600,
            "reference_price": 31000,
            "net_profit": 2100,
            "profit_pct": 6.8,
            "roi": 8.3,
            "daily_volume": 0,
            "data_age_seconds": 100,
            "inversion_type": "higher_quality_cheaper",
            "buy_quality": 4,
            "buy_quality_name": "Excellent",
            "reference_quality": 3,
            "reference_quality_name": "Outstanding",
            "safe_limit": 1,
        }
    ]

    with patch.object(alerter, "_send_webhook", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        await alerter.send_batch_alerts(
            arb_opps=[],
            quality_opps=quality_opps,
            quality_limit=10,
        )

        sent_urls = [call.kwargs.get("webhook_url") for call in mock_send.call_args_list]

        assert alerter.quality_webhook_url in sent_urls
        assert alerter.arb_webhook_url not in sent_urls
        assert len(sent_urls) == 1


