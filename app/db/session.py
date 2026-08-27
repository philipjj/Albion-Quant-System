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
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA wal_autocheckpoint=1000")
            cursor.execute("PRAGMA mmap_size=536870912")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()
        except Exception as e:
            print(f"Failed to set SQLite pragma: {e}")


def checkpoint_wal() -> None:
    """Executes a WAL checkpoint to truncate journal logs and keep DB compact."""
    if settings.database_url.startswith("sqlite"):
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception as e:
            pass


db_url = settings.database_url
try:
    engine_kwargs = {}
    if db_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 60.0}
    else:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine_kwargs["pool_recycle"] = 1800

    engine = create_engine(db_url, echo=False, pool_pre_ping=True, **engine_kwargs)
    with engine.connect() as _test_conn:
        pass
except Exception as e:
    print(f"[DB] Primary DB ({db_url}) unavailable ({e}). Using local SQLite: sqlite:///./data/albion_quant.db")
    db_url = "sqlite:///./data/albion_quant.db"
    engine = create_engine(db_url, echo=False, pool_pre_ping=True, connect_args={"check_same_thread": False, "timeout": 60.0})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async Support for TimescaleDB/PostgreSQL
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

async_engine = None
AsyncSessionLocal = None

if db_url.startswith("postgresql"):
    try:
        async_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        async_engine = create_async_engine(async_url, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=20, pool_recycle=1800)
        AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=async_engine)
    except Exception:
        pass


@asynccontextmanager
async def get_async_db_session():
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "Async session is not configured. DATABASE_URL must start with postgresql."
        )
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
        # Pre-cache column names for all existing tables in a single schema lookup
        tables = set(inspector.get_table_names())
        columns_cache = {}
        for t in tables:
            try:
                columns_cache[t] = {c["name"] for c in inspector.get_columns(t)}
            except Exception:
                columns_cache[t] = set()

        # Fast helper to check and add missing columns
        def add_col(table, col, col_type):
            if table not in columns_cache:
                return
            if col not in columns_cache[table]:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    columns_cache[table].add(col)
                    print(f"Migration: Added {col} to {table}")
                except Exception as e:
                    print(f"Migration Error ({table}.{col}): {e}")

        # 1. Items
        add_col("items", "item_value", "FLOAT DEFAULT 0.0")

        # 2. Market Prices (AQS v3.0 Core)
        add_col("market_prices", "server", 'VARCHAR DEFAULT "west"')
        add_col("market_prices", "sell_price_min", "BIGINT")
        add_col("market_prices", "sell_price_max", "BIGINT")
        add_col("market_prices", "buy_price_min", "BIGINT")
        add_col("market_prices", "buy_price_max", "BIGINT")
        add_col("market_prices", "sell_price_min_date", "DATETIME")
        add_col("market_prices", "sell_price_max_date", "DATETIME")
        add_col("market_prices", "buy_price_min_date", "DATETIME")
        add_col("market_prices", "buy_price_max_date", "DATETIME")
        add_col("market_prices", "volume_24h", "INTEGER DEFAULT 0")
        add_col("market_prices", "quality", "INTEGER DEFAULT 1")
        add_col("market_prices", "data_age_seconds", "FLOAT DEFAULT 0.0")
        add_col("market_prices", "confidence_score", "FLOAT DEFAULT 1.0")
        add_col("market_prices", "coverage_suspect", "BOOLEAN DEFAULT 0")
        add_col("market_prices", "captured_at", "DATETIME")
        add_col("market_prices", "captured_at_bucket", "DATETIME")

        # 3. Market Snapshots
        add_col("market_snapshots", "server", 'VARCHAR DEFAULT "west"')
        add_col("market_snapshots", "sell_price_min", "BIGINT")
        add_col("market_snapshots", "sell_price_max", "BIGINT")
        add_col("market_snapshots", "buy_price_min", "BIGINT")
        add_col("market_snapshots", "buy_price_max", "BIGINT")
        add_col("market_snapshots", "sell_price_min_date", "DATETIME")
        add_col("market_snapshots", "sell_price_max_date", "DATETIME")
        add_col("market_snapshots", "buy_price_min_date", "DATETIME")
        add_col("market_snapshots", "buy_price_max_date", "DATETIME")
        add_col("market_snapshots", "volume_24h", "INTEGER DEFAULT 0")
        add_col("market_snapshots", "quality", "INTEGER DEFAULT 1")
        add_col("market_snapshots", "data_age_seconds", "FLOAT DEFAULT 0.0")
        add_col("market_snapshots", "confidence_score", "FLOAT DEFAULT 1.0")
        add_col("market_snapshots", "coverage_suspect", "BOOLEAN DEFAULT 0")
        add_col("market_snapshots", "captured_at", "DATETIME")

        # 3.1 Black Market Snapshots
        add_col("black_market_snapshots", "captured_at_bucket", "DATETIME")

        # [CRITICAL] Create Unique Indexes for UPSERT
        try:
            conn.execute(
                text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_market_upsert 
                ON market_prices (item_id, city, quality, captured_at_bucket)
            """)
            )
            conn.execute(
                text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_bm_upsert 
                ON black_market_snapshots (item_id, quality, captured_at_bucket)
            """)
            )
            conn.commit()

            # Create hypertable for TimescaleDB if using PostgreSQL
            if not settings.database_url.startswith("sqlite"):
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
                    conn.execute(
                        text(
                            "SELECT create_hypertable('market_prices', 'captured_at', if_not_exists => TRUE);"
                        )
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()

        except Exception as e:
            conn.rollback()
            print(f"Migration Error (Indexes): {e}")

        # 4. Arbitrage
        add_col("arbitrage_opportunities", "ev_score", "FLOAT DEFAULT 0.0")
        add_col("arbitrage_opportunities", "volatility", "FLOAT DEFAULT 0.0")
        add_col("arbitrage_opportunities", "z_score", "FLOAT DEFAULT 0.0")
        add_col("arbitrage_opportunities", "persistence", "INTEGER DEFAULT 1")
        add_col("arbitrage_opportunities", "volume_source", 'VARCHAR DEFAULT "ESTIMATED"')
        add_col("arbitrage_opportunities", "safe_limit", "INTEGER DEFAULT 1")
        add_col("arbitrage_opportunities", "current_supply", "INTEGER DEFAULT 0")
        add_col("arbitrage_opportunities", "market_gap", "INTEGER DEFAULT 0")
        add_col("arbitrage_opportunities", "expected_hourly_profit", "FLOAT DEFAULT 0.0")

        # 5. Crafting
        add_col("crafting_opportunities", "ev_score", "FLOAT DEFAULT 0.0")
        add_col("crafting_opportunities", "z_score", "FLOAT DEFAULT 0.0")
        add_col("crafting_opportunities", "persistence", "INTEGER DEFAULT 1")
        add_col("crafting_opportunities", "ingredients_json", "TEXT")
        add_col("crafting_opportunities", "decision_log", "TEXT")

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
