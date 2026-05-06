"""
Core configuration module.
Loads environment variables and provides typed settings for the entire system.
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env file
load_dotenv()

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
        default="https://west.albion-online-data.com",
        alias="ALBION_API_BASE",
    )
    albion_api_server: str = Field(default="west", alias="ALBION_API_SERVER")

    # Discord
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")

    # Trading Parameters
    min_arbitrage_margin: float = Field(default=12.0, alias="MIN_ARBITRAGE_MARGIN")
    min_arbitrage_profit: int = Field(default=10000, alias="MIN_ARBITRAGE_PROFIT")
    min_crafting_profit: int = Field(default=5000, alias="MIN_CRAFTING_PROFIT")
    min_volume: int = Field(default=5, alias="MIN_VOLUME")
    target_exit_hours: float = Field(default=4.0, alias="TARGET_EXIT_HOURS")
    max_capital_per_trade: int = Field(default=5000000, alias="MAX_CAPITAL_PER_TRADE")

    # Market Constants
    premium_tax_rate: float = Field(default=0.04, alias="PREMIUM_TAX_RATE")
    non_premium_tax_rate: float = Field(default=0.08, alias="NON_PREMIUM_TAX_RATE")
    setup_fee_rate: float = Field(default=0.025, alias="SETUP_FEE_RATE")
    is_premium: bool = Field(default=True, alias="IS_PREMIUM")

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
