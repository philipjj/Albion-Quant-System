# Stage 4 Backtesting Engine Skeleton Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a skeleton for the event-driven backtesting engine.

**Architecture:**
- Create `research/backtesting/engine.py` with `BacktestEngine`.
- It should use `ReplayEngine` to get historical data.
- It should maintain a portfolio/account state.
- It should call a strategy on each event.

---

### Task 1: Implement BacktestEngine and Strategy Interface

**Files:**
- Create: `research/backtesting/engine.py`
- Create: `tests/research/test_backtest_engine.py`

**Step 1: Create tests**

Create `tests/research/test_backtest_engine.py` to verify the backtest loop runs and calls the strategy.

**Step 2: Implement BacktestEngine**

Create `research/backtesting/engine.py` with `BacktestEngine` and a base `Strategy` class.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_backtest_engine.py`

**Step 4: Commit**

```bash
git add research/backtesting/engine.py tests/research/test_backtest_engine.py
git commit -m "feat: implement backtesting engine skeleton"
```
