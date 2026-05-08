# Stage 3 Regime Engine Completion Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the Regime Engine (Section 12 of Roadmap) by adding missing files.

**Architecture:** Add to `app/regime/`: `trend_regime.py`, `manipulation.py`, and `classifier.py`.

---

### Task 1: Implement trend_regime.py

**Files:**
- Create: `app/regime/trend_regime.py`
- Create: `tests/app/test_trend_regime.py`

**Step 1: Create failing test**

Create `tests/app/test_trend_regime.py` with tests for detecting trending vs ranging markets.

**Step 2: Implement trend_regime**

Create `app/regime/trend_regime.py` with a function `detect_trend_regime`.
Inputs: `prices` (List[float]).
Output: `str` ('trending' or 'ranging').

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/app/test_trend_regime.py`

**Step 4: Commit**

```bash
git add app/regime/trend_regime.py tests/app/test_trend_regime.py
git commit -m "feat: implement trend regime detector"
```

---

### Task 2: Implement manipulation.py

**Files:**
- Create: `app/regime/manipulation.py`
- Create: `tests/app/test_manipulation.py`

**Step 1: Create failing test**

Create `tests/app/test_manipulation.py` with tests for detecting spoofing or manipulation.

**Step 2: Implement manipulation**

Create `app/regime/manipulation.py` with a function `detect_manipulation`.
Inputs: `order_book_snapshots` (List[Dict]).
Output: `bool` (True if manipulation detected).

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/app/test_manipulation.py`

**Step 4: Commit**

```bash
git add app/regime/manipulation.py tests/app/test_manipulation.py
git commit -m "feat: implement manipulation detector"
```
