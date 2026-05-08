# Stage 3 Alpha Decay Modeling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement alpha decay modeling (Section 10.3 of Roadmap) to estimate signal lifetime and urgency.

**Architecture:** Create `app/simulation/alpha_decay.py` and implement a function `estimate_alpha_decay` that returns expected lifetime and decay rate.

---

### Task 1: Implement estimate_alpha_decay

**Files:**
- Create: `app/simulation/alpha_decay.py`
- Create: `tests/app/test_alpha_decay.py`

**Step 1: Create failing test**

Create `tests/app/test_alpha_decay.py` with tests for high/low decay scenarios based on volume and time.

**Step 2: Implement model**

Create `app/simulation/alpha_decay.py` with a function `estimate_alpha_decay`.
Inputs: `initial_strength` (float), `current_strength` (float), `elapsed_time` (seconds), `market_volume` (float).
Output: `Dict` with `expected_remaining_lifetime` and `decay_velocity`.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/app/test_alpha_decay.py`

**Step 4: Commit**

```bash
git add app/simulation/alpha_decay.py tests/app/test_alpha_decay.py
git commit -m "feat: implement alpha decay modeling"
```
