"""
Comprehensive Test Suite for the Precision-Calibrated Market Freshness,
Enchanting/Crafting Materials Synchronization, and Travel Buffer Engine.
"""

import pytest
from app.core.freshness import (
    get_max_material_age_seconds,
    get_max_allowed_leg_desync_seconds,
    calculate_leg_sync_score,
    calculate_route_travel_buffer,
    is_market_data_fresh,
    get_tier_based_half_life_hours,
    _classify_item,
    _extract_tier_enchant,
)
from app.core.opportunity_engine import get_max_allowed_bm_age_seconds


class TestTierEnchantExtraction:
    def test_extract_standard_items(self):
        assert _extract_tier_enchant("T4_BAG") == (4, 0)
        assert _extract_tier_enchant("T5_PLANKS@2") == (5, 2)
        assert _extract_tier_enchant("T8_2H_CLAYMORE@4") == (8, 4)
        assert _extract_tier_enchant("T6_HEAD_PLATE_SET1@1") == (6, 1)

    def test_extract_level_format(self):
        assert _extract_tier_enchant("T7_WOOD_LEVEL3") == (7, 3)

    def test_extract_fallback(self):
        assert _extract_tier_enchant("QUESTITEM_TOKEN_AVALON") == (4, 0)


class TestItemClassification:
    def test_materials(self):
        assert _classify_item("T4_ORE") == "material"
        assert _classify_item("T5_BAR") == "material"
        assert _classify_item("T6_LEATHER@1") == "material"
        assert _classify_item("T7_CLOTH@2") == "material"
        assert _classify_item("T8_PLANKS@3") == "material"
        assert _classify_item("T4_STONEBLOCK") == "material"

    def test_enchant_materials(self):
        assert _classify_item("T4_RUNE") == "enchant_material"
        assert _classify_item("T6_SOUL") == "enchant_material"
        assert _classify_item("T8_RELIC") == "enchant_material"
        assert _classify_item("T7_SHARD_AVALONIAN") == "enchant_material"
        assert _classify_item("QUESTITEM_TOKEN_AVALON") == "enchant_material"

    def test_artifacts(self):
        assert _classify_item("T4_ARTEFACT_2H_DUALSCYTHE_HELL") == "artifact"
        assert _classify_item("T6_ARTEFACT_MAIN_SWORD_AVALON") == "artifact"
        assert _classify_item("T8_ARTEFACT_ARMOR_PLATE_AVALON") == "artifact"

    def test_consumables(self):
        assert _classify_item("T7_MEAL_ROAST") == "consumable"
        assert _classify_item("T4_POTION_HEAL") == "consumable"
        assert _classify_item("T6_MEAL_STEW@1") == "consumable"

    def test_specialty(self):
        assert _classify_item("T5_MOUNT_ARMORED_HORSE") == "specialty"
        assert _classify_item("T4_JOURNAL_WARRIOR") == "specialty"
        assert _classify_item("T6_TOOL_PICKAXE") == "specialty"

    def test_equipment(self):
        assert _classify_item("T4_MAIN_SWORD") == "equipment"
        assert _classify_item("T8_2H_CROSSBOW@3") == "equipment"
        assert _classify_item("T6_ARMOR_CLOTH_SET1") == "equipment"
        assert _classify_item("T5_CAPE") == "equipment"
        assert _classify_item("T4_BAG") == "equipment"


class TestMaterialAgeLadderProgression:
    def test_materials_progressive_ladder(self):
        # Lower tiers have tighter age limits (high velocity)
        t4_age = get_max_material_age_seconds("T4_BAR")
        t5_age = get_max_material_age_seconds("T5_BAR")
        t6_age = get_max_material_age_seconds("T6_BAR")
        t7_age = get_max_material_age_seconds("T7_BAR")
        t8_age = get_max_material_age_seconds("T8_BAR")

        assert t4_age == 3600    # 1.0 hour
        assert t5_age == 4500    # 1.25 hours (75 min)
        assert t6_age == 5400    # 1.5 hours
        assert t7_age == 7200    # 2.0 hours
        assert t8_age == 10800   # 3.0 hours
        assert t4_age < t5_age < t6_age < t7_age < t8_age

    def test_enchant_materials_ladder(self):
        # Runes vs Souls vs Relics
        r4 = get_max_material_age_seconds("T4_RUNE")
        r8 = get_max_material_age_seconds("T8_RUNE")
        s8 = get_max_material_age_seconds("T8_SOUL")
        rel8 = get_max_material_age_seconds("T8_RELIC")

        assert r4 == 2700        # 45 min
        assert r8 == 7200        # 2.0h
        assert s8 == 7200        # 2.0h
        assert rel8 == 14400     # 4.0h
        assert r4 < r8 <= s8 < rel8


