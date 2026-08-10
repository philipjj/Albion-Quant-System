"""
Global application state to avoid circular imports.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workers.scheduler import QuantScheduler

# Shared scheduler instance
scheduler_instance: "QuantScheduler | None" = None

# Global tier lock (None means all tiers are enabled)
tier_lock: int | None = None

# Standby mode — system boots paused, !start activates
standby_mode: bool = True

# Dynamic thresholds
min_bm_profit: int = 5000
min_craft_profit: int = 1000
allow_enchant_transport: bool = False
