"""
Tests for alpha ranker.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.signals.alpha_ranker import rank_signals

def test_rank_signals():
    s1 = AlphaSignal(
        signal_type="imbalance",
        item_id="ITEM1",
        cluster_id="C1",
        alpha_score=0.5,
        confidence=0.8,
        persistence_score=0.5,
        manipulation_risk=0.1,
        timestamp=datetime.utcnow()
    )
    s2 = AlphaSignal(
        signal_type="scarcity",
        item_id="ITEM2",
        cluster_id="C2",
        alpha_score=0.8,
        confidence=0.9,
        persistence_score=0.5,
        manipulation_risk=0.1,
        timestamp=datetime.utcnow()
    )
    
    ranked = rank_signals([s1, s2])
    
    # s2 score = 0.8 * 0.9 = 0.72
    # s1 score = 0.5 * 0.8 = 0.4
    assert ranked[0].item_id == "ITEM2"
    assert ranked[1].item_id == "ITEM1"

def test_rank_signals_duplicate_suppression():
    s1 = AlphaSignal(
        signal_type="imbalance",
        item_id="ITEM1",
        cluster_id="C1",
        alpha_score=0.5,
        confidence=0.8,
        persistence_score=0.5,
        manipulation_risk=0.1,
        timestamp=datetime.utcnow()
    )
    s2 = AlphaSignal(
        signal_type="scarcity",
        item_id="ITEM1",
        cluster_id="C1",
        alpha_score=0.8,
        confidence=0.9,
        persistence_score=0.5,
        manipulation_risk=0.1,
        timestamp=datetime.utcnow()
    )
    
    ranked = rank_signals([s1, s2])
    
    # Should only keep the one with higher score (s2)
    assert len(ranked) == 1
    assert ranked[0].signal_type == "scarcity"
