"""
IP Equivalence mapping and substitution cluster generation.
"""
from app.ontology.models import ParsedItem
from app.ontology.parser import parse_item_id

def calculate_effective_tier(tier: int, enchantment: int) -> int:
    """
    Calculates the effective tier (e.g., T4.3 -> T7 equivalent).
    """
    return tier + enchantment

def are_equivalent(item1: ParsedItem, item2: ParsedItem) -> bool:
    """
    Checks if two items are IP-equivalent and can substitute each other.
    They must have the same archetype and the same effective tier.
    """
    return (
        item1.archetype == item2.archetype and
        item1.effective_tier == item2.effective_tier
    )

def generate_cluster_id(item: ParsedItem) -> str:
    """
    Generates a unique cluster ID for an item based on archetype and effective tier.
    Example: T4_MAIN_SWORD_LEVEL3 -> CLUSTER_MAIN_SWORD_ET7
    """
    return f"CLUSTER_{item.archetype}_ET{item.effective_tier}"

def get_cluster_items(items: list[str]) -> dict[str, list[str]]:
    """
    Groups a list of raw item IDs into substitution clusters.
    """
    clusters = {}
    for raw_id in items:
        parsed = parse_item_id(raw_id)
        cluster_id = generate_cluster_id(parsed)
        if cluster_id not in clusters:
            clusters[cluster_id] = []
        clusters[cluster_id].append(raw_id)
    return clusters
