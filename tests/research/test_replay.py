"""
Tests for replay engine.
"""
from app.research.replay_engine import replay_snapshot

def test_replay_snapshot():
    result = replay_snapshot("test_snapshot_001")
    assert result["signals_generated"] == 0
    assert result["alpha_realized"] == 0.0
