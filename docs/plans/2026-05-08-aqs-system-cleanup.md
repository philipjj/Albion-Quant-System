# System Cleanup and Integration Test Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a single integration test for the whole system, remove legacy code, and update `.gitignore`.

---

### Task 1: Create Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Implement Test**

Create a test that uses `ReplayEngine` (mock or small DB) and `BacktestEngine` to run a full loop and verify metrics are generated.
This will test Replay, Backtesting, and Metrics in one go!

**Step 2: Run the test**

Run: `venv\Scripts\python -m pytest tests/test_integration.py`

---

### Task 2: Identify and Remove Legacy Code

**Step 1: Search for old/deprecated code**

Look for files mentioned in the roadmap as "legacy" or "heuristic-based" that we replaced.
We implemented new logic in `app/simulation/` and `app/regime/`.
Let's check if there are old files in `app/` that we can remove or if the user wants to keep them.
The user said "remove legacy/depricated old code".
I'll check for files with "old" or "v1" or similar in their names, or files that implement logic we just replaced.
I'll search for files that might be deprecated.

---

### Task 3: Update .gitignore

**Files:**
- Update: `.gitignore`

**Step 1: Add entries**

Add `data/albion_quant.db` (if not ignored) and `tests/**/*.db` to `.gitignore`.

**Step 2: Commit**

```bash
git add .
git commit -m "chore: add integration test, clean up legacy code, and update .gitignore"
```
