# Stage 3 Calibration Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Calibration Framework (Section 11.2 of Roadmap) to empirically validate probabilities.

**Architecture:** Create `research/calibration/validator.py` and implement a class `ProbabilityCalibrator` that calculates calibration metrics (e.g., Brier score, expected vs realized frequencies).

---

### Task 1: Implement ProbabilityCalibrator

**Files:**
- Create: `research/calibration/validator.py`
- Create: `tests/research/test_calibration.py`

**Step 1: Create failing test**

Create `tests/research/test_calibration.py` with tests for calculating Brier score and calibration error.

**Step 2: Implement ProbabilityCalibrator**

Create `research/calibration/validator.py` with a class `ProbabilityCalibrator`.
Methods:
- `calculate_brier_score(predictions, outcomes)`
- `calculate_calibration_error(predictions, outcomes, bins=10)`

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_calibration.py`

**Step 4: Commit**

```bash
git add research/calibration/validator.py tests/research/test_calibration.py
git commit -m "feat: implement probability calibrator"
```
