"""
Tests for equivalence engine.
"""
from app.ontology.equivalence import calculate_effective_tier, are_equivalent, generate_cluster_id
from app.ontology.parser import parse_item_id

def test_calculate_effective_tier():
    assert calculate_effective_tier(4, 3) == 7
    assert calculate_effective_tier(7, 0) == 7
    assert calculate_effective_tier(8, 4) == 12

def test_are_equivalent():
    item1 = parse_item_id("T4_MAIN_SWORD_LEVEL3")
    item2 = parse_item_id("T7_MAIN_SWORD")
    assert are_equivalent(item1, item2) == True

def test_are_not_equivalent_different_archetype():
    item1 = parse_item_id("T4_MAIN_SWORD_LEVEL3")
    item2 = parse_item_id("T7_MAIN_AXE")
    assert are_equivalent(item1, item2) == False

def test_generate_cluster_id():
    item = parse_item_id("T4_MAIN_SWORD_LEVEL3")
    assert generate_cluster_id(item) == "CLUSTER_MAIN_SWORD_ET7"
