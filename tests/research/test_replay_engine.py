"""
Tests for Replay Engine.
"""
from research.replay.engine import ReplayEngine
from app.db.models import MarketPrice
from datetime import datetime, timedelta
import pytest

def test_replay_engine_iterator():
    # We can't easily mock the database here without setting up a full test DB
    # So we will mock the database query in the implementation or use a mock engine
    
    # For now, let's test that the iterator yields items in chronological order
    # if we provide it with a list of items.
    
    # Let's assume ReplayEngine can take a list of items for testing
    items = [
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow() - timedelta(hours=1)),
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow()),
    ]
    
    # We might need to mock the DB connection in the real test
    # But for a simple test of the iterator logic:
    
    engine = ReplayEngine(source="mock")
    engine.set_mock_data(items)
    
    states = list(engine.replay_iterator(
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=1)
    ))
    
    assert len(states) == 2
    assert states[0].captured_at < states[1].captured_at
