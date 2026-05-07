"""
Database session management.
Supports SQLite (dev) and PostgreSQL (prod) via SQLAlchemy.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import Base


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    if settings.database_url.startswith("sqlite"):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception as e:
            print(f"Failed to set SQLite pragma (likely already WAL or locked): {e}")

# Create engine
engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30.0  # Wait up to 30s for write locks to clear
    }

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    **engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables and run simple migrations for schema changes."""
    Base.metadata.create_all(bind=engine)

    # ═══════════════════════════════════════════════════════════════
    # AUTO-MIGRATIONS (May 2026 Update)
    # ═══════════════════════════════════════════════════════════════
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        # 1. Update 'items' table
        items_cols = [c['name'] for c in inspector.get_columns('items')]
        if 'item_value' not in items_cols:
            conn.execute(text("ALTER TABLE items ADD COLUMN item_value FLOAT DEFAULT 0.0"))
        
        # 2. Update 'arbitrage_opportunities' table
        arb_cols = [c['name'] for c in inspector.get_columns('arbitrage_opportunities')]
        if 'ev_score' not in arb_cols:
            conn.execute(text("ALTER TABLE arbitrage_opportunities ADD COLUMN ev_score FLOAT DEFAULT 0.0"))
        
        # 3. Update 'crafting_opportunities' table
        craft_cols = [c['name'] for c in inspector.get_columns('crafting_opportunities')]
        if 'ev_score' not in craft_cols:
            conn.execute(text("ALTER TABLE crafting_opportunities ADD COLUMN ev_score FLOAT DEFAULT 0.0"))
        if 'ingredients_json' not in craft_cols:
            conn.execute(text("ALTER TABLE crafting_opportunities ADD COLUMN ingredients_json TEXT"))
        if 'decision_log' not in craft_cols:
            conn.execute(text("ALTER TABLE crafting_opportunities ADD COLUMN decision_log TEXT"))
            
        conn.commit()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency - yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Iterator[Session]:
    """Context manager for database sessions (for workers/scripts)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
