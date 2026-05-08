# AQS vNext Stage 1: Split Core Monolith Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the core monolith in `app/core` into smaller, testable functions in `shared/` and refactor them to use the new domain models. Fix the `risk_multiplier` bug in `scoring.py`.

**Architecture:**
- Move math/utility functions from `app/core/market_utils.py` to `shared/utils/market.py`.
- Move scoring logic from `app/core/scoring.py` to `shared/domain/scoring.py`, refactoring to use `Signal`, `Opportunity`, and `Alpha` models.

**Tech Stack:** Python 3.10+, Pydantic v2

---

### Task 1: Move Market Utilities to Shared

**Files:**
- Create: `shared/utils/market.py`
- Create: `tests/shared/test_market_utils.py`

**Step 1: Write the failing test**

Create `tests/shared/test_market_utils.py` testing `calculate_rrr` and `calculate_blended_price`.

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/shared/test_market_utils.py`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

Copy functions from `app/core/market_utils.py` to `shared/utils/market.py`. Ensure `CITY_BONUS` and constants are also moved or referenced.

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/shared/test_market_utils.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/utils/market.py tests/shared/test_market_utils.py
git commit -m "feat: move market utilities to shared"
```

---

### Task 2: Refactor Scoring Logic to Use Domain Models

**Files:**
- Create: `shared/domain/scoring.py`
- Create: `tests/shared/test_scoring.py`

**Step 1: Write the failing test**

Create `tests/shared/test_scoring.py` testing `derive_opportunity` and `derive_alpha`.

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/shared/test_scoring.py`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

In `shared/domain/scoring.py`:
- Implement `calculate_data_confidence(signal: Signal) -> float`
- Implement `calculate_fill_probability(volume_24h: int, margin_pct: float) -> float`
- Implement `derive_opportunity(signal: Signal, market_data: dict) -> Opportunity`
- Implement `derive_alpha(opportunity: Opportunity) -> Alpha`

**Fix the Bug**: Define `risk_multiplier = 2.0` if route is in `DANGEROUS_ROUTES` else `1.0`.

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/shared/test_scoring.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/domain/scoring.py tests/shared/test_scoring.py
git commit -m "feat: refactor scoring logic to use domain models and fix risk_multiplier bug"
```
