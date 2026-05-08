"""
Tests for imbalance signal generation.
"""
from app.signals.imbalance import generate_imbalance_signal

def test_generate_imbalance_signal():
    signal = generate_imbalance_signal("T4_MAIN_SWORD", "CLUSTER_MAIN_SWORD_ET4", 100.0, 0.0)
    assert signal.signal_type == "imbalance"
    assert signal.item_id == "T4_MAIN_SWORD"
    assert signal.alpha_score == 1.0
    assert signal.confidence == 0.8
