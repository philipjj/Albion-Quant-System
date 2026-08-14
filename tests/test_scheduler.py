import asyncio

import pytest
from app.workers.scheduler import QuantScheduler


@pytest.mark.asyncio
async def test_cycle_lock():
    # Bypass __init__ to avoid heavy initialization
    original_init = QuantScheduler.__init__
    QuantScheduler.__init__ = lambda self: None

    try:
        sched = QuantScheduler()
        sched._cycle_running = True  # Simulate that a cycle is already running
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
    from unittest.mock import AsyncMock, MagicMock

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

        assert hasattr(sched, "_loop_task")
        assert sched._loop_task is not None

        # Cleanup
        sched.stop()
    finally:
        QuantScheduler.__init__ = original_init


@pytest.mark.asyncio
async def test_master_cycle_unpacks_8_scan_all_returns():
    from unittest.mock import AsyncMock, MagicMock

    original_init = QuantScheduler.__init__
    QuantScheduler.__init__ = lambda self: None

    try:
        sched = QuantScheduler()
        sched._cycle_running = False
        sched._stop_requested = False
        sched._current_partition = 0
        sched._alert_history = {}

        # Mock collector and scanner
        sched.collector = MagicMock()
        sched.collector._stop_requested = False
        sched.collector.collect_partition = AsyncMock(return_value=10)

        sched.unified_scanner = MagicMock()
        # scan_all returns 8 lists
        sched.unified_scanner.scan_all = AsyncMock(return_value=([], [], [], [], [], [], [], []))

        sched.alerter = MagicMock()
        sched.alerter.send_batch_alerts = AsyncMock()

        # Run cycle
        await sched.master_cycle()

        assert sched.unified_scanner.scan_all.called
        assert sched._current_partition == 1
    finally:
        QuantScheduler.__init__ = original_init
