import pytest
from datetime import datetime, timedelta
from app.ingestion.nats_client import AlbionNatsClient


@pytest.fixture
def nats_client():
    return AlbionNatsClient()


def test_nats_lob_order_update(nats_client):
    """Test that incoming NATS orders build the live orderbook."""
    order1 = {
        "Id": 1001,
        "ItemTypeId": "T4_BAG",
        "LocationId": 3003,  # Martlock
        "QualityLevel": 1,
        "UnitPriceSilver": 150000000,  # 15,000 silver
        "Amount": 1,
        "AuctionType": "offer",
        "Expires": "2030-01-01T00:00:00Z",
    }
    nats_client._update_live_lob("T4_BAG", "Martlock", 1, order1)

    key = ("T4_BAG", "Martlock", 1)
    assert key in nats_client.live_orderbook
    lob = nats_client.live_orderbook[key]
    assert 1001 in lob["offers"]
    assert lob["top_sell_price"] == 15000.0


def test_nats_lob_anti_bait_depth_pooling(nats_client):
    """
    Test depth pooling: 1-unit bait order at 10 silver vs 5 units at 50,000 silver.
    True Sell Price should ignore the 1-unit bait and reflect depth price.
    """
    # 1. Troll order: 1 unit @ 10 silver
    order_bait = {
        "Id": 1,
        "ItemTypeId": "T6_MAIN_SWORD",
        "LocationId": 1002,  # Lymhurst
        "QualityLevel": 1,
        "UnitPriceSilver": 100000,  # 10 silver
        "Amount": 1,
        "AuctionType": "offer",
    }
    nats_client._update_live_lob("T6_MAIN_SWORD", "Lymhurst", 1, order_bait)

    # 2. Real market orders: 5 units @ 50,000 silver
    order_real = {
        "Id": 2,
        "ItemTypeId": "T6_MAIN_SWORD",
        "LocationId": 1002,
        "QualityLevel": 1,
        "UnitPriceSilver": 500000000,  # 50,000 silver
        "Amount": 5,
        "AuctionType": "offer",
    }
    nats_client._update_live_lob("T6_MAIN_SWORD", "Lymhurst", 1, order_real)

    lob = nats_client.live_orderbook[("T6_MAIN_SWORD", "Lymhurst", 1)]
    assert lob["top_sell_price"] == 10.0  # Raw top-of-book
    assert lob["true_sell_price"] == 50000.0  # Depth-weighted true price (>= 3 units for equipment)


def test_nats_get_live_prices_dict(nats_client):
    """Test converting live orderbook to dictionary for scanner."""
    order = {
        "Id": 500,
        "ItemTypeId": "T7_ARMOR_CLOTH_SET1",
        "LocationId": 4002,  # Fort Sterling
        "QualityLevel": 2,
        "UnitPriceSilver": 1200000000,  # 120,000 silver
        "Amount": 10,
        "AuctionType": "offer",
    }
    nats_client._update_live_lob("T7_ARMOR_CLOTH_SET1", "Fort Sterling", 2, order)

    prices_dict = nats_client.get_live_prices_dict()
    assert "T7_ARMOR_CLOTH_SET1" in prices_dict
    assert "Fort Sterling" in prices_dict["T7_ARMOR_CLOTH_SET1"]
    assert 2 in prices_dict["T7_ARMOR_CLOTH_SET1"]["Fort Sterling"]
    data = prices_dict["T7_ARMOR_CLOTH_SET1"]["Fort Sterling"][2]
    assert data["sell_price_min"] == 120000
    assert data["data_age_seconds"] == 0
