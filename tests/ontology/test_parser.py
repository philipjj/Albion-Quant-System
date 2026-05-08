"""
Tests for item parser.
"""
from app.ontology.parser import parse_item_id

def test_parse_basic_item():
    parsed = parse_item_id("T4_MAIN_SWORD")
    assert parsed.tier == 4
    assert parsed.enchantment == 0
    assert parsed.effective_tier == 4
    assert parsed.archetype == "MAIN_SWORD"

def test_parse_enchanted_item():
    parsed = parse_item_id("T4_MAIN_SWORD_LEVEL3")
    assert parsed.tier == 4
    assert parsed.enchantment == 3
    assert parsed.effective_tier == 7
    assert parsed.archetype == "MAIN_SWORD"

def test_parse_at_enchantment():
    parsed = parse_item_id("T4_MAIN_SWORD@2")
    assert parsed.tier == 4
    assert parsed.enchantment == 2
    assert parsed.effective_tier == 6
    assert parsed.archetype == "MAIN_SWORD"

def test_parse_no_tier():
    parsed = parse_item_id("UNIQUE_HIDEOUT")
    assert parsed.tier == 1  # Default in our parser for now
    assert parsed.enchantment == 0
    assert parsed.archetype == "UNIQUE_HIDEOUT"
