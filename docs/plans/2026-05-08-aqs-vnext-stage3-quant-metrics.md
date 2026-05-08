# Stage 3 Quant Metrics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement Quant Metrics (Section 11.3 of Roadmap) to evaluate signal and execution quality.

**Architecture:** Create `research/diagnostics/metrics.py` and implement functions for Hit Rate, EV Error, and Sharpe-like Ratio.

---

### Task 1: Implement Quant Metrics

**Files:**
- Create: `research/diagnostics/metrics.py`
- Create: `tests/research/test_metrics.py`

**Step 1: Create failing test**

Create `tests/research/test_metrics.py` with tests for hit rate and Sharpe ratio.

**Step 2: Implement metrics**

Create `research/diagnostics/metrics.py` with functions:
- `calculate_hit_rate(outcomes)`
- `calculate_sharpe_ratio(returns, risk_free_rate=0.0)`

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_metrics.py`

**Step 4: Commit**

```bash
git add research/diagnostics/metrics.py tests/research/test_metrics.py
git commit -m "feat: implement quant metrics"
```
