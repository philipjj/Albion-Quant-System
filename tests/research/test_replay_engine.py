"""
Tests for Replay Engine.
"""
from research.replay.engine import ReplayEngine
from app.db.models import MarketPrice
from datetime import datetime, timedelta
import pytest
import sqlite3
import os

def test_replay_engine_iterator_mock():
    items = [
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow() - timedelta(hours=1)),
        MarketPrice(item_id="T4_SWORD", city="Caerleon", captured_at=datetime.utcnow()),
    ]
    
    engine = ReplayEngine(source="mock")
    engine.set_mock_data(items)
    
    states = list(engine.replay_iterator(
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=1)
    ))
    
    assert len(states) == 2
    # Fixed: states are dictionaries now
    assert states[0]["captured_at"] < states[1]["captured_at"]

def test_replay_engine_iterator_db():
    # Test with a real (temporary) SQLite DB
    db_path = "tests/research/test_market.db"
    
    # Setup
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY,
            item_id TEXT,
            city TEXT,
            captured_at TIMESTAMP
        )
    """)
    
    t1 = datetime.utcnow() - timedelta(hours=1)
    t2 = datetime.utcnow()
    
    cursor.execute("INSERT INTO market_prices (item_id, city, captured_at) VALUES (?, ?, ?)",
                   ("T4_SWORD", "Caerleon", t1.strftime('%Y-%m-%d %H:%M:%S')))
    cursor.execute("INSERT INTO market_prices (item_id, city, captured_at) VALUES (?, ?, ?)",
                   ("T4_SWORD", "Caerleon", t2.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    
    try:
        engine = ReplayEngine(source="db", db_path=db_path)
        states = list(engine.replay_iterator(
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=1)
        ))
        
        assert len(states) == 2
        # Check that they are ordered by captured_at
        assert states[0]["captured_at"] < states[1]["captured_at"]
        
    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.remove(db_path)
