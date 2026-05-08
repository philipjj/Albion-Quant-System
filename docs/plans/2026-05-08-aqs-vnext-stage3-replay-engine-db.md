# Stage 3 Replay Engine DB Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement database query logic in the Replay Engine to read from the SQLite database.

**Architecture:** Update `research/replay/engine.py` to connect to `data/albion_quant.db` and yield rows ordered by `captured_at`.

---

### Task 1: Implement SQLite query in ReplayEngine

**Files:**
- Update: `research/replay/engine.py`
- Update: `tests/research/test_replay_engine.py`

**Step 1: Update tests**

Update `tests/research/test_replay_engine.py` to test the database branch (if we can mock the DB or just verify it raises the right error if DB missing).
Actually, since we have a 919MB DB file, we can test it with real data if we limit the query!
Or we can use a mock DB connection.
Let's use a mock DB connection or a small test DB to avoid reading 919MB in tests!
I'll update the test to use a temporary SQLite file for testing.

**Step 2: Implement DB query**

Update `research/replay/engine.py` to use `sqlite3` and query `market_prices` table.
Yield dictionaries or objects.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_replay_engine.py`

**Step 4: Commit**

```bash
git add research/replay/engine.py tests/research/test_replay_engine.py
git commit -m "feat: integrate SQLite source in replay engine"
```
