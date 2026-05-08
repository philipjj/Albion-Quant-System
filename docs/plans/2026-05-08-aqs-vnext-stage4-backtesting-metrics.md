# Stage 4 Backtesting Metric Accumulation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement metric accumulation (PNL, positions) in the backtesting engine.

**Architecture:**
- Update `research/backtesting/engine.py` to maintain cash and positions.
- Provide a way for the strategy to execute trades (buy/sell).
- Calculate final metrics (Sharpe, Hit Rate) using `research/diagnostics/metrics.py`.

---

### Task 1: Implement Position Tracking and Trade Execution

**Files:**
- Update: `research/backtesting/engine.py`
- Update: `tests/research/test_backtest_engine.py`

**Step 1: Update tests**

Update `tests/research/test_backtest_engine.py` to verify that a strategy can place orders and track PNL.

**Step 2: Update BacktestEngine**

Add `cash`, `positions`, and `execute_order` method to `BacktestEngine`.
Pass `engine` to `strategy.on_data` so it can call `execute_order`.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_backtest_engine.py`

**Step 4: Commit**

```bash
git add research/backtesting/engine.py tests/research/test_backtest_engine.py
git commit -m "feat: add position tracking and trade execution to backtester"
```
