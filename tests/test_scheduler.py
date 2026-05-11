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


@pytest.mark.asyncio
async def test_scheduler_start_creates_task():
    from unittest.mock import MagicMock, AsyncMock
    # Bypass __init__ to avoid heavy initialization
    original_init = QuantScheduler.__init__
    QuantScheduler.__init__ = lambda self: None
    
    try:
        sched = QuantScheduler()
        sched.scheduler = MagicMock()
        sched._is_running = False
        sched.collector = MagicMock()
        
        # Mock master_cycle to avoid running it
        sched.master_cycle = AsyncMock()
        
        sched.start()
        
        assert hasattr(sched, '_loop_task')
        assert sched._loop_task is not None
        
        # Cleanup
        sched.stop()
    finally:
        QuantScheduler.__init__ = original_init
