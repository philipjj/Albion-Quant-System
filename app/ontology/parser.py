"""
Deterministic parsing for Albion item IDs.
"""
import re
from app.ontology.models import ParsedItem

# Regex to match Tier at start (e.g., T4_)
TIER_PATTERN = re.compile(r"^T([1-8])_")

# Regex to match Enchantment (e.g., _LEVEL1 or @1)
ENCHANT_PATTERN = re.compile(r"(?:_LEVEL|@)([0-4])$")

def parse_item_id(raw_id: str) -> ParsedItem:
    """
    Parses an Albion item ID into its components.
    
    Support:
    - Tiers (T1-T8)
    - Enchantments (_LEVEL1-4 or @1-4)
    - Qualities (Normal=1, Good=2, etc. - default to 1 if not in ID)
    - Artifacts
    - Resources
    - Consumables
    
    Example: T4_MAIN_SWORD_LEVEL3 -> Tier 4, Enchant 3, Effective Tier 7
    """
    tier = 1
    enchantment = 0
    quality = 1  # Default quality
    archetype = raw_id
    
    # Parse Tier
    tier_match = TIER_PATTERN.match(raw_id)
    if tier_match:
        tier = int(tier_match.group(1))
        archetype = raw_id[tier_match.end():]
        
    # Parse Enchantment
    enchant_match = ENCHANT_PATTERN.search(archetype)
    if enchant_match:
        enchantment = int(enchant_match.group(1))
        archetype = archetype[:enchant_match.start()]
        
    # Effective Tier = Tier + Enchantment
    effective_tier = tier + enchantment
    
    # Normalized ID is Archetype (without tier and enchant)
    normalized_id = archetype
    
    # Category (simplistic for now, can be improved via taxonomy)
    category = "equipment" if "MAIN" in archetype or "ARMOR" in archetype else "resource"
    
    return ParsedItem(
        raw_id=raw_id,
        tier=tier,
        enchantment=enchantment,
        quality=quality,
        archetype=archetype,
        effective_tier=effective_tier,
        normalized_id=normalized_id,
        category=category
    )
