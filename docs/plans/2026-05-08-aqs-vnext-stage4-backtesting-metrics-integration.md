# Stage 4 Backtesting Metrics Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate complex metrics (Sharpe ratio, Max Drawdown) into the backtesting engine.

**Architecture:**
- Add `calculate_max_drawdown` to `research/diagnostics/metrics.py`.
- Update `research/backtesting/engine.py` to record equity curve and calculate metrics.

---

### Task 1: Add Max Drawdown to metrics.py

**Files:**
- Update: `research/diagnostics/metrics.py`
- Update: `tests/research/test_metrics.py`

**Step 1: Update tests**

Update `tests/research/test_metrics.py` to test `calculate_max_drawdown`.

**Step 2: Implement Max Drawdown**

Add `calculate_max_drawdown` to `research/diagnostics/metrics.py`.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_metrics.py`

---

### Task 2: Update BacktestEngine to use metrics

**Files:**
- Update: `research/backtesting/engine.py`
- Update: `tests/research/test_backtest_engine.py`

**Step 1: Update BacktestEngine**

Track `returns` and `equity_curve` in `BacktestEngine.run`.
Call `calculate_sharpe_ratio` and `calculate_max_drawdown` at the end.

**Step 2: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_backtest_engine.py`

**Step 3: Commit**

```bash
git add research/diagnostics/metrics.py research/backtesting/engine.py tests/research/test_metrics.py tests/research/test_backtest_engine.py
git commit -m "feat: integrate Sharpe ratio and Max Drawdown in backtester"
```
