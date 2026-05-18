# Continuous Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run `master_cycle` continuously (start next partition as soon as previous is done) instead of waiting for a fixed interval.

**Architecture:** 
Instead of scheduling `master_cycle` via APScheduler's `IntervalTrigger`, we will start it as a background asyncio task in `QuantScheduler.start()`. This task will run a `while True` loop that calls `master_cycle()` and then a small pause (e.g., 1 second) to prevent CPU spinning, relying on the lock we added to prevent overlaps if needed, but primarily just running them back-to-back.

**Tech Stack:** Python, asyncio.

---

### Task 1: Refactor Scheduler for Continuous Execution

**Files:**
- Modify: `app/workers/scheduler.py`

**Step 1: Write minimal implementation**
Modify `app/workers/scheduler.py`:
- In `start(self)`, remove the `master_cycle` job from `self.scheduler.add_job`.
- Add a dedicated async loop method:
```python
    async def _continuous_cycle_loop(self):
        log.info("[SCHEDULER] Starting continuous cycle loop.")
        while self._is_running:
            await self.master_cycle()
            await asyncio.sleep(1) # Small pause between cycles
```
- In `start(self)`, start this loop as a task:
```python
        self._loop_task = asyncio.create_task(self._continuous_cycle_loop())
```
- In `stop(self)` and `shutdown(self)`, cancel the task:
```python
        if hasattr(self, '_loop_task') and self._loop_task:
            self._loop_task.cancel()
```

**Step 2: Verify visually or with smoke test**
Since we don't have a specific test for the loop timing, we will verify that the tests still pass and the code structure is correct.

---

### Task 2: Update Tests for Continuous Execution

**Files:**
- Modify: `tests/test_scheduler.py`

**Step 1: Update the test**
The previous test `test_cycle_lock` manually called `master_cycle`. It should still work because `master_cycle` still has the lock logic!
We should add a test to verify that `start()` creates the loop task.

```python
@pytest.mark.asyncio
async def test_scheduler_start_creates_task():
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
```

**Step 2: Run tests to verify they pass**
Run: `pytest tests/test_scheduler.py`
Expected: PASS

**Step 3: Commit**
```bash
git add app/workers/scheduler.py tests/test_scheduler.py
git commit -m "feat: change scheduler to run master cycle continuously"
```
