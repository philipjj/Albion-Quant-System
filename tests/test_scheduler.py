import pytest
import asyncio
from app.workers.scheduler import QuantScheduler

@pytest.mark.asyncio
async def test_cycle_lock():
    # Bypass __init__ to avoid heavy initialization
    original_init = QuantScheduler.__init__
    QuantScheduler.__init__ = lambda self: None
    
    try:
        sched = QuantScheduler()
        sched._cycle_running = True # Simulate that a cycle is already running
        sched._current_partition = 0
        
        initial_part = sched._current_partition
        await sched.master_cycle()
        
        # If the lock works, the cycle should abort early and NOT increment the partition
        assert sched._current_partition == initial_part
    finally:
        # Restore __init__
        QuantScheduler.__init__ = original_init
