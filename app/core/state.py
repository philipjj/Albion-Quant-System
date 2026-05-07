"""
Global application state to avoid circular imports.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workers.scheduler import QuantScheduler

# Shared scheduler instance
scheduler_instance: "QuantScheduler | None" = None
