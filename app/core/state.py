"""
Global application state to avoid circular imports.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.workers.scheduler import QuantScheduler

# Shared scheduler instance
scheduler_instance: "QuantScheduler | None" = None

# Global tier lock (None means all tiers are enabled)
tier_lock: int | None = None

# Standby mode — system boots paused, !start activates
standby_mode: bool = True

# Dynamic thresholds
min_bm_profit: int = 5000
min_craft_profit: int = 1000
allow_enchant_transport: bool = True
crafting_local_sourcing_only: bool = True
refining_local_sourcing_only: bool = False

# Discord alert broadcasting toggle (Master ON/OFF switch - starts OFF by default)
discord_alerts_enabled: bool = False

# Dismissed / Filled tracking
# Standard 15-minute temporary dismissals for royal/crafting: { item_id_upper: expiry_timestamp }
dismissed_opportunities: dict[str, float] = {}

# Persistent Black Market Filled Buy Orders tracking:
# { f"{item_id_upper}:{quality}": { "filled_at": timestamp, "data_age_bm": int, "bm_price": int, "bm_ts": datetime|None } }
filled_bm_orders: dict[str, dict] = {}

