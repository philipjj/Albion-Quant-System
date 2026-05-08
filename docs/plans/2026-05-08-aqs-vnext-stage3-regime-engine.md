# Stage 3 Regime Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Regime Engine (Section 12 of Roadmap) to detect market states.

**Architecture:** Add missing files to `app/regime/`: `liquidity_regime.py`, `manipulation.py`, `trend_regime.py`, and `classifier.py`.

---

### Task 1: Implement liquidity_regime.py

**Files:**
- Create: `app/regime/liquidity_regime.py`
- Create: `tests/app/test_liquidity_regime.py`

**Step 1: Create failing test**

Create `tests/app/test_liquidity_regime.py` with tests for detecting illiquid vs liquid regimes.

**Step 2: Implement liquidity_regime**

Create `app/regime/liquidity_regime.py` with a function `detect_liquidity_regime`.
Inputs: `volumes` (List[float]), `threshold` (float).
Output: `str` ('liquid' or 'illiquid').

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/app/test_liquidity_regime.py`

**Step 4: Commit**

```bash
git add app/regime/liquidity_regime.py tests/app/test_liquidity_regime.py
git commit -m "feat: implement liquidity regime detector"
```
