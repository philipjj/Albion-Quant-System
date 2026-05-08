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
RUNTIME_DIR = PROJECT_ROOT / "runtime"
DATA_DIR = RUNTIME_DIR # Fallback for backward compatibility
CACHE_DIR = RUNTIME_DIR / "cache"
DB_DIR = RUNTIME_DIR / "databases"
HISTORICAL_DIR = RUNTIME_DIR / "historical"
LOGS_DIR = RUNTIME_DIR / "logs"
PARQUET_DIR = RUNTIME_DIR / "parquet"
REPORTS_DIR = RUNTIME_DIR / "reports"
SNAPSHOTS_DIR = RUNTIME_DIR / "snapshots"
TMP_DIR = RUNTIME_DIR / "tmp"

# Ensure runtime directories exist
for d in [RUNTIME_DIR, CACHE_DIR, DB_DIR, HISTORICAL_DIR, LOGS_DIR, PARQUET_DIR, REPORTS_DIR, SNAPSHOTS_DIR, TMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

import yaml

def _load_yaml_parameters() -> dict:
    """Loads parameters from configs/research/parameters.yaml if it exists."""
    param_path = PROJECT_ROOT / "configs" / "research" / "parameters.yaml"
    if param_path.exists():
        try:
            with open(param_path, "r") as f:
                data = yaml.safe_load(f)
                return data or {}
        except Exception as e:
            print(f"Error loading parameters.yaml: {e}")
    return {}

_params = _load_yaml_parameters()
_thresholds = _params.get("thresholds", {})


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = Field(
        default=f"sqlite:///{DB_DIR / 'aqs.sqlite'}",
        alias="DATABASE_URL",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
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
    min_arbitrage_margin: float = Field(default=_thresholds.get("min_arbitrage_margin", 5.0), alias="MIN_ARBITRAGE_MARGIN")
    min_arbitrage_profit: int = Field(default=_thresholds.get("min_arbitrage_profit", 2000), alias="MIN_ARBITRAGE_PROFIT")
    min_crafting_profit: int = Field(default=_thresholds.get("min_crafting_profit", 500), alias="MIN_CRAFTING_PROFIT")
    min_crafting_margin: float = Field(default=_thresholds.get("min_crafting_margin", 3.0), alias="MIN_CRAFTING_MARGIN")
    min_volume: int = Field(default=_thresholds.get("min_volume", 5), alias="MIN_VOLUME")
    target_exit_hours: float = Field(default=_thresholds.get("target_exit_hours", 4.0), alias="TARGET_EXIT_HOURS")
    max_capital_per_trade: int = Field(default=_thresholds.get("max_capital_per_trade", 2000000), alias="MAX_CAPITAL_PER_TRADE")
    max_crafting_capital: int = Field(default=_thresholds.get("max_crafting_capital", 2000000), alias="MAX_CRAFTING_CAPITAL")

    # Market Constants
    premium_tax_rate: float = Field(default=0.04, alias="PREMIUM_TAX_RATE")
    non_premium_tax_rate: float = Field(default=0.08, alias="NON_PREMIUM_TAX_RATE")
    setup_fee_rate: float = Field(default=0.025, alias="SETUP_FEE_RATE")
    is_premium: bool = Field(default=True, alias="IS_PREMIUM")

    # [NEW] Market fee constants (Albion Online Wiki — Marketplace, 2026)
    market_setup_fee_pct: float = _thresholds.get("market_setup_fee_pct", 0.025)
    market_tax_premium_pct: float = _thresholds.get("market_tax_premium_pct", 0.04)
    market_tax_non_premium_pct: float = _thresholds.get("market_tax_non_premium_pct", 0.08)
    crafting_station_fee_default: float = _thresholds.get("crafting_station_fee_default", 0.03)
    confidence_floor: float = _thresholds.get("confidence_floor", 0.20)

    # Signal Defaults
    volatility_default_confidence: float = _params.get("signals", {}).get("volatility", {}).get("default_confidence", 0.5)
    volatility_default_persistence: float = _params.get("signals", {}).get("volatility", {}).get("default_persistence", 0.4)
    volatility_default_manipulation_risk: float = _params.get("signals", {}).get("volatility", {}).get("default_manipulation_risk", 0.3)

    # Imbalance Signal Defaults
    imbalance_default_confidence: float = _params.get("signals", {}).get("imbalance", {}).get("default_confidence", 0.8)
    imbalance_default_persistence: float = _params.get("signals", {}).get("imbalance", {}).get("default_persistence", 0.5)
    imbalance_default_manipulation_risk: float = _params.get("signals", {}).get("imbalance", {}).get("default_manipulation_risk", 0.1)

    # Liquidity Gap Signal Defaults
    liquidity_gap_default_confidence: float = _params.get("signals", {}).get("liquidity_gap", {}).get("default_confidence", 0.6)
    liquidity_gap_default_persistence: float = _params.get("signals", {}).get("liquidity_gap", {}).get("default_persistence", 0.5)
    liquidity_gap_default_manipulation_risk: float = _params.get("signals", {}).get("liquidity_gap", {}).get("default_manipulation_risk", 0.2)

    # Scarcity Signal Defaults
    scarcity_default_confidence: float = _params.get("signals", {}).get("scarcity", {}).get("default_confidence", 0.7)
    scarcity_default_persistence: float = _params.get("signals", {}).get("scarcity", {}).get("default_persistence", 0.8)
    scarcity_default_manipulation_risk: float = _params.get("signals", {}).get("scarcity", {}).get("default_manipulation_risk", 0.2)

    # Substitution Signal Defaults
    substitution_default_confidence: float = _params.get("signals", {}).get("substitution", {}).get("default_confidence", 0.6)
    substitution_default_persistence: float = _params.get("signals", {}).get("substitution", {}).get("default_persistence", 0.6)
    substitution_default_manipulation_risk: float = _params.get("signals", {}).get("substitution", {}).get("default_manipulation_risk", 0.1)

    # Arbitrage Parameters
    arb_distance_weight: float = _params.get("arbitrage", {}).get("risk", {}).get("distance_weight", 10.0)
    arb_danger_multiplier: float = _params.get("arbitrage", {}).get("risk", {}).get("danger_multiplier", 2.5)
    arb_value_divisor: float = _params.get("arbitrage", {}).get("risk", {}).get("value_divisor", 100000.0)
    arb_value_weight: float = _params.get("arbitrage", {}).get("risk", {}).get("value_weight", 5.0)
    arb_regular_hours: float = _params.get("arbitrage", {}).get("lookback", {}).get("regular_hours", 2.0)
    arb_bm_hours: float = _params.get("arbitrage", {}).get("lookback", {}).get("black_market_hours", 4.0)
    arb_default_volatility: float = _params.get("arbitrage", {}).get("default_volatility", 0.05)

    # Crafting Parameters
    crafting_lookback_hours: float = _params.get("crafting", {}).get("lookback_hours", 24.0)
    crafting_max_depth: int = _params.get("crafting", {}).get("max_depth", 2)
    crafting_default_tier: int = _params.get("crafting", {}).get("default_tier", 4)
    crafting_max_rrr: float = _params.get("crafting", {}).get("max_rrr", 0.99)
    crafting_default_volatility: float = _params.get("crafting", {}).get("default_volatility", 0.05)

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
