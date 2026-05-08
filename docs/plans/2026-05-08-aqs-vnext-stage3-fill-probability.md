# Stage 3 Fill Probability Modeling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement fill probability modeling (Section 10.2 of Roadmap) to estimate the likelihood of an order being filled.

**Architecture:** Create `app/simulation/fill_probability.py` and implement a function `calculate_fill_probability` that takes market features and returns a probability (0.0 to 1.0).

---

### Task 1: Implement calculate_fill_probability

**Files:**
- Create: `app/simulation/fill_probability.py`
- Create: `tests/app/test_fill_probability.py`

**Step 1: Create failing test**

Create `tests/app/test_fill_probability.py` with tests for high/low probability scenarios based on inputs like imbalance and volatility.

**Step 2: Implement model**

Create `app/simulation/fill_probability.py` with a heuristic or logistic model for `calculate_fill_probability`.
Inputs: `imbalance` (float), `volatility` (float), `spread` (float), `volume` (float).
Output: `P_fill` (float).

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/app/test_fill_probability.py`

**Step 4: Commit**

```bash
git add app/simulation/fill_probability.py tests/app/test_fill_probability.py
git commit -m "feat: implement fill probability modeling"
```
