from dataclasses import dataclass

@dataclass(frozen=True)
class ParsedItem:
    """
    Represents a parsed and normalized Albion item.
    """
    raw_id: str
    tier: int
    enchantment: int
    quality: int | None
    archetype: str
    effective_tier: int
    normalized_id: str
    category: str
