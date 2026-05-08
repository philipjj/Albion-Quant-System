"""
Tests for cluster generation.
"""
from app.ontology.equivalence import get_cluster_items

def test_get_cluster_items():
    items = [
        "T4_MAIN_SWORD_LEVEL3",
        "T7_MAIN_SWORD",
        "T4_MAIN_AXE",
        "T5_MAIN_SWORD_LEVEL2"
    ]
    clusters = get_cluster_items(items)
    
    # T4.3 and T7.0 should be in the same cluster (ET7)
    # T5.2 is also ET7!
    assert "CLUSTER_MAIN_SWORD_ET7" in clusters
    assert len(clusters["CLUSTER_MAIN_SWORD_ET7"]) == 3
    assert "T4_MAIN_SWORD_LEVEL3" in clusters["CLUSTER_MAIN_SWORD_ET7"]
    assert "T7_MAIN_SWORD" in clusters["CLUSTER_MAIN_SWORD_ET7"]
    assert "T5_MAIN_SWORD_LEVEL2" in clusters["CLUSTER_MAIN_SWORD_ET7"]
    
    # T4.0 Axe should be in its own cluster (ET4)
    assert "CLUSTER_MAIN_AXE_ET4" in clusters
    assert len(clusters["CLUSTER_MAIN_AXE_ET4"]) == 1
