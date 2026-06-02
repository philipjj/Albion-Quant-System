"""
Substitution cluster generation.
"""

from collections import defaultdict

from app.ontology.models import ParsedItem


def generate_clusters(items: list[ParsedItem]) -> dict[str, list[ParsedItem]]:
    """
    Groups items into substitution clusters based on IP equivalence.
    Equivalent items share the same archetype and effective tier.
    """
    clusters = defaultdict(list)
    for item in items:
        cluster_key = f"{item.archetype}_ET{item.effective_tier}"
        clusters[cluster_key].append(item)
    return dict(clusters)
