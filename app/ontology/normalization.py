"""
Item normalization logic.
"""

from app.ontology.parser import parse_item_id


def normalize_item_id(raw_id: str) -> str:
    """
    Returns the normalized ID for an item (e.g., removing enchantment/quality for base comparison).
    """
    parsed = parse_item_id(raw_id)
    return parsed.normalized_id
