"""
Database session management.
Supports SQLite (dev) and PostgreSQL (prod) via SQLAlchemy.
"""
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, inspect, text
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
            print(f"Failed to set SQLite pragma: {e}")

engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30.0}

engine = create_engine(settings.database_url, echo=False, pool_pre_ping=True, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async Support for TimescaleDB/PostgreSQL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from contextlib import asynccontextmanager

# We derive the async URL from the sync one if it's postgresql
async_engine = None
AsyncSessionLocal = None

if settings.database_url.startswith("postgresql"):
    async_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    async_engine = create_async_engine(async_url, echo=False, pool_pre_ping=True)
    AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=async_engine)

@asynccontextmanager
async def get_async_db_session():
    if AsyncSessionLocal is None:
        raise RuntimeError("Async session is not configured. DATABASE_URL must start with postgresql.")
    db = AsyncSessionLocal()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

def init_db() -> None:
    """Create all tables and run migrations for AQS v3.0."""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        # Helper to add column if missing
        def add_col(table, col, col_type):
            try:
                cols = [c['name'] for c in inspector.get_columns(table)]
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    print(f"Migration: Added {col} to {table}")
            except Exception as e:
                print(f"Migration Error ({table}.{col}): {e}")

        # 1. Items
        add_col('items', 'item_value', 'FLOAT DEFAULT 0.0')

        # 2. Market Prices (AQS v3.0 Core)
        add_col('market_prices', 'server', 'VARCHAR DEFAULT "west"')
        add_col('market_prices', 'sell_price_min', 'BIGINT')
        add_col('market_prices', 'sell_price_max', 'BIGINT')
        add_col('market_prices', 'buy_price_min', 'BIGINT')
        add_col('market_prices', 'buy_price_max', 'BIGINT')
        add_col('market_prices', 'sell_price_min_date', 'DATETIME')
        add_col('market_prices', 'sell_price_max_date', 'DATETIME')
        add_col('market_prices', 'buy_price_min_date', 'DATETIME')
        add_col('market_prices', 'buy_price_max_date', 'DATETIME')
        add_col('market_prices', 'volume_24h', 'INTEGER DEFAULT 0')
        add_col('market_prices', 'quality', 'INTEGER DEFAULT 1')
        add_col('market_prices', 'data_age_seconds', 'FLOAT DEFAULT 0.0')
        add_col('market_prices', 'confidence_score', 'FLOAT DEFAULT 1.0')
        add_col('market_prices', 'coverage_suspect', 'BOOLEAN DEFAULT 0')
        add_col('market_prices', 'captured_at', 'DATETIME')
        add_col('market_prices', 'captured_at_bucket', 'DATETIME')

        # 3. Market Snapshots
        add_col('market_snapshots', 'server', 'VARCHAR DEFAULT "west"')
        add_col('market_snapshots', 'sell_price_min', 'BIGINT')
        add_col('market_snapshots', 'sell_price_max', 'BIGINT')
        add_col('market_snapshots', 'buy_price_min', 'BIGINT')
        add_col('market_snapshots', 'buy_price_max', 'BIGINT')
        add_col('market_snapshots', 'sell_price_min_date', 'DATETIME')
        add_col('market_snapshots', 'sell_price_max_date', 'DATETIME')
        add_col('market_snapshots', 'buy_price_min_date', 'DATETIME')
        add_col('market_snapshots', 'buy_price_max_date', 'DATETIME')
        add_col('market_snapshots', 'volume_24h', 'INTEGER DEFAULT 0')
        add_col('market_snapshots', 'quality', 'INTEGER DEFAULT 1')
        add_col('market_snapshots', 'data_age_seconds', 'FLOAT DEFAULT 0.0')
        add_col('market_snapshots', 'confidence_score', 'FLOAT DEFAULT 1.0')
        add_col('market_snapshots', 'coverage_suspect', 'BOOLEAN DEFAULT 0')
        add_col('market_snapshots', 'captured_at', 'DATETIME')

        # 3.1 Black Market Snapshots
        add_col('black_market_snapshots', 'captured_at_bucket', 'DATETIME')

        # [CRITICAL] Create Unique Indexes for UPSERT
        try:
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_market_upsert 
                ON market_prices (item_id, city, quality, captured_at_bucket)
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_bm_upsert 
                ON black_market_snapshots (item_id, quality, captured_at_bucket)
            """))
            
            # Create hypertable for TimescaleDB if using PostgreSQL
            if not settings.database_url.startswith("sqlite"):
                try:
                    conn.execute(text("SELECT create_hypertable('market_prices', 'captured_at', if_not_exists => TRUE);"))
                    print("Migration: Verified hypertable for market_prices")
                except Exception as e:
                    # This might fail if the extension is not installed or it's already a hypertable
                    print(f"Migration Error (Hypertable): {e}")
                    
            conn.commit()
            print("Migration: Unique UPSERT indexes verified")
        except Exception as e:
            print(f"Migration Error (Indexes): {e}")

        # 4. Arbitrage
        add_col('arbitrage_opportunities', 'ev_score', 'FLOAT DEFAULT 0.0')
        add_col('arbitrage_opportunities', 'volatility', 'FLOAT DEFAULT 0.0')
        add_col('arbitrage_opportunities', 'z_score', 'FLOAT DEFAULT 0.0')
        add_col('arbitrage_opportunities', 'persistence', 'INTEGER DEFAULT 1')
        add_col('arbitrage_opportunities', 'volume_source', 'VARCHAR DEFAULT "ESTIMATED"')
        add_col('arbitrage_opportunities', 'safe_limit', 'INTEGER DEFAULT 1')
        add_col('arbitrage_opportunities', 'current_supply', 'INTEGER DEFAULT 0')
        add_col('arbitrage_opportunities', 'market_gap', 'INTEGER DEFAULT 0')
        add_col('arbitrage_opportunities', 'expected_hourly_profit', 'FLOAT DEFAULT 0.0')

        # 5. Crafting
        add_col('crafting_opportunities', 'ev_score', 'FLOAT DEFAULT 0.0')
        add_col('crafting_opportunities', 'z_score', 'FLOAT DEFAULT 0.0')
        add_col('crafting_opportunities', 'persistence', 'INTEGER DEFAULT 1')
        add_col('crafting_opportunities', 'ingredients_json', 'TEXT')
        add_col('crafting_opportunities', 'decision_log', 'TEXT')

        conn.commit()

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def get_db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
