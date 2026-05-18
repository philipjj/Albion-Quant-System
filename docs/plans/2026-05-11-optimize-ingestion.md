# Optimize Ingestion and Add Cycle Lock Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Speed up batch processing in the collector and ensure previous cycles are done before starting new ones in the scheduler.

**Architecture:** 
1. Reduce the mandatory sleep in `MarketCollector.collect_partition` from 2.5s to 0.5s to rely on the `DeterministicRateLimiter` for spacing, while avoiding excessive event loop spinning.
2. Add a `_cycle_running` boolean flag in `QuantScheduler` to prevent `master_cycle` from running if a previous instance is still active.

**Tech Stack:** Python, APScheduler, asyncio.

---

### Task 1: Add Cycle Lock in Scheduler

**Files:**
- Modify: `app/workers/scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write the failing test**
Create `tests/test_scheduler.py` to verify that `master_cycle` skips execution and does not increment the partition index if a cycle is already running.

```python
import pytest
import asyncio
from app.workers.scheduler import QuantScheduler

@pytest.mark.asyncio
async def test_cycle_lock():
    sched = QuantScheduler()
    sched._cycle_running = True # Simulate that a cycle is already running
    
    initial_part = sched._current_partition
    await sched.master_cycle()
    
    # If the lock works, the cycle should abort early and NOT increment the partition
    assert sched._current_partition == initial_part
```

**Step 2: Run test to verify it fails**
Run: `pytest tests/test_scheduler.py`
Expected: FAIL (AttributeError: 'QuantScheduler' object has no attribute '_cycle_running')

**Step 3: Write minimal implementation**
Modify `app/workers/scheduler.py`:
- Initialize `self._cycle_running = False` in `__init__`.
- Add the check at the start of `master_cycle`:

```python
    async def master_cycle(self):
        if self._cycle_running:
            log.warning("[SCHEDULER] Master cycle already running. Skipping this run.")
            return
        
        self._cycle_running = True
        try:
            # ... existing code ...
        finally:
            self._cycle_running = False
```

**Step 4: Run test to verify it passes**
Run: `pytest tests/test_scheduler.py`
Expected: PASS

**Step 5: Commit**
```bash
git add app/workers/scheduler.py tests/test_scheduler.py
git commit -m "feat: add cycle lock to prevent overlapping runs"
```

---

### Task 2: Optimize Batch Processing in Collector

**Files:**
- Modify: `app/ingestion/collector.py`

**Step 1: Write a smoke test**
Create `tests/test_collector.py` to ensure `collect_partition` still runs without errors after our change.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.ingestion.collector import MarketCollector

@pytest.mark.asyncio
async def test_collect_partition_smoke():
    collector = MarketCollector(
        repository=MagicMock(), 
        parquet_storage=MagicMock(), 
        redis_cache=MagicMock()
    )
    # Mock fetch_market_data to avoid real API calls
    collector.fetch_market_data = AsyncMock(return_value=[])
    
    # Should run and return 0 batches (since mock returns empty)
    result = await collector.collect_partition(0, 6)
    assert result == 0 or result is None
```

**Step 2: Run test to verify it passes (Regression check)**
Run: `pytest tests/test_collector.py`
Expected: PASS

**Step 3: Write minimal implementation**
Modify `app/ingestion/collector.py` around line 557:
Change `await asyncio.sleep(2.5)` to `await asyncio.sleep(0.5)`.

**Step 4: Run tests again to verify no regression**
Run: `pytest tests/test_collector.py`
Expected: PASS

**Step 5: Commit**
```bash
git add app/ingestion/collector.py tests/test_collector.py
git commit -m "perf: reduce batch sleep time in collector from 2.5s to 0.5s"
```
