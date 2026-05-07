"""
SQLAlchemy database models for the Albion Quant Trading System.
Covers items, recipes, market prices, and opportunity tracking.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class Item(Base):
    """Static item data parsed from ao-bin-dumps."""
    __tablename__ = "items"

    item_id = Column(String(128), primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    tier = Column(Integer, nullable=True)
    enchant = Column(Integer, default=0)
    category = Column(String(64), nullable=True)
    subcategory = Column(String(64), nullable=True)
    shop_category = Column(String(64), nullable=True)
    shop_subcategory = Column(String(64), nullable=True)
    weight = Column(Float, default=0.0)
    max_stack = Column(Integer, default=999)
    item_value = Column(Float, default=0.0) # Game internal value for tax/fees
    is_craftable = Column(Boolean, default=False)

    # Relationships
    crafted_recipes = relationship(
        "Recipe",
        back_populates="crafted_item",
        foreign_keys="Recipe.crafted_item_id",
    )

    def __repr__(self):
        return f"<Item {self.item_id} ({self.name})>"


class Recipe(Base):
    """Crafting recipe ingredients."""
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    crafted_item_id = Column(
        String(128),
        ForeignKey("items.item_id"),
        nullable=False,
        index=True,
    )
    ingredient_item_id = Column(String(128), nullable=False, index=True)
    quantity = Column(Float, nullable=False)

    # Crafting metadata
    crafting_station = Column(String(64), nullable=True)
    nutrition_cost = Column(Float, default=0.0)
    focus_cost = Column(Float, default=0.0)
    crafting_fame = Column(Float, default=0.0)

    # Relationships
    crafted_item = relationship(
        "Item",
        back_populates="crafted_recipes",
        foreign_keys=[crafted_item_id],
    )

    __table_args__ = (
        Index("ix_recipe_crafted_ingredient", "crafted_item_id", "ingredient_item_id"),
    )

    def __repr__(self):
        return f"<Recipe {self.crafted_item_id} <- {self.quantity}x {self.ingredient_item_id}>"


class MarketPrice(Base):
    """Live market price snapshots from the Albion Data API."""
    __tablename__ = "market_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(128), nullable=False, index=True)
    city = Column(String, nullable=False)
    server = Column(String, nullable=False, default="west")
    sell_price_min = Column(BigInteger)
    sell_price_max = Column(BigInteger)
    buy_price_min = Column(BigInteger)
    buy_price_max = Column(BigInteger)
    sell_price_min_date = Column(DateTime)
    sell_price_max_date = Column(DateTime)
    buy_price_min_date = Column(DateTime)
    buy_price_max_date = Column(DateTime)
    
    # [NEW] Derived from history endpoint
    volume_24h = Column(Integer, default=0)
    
    data_age_seconds = Column(Float)
    confidence_score = Column(Float, default=1.0)
    
    # [NEW] Coverage suspect flag
    coverage_suspect = Column(Boolean, default=False)
    
    quality = Column(Integer, default=1)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    captured_at_bucket = Column(DateTime, index=True)

    __table_args__ = (
        Index("ix_market_item_city", "item_id", "city"),
        Index("ix_market_fetched", "captured_at"),
        Index("ix_market_upsert", "item_id", "city", "quality", "captured_at_bucket", unique=True),
    )

    def __repr__(self):
        return f"<MarketPrice {self.item_id}@{self.city} sell={self.sell_price_min} buy={self.buy_price_max}>"


class MarketHistory(Base):
    """Historical sales volume data for liquidity analysis."""
    __tablename__ = "market_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(128), nullable=False, index=True)
    city = Column(String(32), nullable=False, index=True)
    quality = Column(Integer, default=1)
    item_count = Column(Integer, default=0)
    avg_price = Column(Float, default=0.0)
    timestamp = Column(DateTime, nullable=False, index=True)

    __table_args__ = (
        Index("ix_history_item_city_time", "item_id", "city", "timestamp"),
    )

    def __repr__(self):
        return f"<MarketHistory {self.item_id}@{self.city} count={self.item_count} at {self.timestamp}>"


class ArbitrageOpportunity(Base):
    """Detected arbitrage opportunities between cities."""
    __tablename__ = "arbitrage_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(128), nullable=False, index=True)
    item_name = Column(String(256), nullable=True)
    source_city = Column(String(32), nullable=False)
    destination_city = Column(String(32), nullable=False)
    buy_price = Column(Integer, nullable=False)
    sell_price = Column(Integer, nullable=False)
    estimated_profit = Column(Float, nullable=False)
    estimated_margin = Column(Float, nullable=False)
    risk_score = Column(Float, default=0.0)
    daily_volume = Column(Integer, default=0)
    volume_source = Column(String(32), default="ESTIMATED")
    safe_limit = Column(Integer, default=1)
    current_supply = Column(Integer, default=0)
    market_gap = Column(Integer, default=0)
    expected_hourly_profit = Column(Float, default=0.0)
    ev_score = Column(Float, default=0.0, index=True)
    volatility = Column(Float, default=0.0)
    z_score = Column(Float, default=0.0)
    persistence = Column(Integer, default=1)
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_arb_margin", "estimated_margin"),
        Index("ix_arb_profit", "estimated_profit"),
    )

    def __repr__(self):
        return (
            f"<Arbitrage {self.item_id}: {self.source_city}->{self.destination_city} "
            f"profit={self.estimated_profit} margin={self.estimated_margin}%>"
        )


class CraftingOpportunity(Base):
    """Detected crafting profit opportunities."""
    __tablename__ = "crafting_opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(128), nullable=False, index=True)
    item_name = Column(String(256), nullable=True)
    crafting_city = Column(String(32), nullable=False)
    sell_city = Column(String(32), nullable=True)
    craft_cost = Column(Float, nullable=False)
    sell_price = Column(Float, nullable=False)
    profit = Column(Float, nullable=False)
    profit_margin = Column(Float, nullable=False)
    focus_cost = Column(Float, default=0.0)
    profit_per_focus = Column(Float, default=0.0)
    silver_per_nutrition = Column(Float, default=0.0)
    journal_profit = Column(Float, default=0.0)
    daily_volume = Column(Integer, default=0)
    volume_source = Column(String(32), default="ESTIMATED")
    safe_limit = Column(Integer, default=1)
    current_supply = Column(Integer, default=0)
    market_gap = Column(Integer, default=0)
    ev_score = Column(Float, default=0.0, index=True)
    volatility = Column(Float, default=0.0)
    persistence = Column(Integer, default=1)
    ingredients_json = Column(Text, nullable=True)
    decision_log = Column(Text, nullable=True) # Recursive path decisions
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_craft_profit", "profit"),
        Index("ix_craft_margin", "profit_margin"),
    )

    def __repr__(self):
        return (
            f"<CraftingOpp {self.item_id}@{self.crafting_city} "
            f"profit={self.profit} margin={self.profit_margin}%>"
        )


class MarketSnapshot(Base):
    """Hourly market state snapshots for historical analysis."""
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True)
    item_id = Column(String, nullable=False, index=True)
    enchantment = Column(Integer, default=0)
    quality = Column(Integer, default=1)
    city = Column(String, nullable=False)
    server = Column(String, nullable=False)

    sell_price_min = Column(BigInteger, nullable=True)
    sell_price_max = Column(BigInteger, nullable=True)
    buy_price_min = Column(BigInteger, nullable=True)
    buy_price_max = Column(BigInteger, nullable=True)

    sell_price_min_date = Column(DateTime, nullable=True)
    sell_price_max_date = Column(DateTime, nullable=True)
    buy_price_min_date  = Column(DateTime, nullable=True)
    buy_price_max_date  = Column(DateTime, nullable=True)

    volume_24h = Column(Integer, nullable=True)
    data_age_seconds = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    coverage_suspect = Column(Boolean, default=False)

    quality = Column(Integer, default=1)
    captured_at = Column(DateTime, default=datetime.utcnow)

class BlackMarketSnapshot(Base):
    """Snapshot of Black Market buy orders."""
    __tablename__ = "black_market_snapshots"

    id = Column(Integer, primary_key=True)
    item_id = Column(String, nullable=False)
    enchantment = Column(Integer, default=0)
    quality = Column(Integer, default=1)
    
    buy_price_min = Column(BigInteger)
    buy_price_max = Column(BigInteger)
    buy_price_min_date = Column(DateTime)
    buy_price_max_date = Column(DateTime)
    
    data_age_seconds = Column(Float)
    confidence_score = Column(Float, default=1.0)
    captured_at = Column(DateTime, default=datetime.utcnow)
    captured_at_bucket = Column(DateTime, index=True)

    __table_args__ = (
        Index("ix_bm_upsert", "item_id", "quality", "captured_at_bucket", unique=True),
    )

class LiquidityConfidence(Base):
    """Historical liquidity confidence tracking."""
    __tablename__ = "liquidity_confidence"

    id = Column(Integer, primary_key=True)
    item_id = Column(String, nullable=False)
    city = Column(String, nullable=False)
    quality = Column(Integer, default=1)
    enchantment = Column(Integer, default=0)
    score = Column(Float, nullable=False)
    encryption_penalised = Column(Boolean, default=False)
    computed_at = Column(DateTime, default=datetime.utcnow)


class UserProfile(Base):
    """Per-user preferences for personalization (Discord + API clients)."""
    __tablename__ = "user_profiles"

    # Discord user id as stable key. (Also usable for API tokens later.)
    discord_user_id = Column(String(32), primary_key=True)

    # Preferences (defaults align to app.core.config settings).
    is_premium = Column(Boolean, default=True)
    home_city = Column(String(32), nullable=True)
    api_server = Column(String(16), nullable=True)  # west/europe/east

    # Risk/execution knobs.
    max_capital_per_trade = Column(Integer, nullable=True)
    target_exit_hours = Column(Float, nullable=True)
    min_arbitrage_margin = Column(Float, nullable=True)
    min_arbitrage_profit = Column(Integer, nullable=True)
    min_crafting_profit = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
