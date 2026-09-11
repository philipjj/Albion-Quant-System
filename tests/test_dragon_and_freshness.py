"""
Unit and integration tests verifying Dragonfire update data, 3-tier freshness framework,
dynamic manipulation filters, and 1-click pre-flight live price verification.
"""

import pytest
from app.core.opportunity_engine import is_price_valid, get_min_realistic_price
from app.core.freshness import (
    get_freshness_tier,
    is_market_data_fresh,
    get_max_material_age_seconds,
    calculate_leg_sync_score,
)
from app.core.scanner_integration import UnifiedScanner


def test_is_price_valid_standard_vs_dragon_whale():
    """Verify standard commodities enforce 5x ratio, while Dragonfire and T8.2+ equipment allow up to 10x ratio."""
    # Standard T4 bag: 10k sell, 1.5k buy -> ratio 6.67x -> False
    assert is_price_valid(10000, 1500, daily_volume=100, item_id="T4_BAG") is False

    # Standard T4 bag: 10k sell, 3k buy -> ratio 3.33x -> True
    assert is_price_valid(10000, 3000, daily_volume=100, item_id="T4_BAG") is True

    # Dragonfire weapon (new release wide spread): 2M sell, 300k buy -> ratio 6.67x -> True
    assert is_price_valid(2000000, 300000, daily_volume=5, item_id="T8_MAIN_SWORD_DRAGON") is True

    # Whale T8.3 equipment: 8M sell, 1M buy -> ratio 8.0x -> True
    assert is_price_valid(8000000, 1000000, daily_volume=2, item_id="T8_ARMOR_PLATE_SET1@3") is True

    # Extreme manipulation (> 10x) is still rejected even for whale/dragon
    assert is_price_valid(15000000, 1000000, daily_volume=1, item_id="T8_ARMOR_PLATE_SET1@3") is False


def test_get_freshness_tier():
    """Verify 3-tier classification: verified (<45m), candidate (45m-24h), stale (>24h)."""
    # 10 minutes (600s) -> verified
    t1 = get_freshness_tier(600)
    assert t1["tier"] == "verified"
    assert t1["is_auto_alert_eligible"] is True
    assert "Verified Fresh" in t1["label"]

    # 40 minutes (2400s) -> verified
    t2 = get_freshness_tier([300, 2400])
    assert t2["tier"] == "verified"
    assert t2["is_auto_alert_eligible"] is True

    # 2 hours (7200s) -> candidate
    t3 = get_freshness_tier(7200)
    assert t3["tier"] == "candidate"
    assert t3["is_auto_alert_eligible"] is False
    assert "Candidate Spread" in t3["label"]

    # Multi-leg: buy leg 10m, sell leg 3h -> candidate
    t4 = get_freshness_tier([600, 10800])
    assert t4["tier"] == "candidate"
    assert t4["is_auto_alert_eligible"] is False

    # 30 hours (108000s) -> stale
    t5 = get_freshness_tier(108000)
    assert t5["tier"] == "stale"
    assert t5["is_auto_alert_eligible"] is False


def test_is_market_data_fresh_ingestion_context():
    """Verify ingestion context preserves multi-city snapshots up to 24h/48h without throwing data away."""
    # 4 hours old (14400s) data in Martlock
    # Under execution context it might be a candidate, but under ingestion context it MUST be accepted
    assert is_market_data_fresh("T4_BAG", 14400, volume_24h=50, city="Martlock", context="ingestion") is True

    # 18 hours old in Black Market -> accepted at ingestion
    assert is_market_data_fresh("T8_ARMOR_PLATE_SET1@2", 64800, volume_24h=10, city="Black Market", context="ingestion") is True

    # > 48h data is rejected at ingestion
    assert is_market_data_fresh("T4_BAG", 200000, volume_24h=50, city="Martlock", context="ingestion") is False


def test_scanner_enrich_freshness_tier():
    """Verify UnifiedScanner._enrich_freshness_tier properly enriches dicts."""
    scanner = UnifiedScanner()

    # Fresh opportunity (<45m)
    fresh_opp = {
        "item_id": "T4_BAG",
        "data_age_buy": 300,
        "data_age_sell": 1200,
        "net_profit": 5000,
    }
    enriched_fresh = scanner._enrich_freshness_tier(fresh_opp)
    assert enriched_fresh["freshness_tier"] == "verified"
    assert "🟢" in enriched_fresh["freshness_badge"]
    assert enriched_fresh["max_leg_age_seconds"] == 1200

    # Candidate opportunity (e.g. 2.5 hours old)
    cand_opp = {
        "item_id": "T5_SWORD",
        "data_age_buy": 900,
        "data_age_sell": 9000,
        "net_profit": 25000,
    }
    enriched_cand = scanner._enrich_freshness_tier(cand_opp)
    assert enriched_cand["freshness_tier"] == "candidate"
    assert "🟡" in enriched_cand["freshness_badge"]
    assert enriched_cand["max_leg_age_seconds"] == 9000


@pytest.mark.asyncio
async def test_verify_opportunity_endpoint():
    """Verify the /api/v1/system/opportunities/verify endpoint returns expected structure."""
    from app.api.system import verify_opportunity_endpoint, VerifyOpportunityRequest

    req = VerifyOpportunityRequest(
        item_id="T4_BAG",
        source_city="Martlock",
        destination_city="Caerleon",
        expected_buy_price=1000,
        expected_sell_price=2500,
        quality=1,
    )
    res = await verify_opportunity_endpoint(req=req)
    assert "verified" in res
    assert "status" in res
    assert "live_buy_price" in res
    assert "live_sell_price" in res
    assert "message" in res
    assert res["source_city"] == "Martlock"
    assert res["destination_city"] == "Caerleon"