class TestBlackMarketFlashFillTTLs:
    def test_low_tier_fast_fill_ttl(self):
        # T4 flat weapon with 45k price -> 1.5 hours (5400s)
        t4_bm_ttl = get_max_allowed_bm_age_seconds("T4_MAIN_SWORD", bm_price=45_000)
        assert t4_bm_ttl == 5400

    def test_mid_tier_bm_ttl(self):
        # T6.2 weapon with 850k price -> 6.0h (21600s)
        t6_bm_ttl = get_max_allowed_bm_age_seconds("T6_2H_BOW@2", bm_price=850_000)
        assert t6_bm_ttl == 21600

    def test_whale_bm_ttl(self):
        # T8.4 Whale weapon with 38M price -> 2 days (172,800s)
        whale_ttl = get_max_allowed_bm_age_seconds("T8_MAIN_HOLYSTAFF@4", bm_price=38_000_000)
        assert whale_ttl == 172_800


class TestMultiLegDesynchronization:
    def test_desync_thresholds(self):
        assert get_max_allowed_leg_desync_seconds(4) == 2700    # 45 min
        assert get_max_allowed_leg_desync_seconds(6) == 5400    # 1.5h
        assert get_max_allowed_leg_desync_seconds(8) == 10800   # 3.0h

    def test_leg_sync_scoring(self):
        # Zero drift -> 1.0 perfect confidence
        assert calculate_leg_sync_score(output_age=600, input_ages=[600, 580], tier=4) == 1.0

        # Moderate drift (15 min delta on T4 max 45 min / 2700s) -> 1.0 - 900/2700 = 0.6667
        score = calculate_leg_sync_score(output_age=1500, input_ages=[600], tier=4)
        assert 0.60 <= score <= 0.70

        # Extreme drift (1.5 hours delta on T4 max 45 min) -> 0.1 floor
        score_stale = calculate_leg_sync_score(output_age=6000, input_ages=[600], tier=4)
        assert score_stale == 0.1


class TestRouteTravelBuffer:
    def test_same_city_buffer(self):
        assert calculate_route_travel_buffer("Caerleon", "Caerleon") == 0

    def test_cross_city_dangerous_route_buffer(self):
        # Martlock to Caerleon is a dangerous route
        buffer_sec = calculate_route_travel_buffer("Martlock", "Caerleon")
        assert buffer_sec > 300  # Includes distance + dangerous zone prep buffer


class TestVolumeOverride:
    def test_continuous_volume_scaling(self):
        # T8.0 Bar base is 10800 (3h)
        base = get_max_material_age_seconds("T8_BAR", volume_24h=50)
        assert base == 10800

        # Volume >= 1000 scales down by 55% -> 5940
        high_vol = get_max_material_age_seconds("T8_BAR", volume_24h=1500)
        assert high_vol == 5940

        # Volume >= 5000 scales down by 35% -> 3780
        very_high_vol = get_max_material_age_seconds("T8_BAR", volume_24h=6000)
        assert very_high_vol == 3780


class TestScanElapsedBuffer:
    def test_scan_elapsed_buffer_extends_age_limit(self):
        # Base limit for T4_RUNE is 2700s (45m)
        base_ttl = get_max_material_age_seconds("T4_RUNE", scan_elapsed_seconds=0)
        assert base_ttl == 2700

        # Adding a 300s scan elapsed buffer extends the threshold to 3000s
        buffered_ttl = get_max_material_age_seconds("T4_RUNE", scan_elapsed_seconds=300)
        assert buffered_ttl == 3000

    def test_desync_buffer_extends_desync_limit(self):
        base_desync = get_max_allowed_leg_desync_seconds(4, scan_elapsed_seconds=0)
        assert base_desync == 2700

        buffered_desync = get_max_allowed_leg_desync_seconds(4, scan_elapsed_seconds=300)
        assert buffered_desync == 3000


class TestDualSegmentAgeLimits:
    def test_royal_vs_caerleon_segmentation(self):
        # Royal City (Martlock) has strict 1-hour limit on T4_BAR
        royal_ttl = get_max_material_age_seconds("T4_BAR", city="Martlock")
        assert royal_ttl == 3600

        # Caerleon / Black Market has widened 2x limit for red zone transit
        caerleon_ttl = get_max_material_age_seconds("T4_BAR", city="Caerleon")
        assert caerleon_ttl == 7200
        assert royal_ttl < caerleon_ttl

    def test_is_market_data_fresh_segmentation(self):
        # Data that is 4500 seconds old:
        # In Royal non-lethal (Martlock), 4500s > 3600s + 300s buffer (3900s) -> REJECTED (no phantom order)
        assert is_market_data_fresh("T4_BAR", age_seconds=4500, city="Martlock") is False

        # In Caerleon lethal, 4500s <= 7200s + 300s buffer -> ACCEPTED
        assert is_market_data_fresh("T4_BAR", age_seconds=4500, city="Caerleon") is True
