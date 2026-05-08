# Stage 3 Replay Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Replay Engine (Section 11.1 of Roadmap) to reconstruct historical market states and replay signals.

**Architecture:** Create `research/replay/engine.py` and implement a class `ReplayEngine` that connects to the SQLite database `data/albion_quant.db` (or Postgres if available) and yields market states chronologically.

---

### Task 1: Implement ReplayEngine

**Files:**
- Create: `research/replay/engine.py`
- Create: `tests/research/test_replay_engine.py`

**Step 1: Create failing test**

Create `tests/research/test_replay_engine.py` with tests for yielding market states in chronological order.

**Step 2: Implement ReplayEngine**

Create `research/replay/engine.py` with a class `ReplayEngine`.
It should have a method `replay_iterator(self, start_time, end_time)` that yields market states.
It should read from `data/albion_quant.db` (SQLite) as the source of truth for now, given the 919MB file size.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_replay_engine.py`

**Step 4: Commit**

```bash
git add research/replay/engine.py tests/research/test_replay_engine.py
git commit -m "feat: implement replay engine skeleton"
```
