"""
Core configuration module.
Loads environment variables and provides typed settings for the entire system.
"""

from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env file
load_dotenv()

class AlbionServer(str, Enum):
    AMERICAS = "west"
    ASIA     = "east"
    EUROPE   = "europe"

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PARSED_DIR = DATA_DIR / "parsed"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
CACHE_DIR = DATA_DIR / "cache"

# Ensure data directories exist
for d in [DATA_DIR, RAW_DIR, PARSED_DIR, SNAPSHOTS_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = Field(
        default=f"sqlite:///{DATA_DIR / 'albion_quant.db'}",
        alias="DATABASE_URL",
    )

    # Albion API
    albion_api_base: str = Field(
        default="https://europe.albion-online-data.com",
        alias="ALBION_API_BASE",
    )
    albion_api_server: str = Field(default="europe", alias="ALBION_API_SERVER")
    active_server: AlbionServer = Field(default=AlbionServer.EUROPE, alias="ACTIVE_SERVER")

    # AODP Regional Hosts
    aodp_base_urls: dict = {
        AlbionServer.AMERICAS: "https://west.albion-online-data.com",
        AlbionServer.ASIA:     "https://east.albion-online-data.com",
        AlbionServer.EUROPE:   "https://europe.albion-online-data.com",
    }

    # AODP Rate Limits
    aodp_rate_limit_per_minute: int = 180
    aodp_rate_limit_per_5_min: int = 750
    aodp_use_gzip: bool = True

    # Discord
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")

    # Trading Parameters
    min_arbitrage_margin: float = Field(default=5.0, alias="MIN_ARBITRAGE_MARGIN")
    min_arbitrage_profit: int = Field(default=2000, alias="MIN_ARBITRAGE_PROFIT")
    min_crafting_profit: int = Field(default=500, alias="MIN_CRAFTING_PROFIT")
    min_crafting_margin: float = Field(default=3.0, alias="MIN_CRAFTING_MARGIN")
    min_volume: int = Field(default=5, alias="MIN_VOLUME")
    target_exit_hours: float = Field(default=4.0, alias="TARGET_EXIT_HOURS")
    max_capital_per_trade: int = Field(default=2000000, alias="MAX_CAPITAL_PER_TRADE")
    max_crafting_capital: int = Field(default=2000000, alias="MAX_CRAFTING_CAPITAL")

    # Market Constants
    premium_tax_rate: float = Field(default=0.04, alias="PREMIUM_TAX_RATE")
    non_premium_tax_rate: float = Field(default=0.08, alias="NON_PREMIUM_TAX_RATE")
    setup_fee_rate: float = Field(default=0.025, alias="SETUP_FEE_RATE")
    is_premium: bool = Field(default=True, alias="IS_PREMIUM")

    # [NEW] Market fee constants (Albion Online Wiki — Marketplace, 2026)
    market_setup_fee_pct: float = 0.025
    market_tax_premium_pct: float = 0.04
    market_tax_non_premium_pct: float = 0.08
    crafting_station_fee_default: float = 0.03
    confidence_floor: float = 0.20

    # Scheduler Intervals (minutes)
    market_poll_interval: int = Field(
        default=5, alias="MARKET_POLL_INTERVAL_MINUTES"
    )
    arbitrage_compute_interval: int = Field(
        default=10, alias="ARBITRAGE_COMPUTE_INTERVAL_MINUTES"
    )
    crafting_compute_interval: int = Field(
        default=10, alias="CRAFTING_COMPUTE_INTERVAL_MINUTES"
    )
    snapshot_interval: int = Field(
        default=60, alias="SNAPSHOT_INTERVAL_MINUTES"
    )
    volume_refresh_interval: int = Field(
        default=60, alias="VOLUME_REFRESH_INTERVAL_MINUTES"
    )
    market_data_retention_days: int = Field(
        default=7, alias="MARKET_DATA_RETENTION_DAYS"
    )
    alert_limit_per_cycle: int = Field(
        default=5, alias="ALERT_LIMIT_PER_CYCLE"
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # When true, API lifespan skips scheduler, Discord bot, and startup collection (used by tests / CI).
    disable_background_tasks: bool = Field(
        default=False,
        alias="DISABLE_BACKGROUND_TASKS",
    )

    @property
    def tax_rate(self) -> float:
        """Returns the applicable tax rate based on premium status."""
        return self.premium_tax_rate if self.is_premium else self.non_premium_tax_rate

    @property
    def total_market_fee(self) -> float:
        """Total fee for a buy-and-sell cycle (2 setup fees + 1 sales tax)."""
        return (self.setup_fee_rate * 2) + self.tax_rate

    class Config:
        env_file = ".env"
        extra = "ignore"


# Singleton settings instance
settings = Settings()
