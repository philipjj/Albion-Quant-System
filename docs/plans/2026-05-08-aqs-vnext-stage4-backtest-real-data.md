# Stage 4 Backtest on Real Data Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a simple strategy and run a backtest on the real 919MB SQLite database.

**Architecture:**
- Create `research/backtesting/strategy.py` with `SimpleArbitrageStrategy`.
- Create a script `research/backtesting/run_backtest.py` to run the backtest.
- Use `ReplayEngine` with `source="db"`.

---

### Task 1: Implement SimpleArbitrageStrategy

**Files:**
- Create: `research/backtesting/strategy.py`
- Create: `tests/research/test_strategy.py`

**Step 1: Create tests**

Create `tests/research/test_strategy.py` to verify the strategy generates signals.

**Step 2: Implement Strategy**

Create `research/backtesting/strategy.py`.
Strategy logic: If price in City A < price in City B, buy in A and sell in B (abstractly).
Since our replay yields one event at a time, we need to remember the last price in each city!

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/research/test_strategy.py`

---

### Task 2: Create Run Script

**Files:**
- Create: `research/backtesting/run_backtest.py`

**Step 1: Implement Script**

Create `research/backtesting/run_backtest.py` that initializes `ReplayEngine`, `SimpleArbitrageStrategy`, and `BacktestEngine`, and runs it for a small time range.

**Step 2: Run the script**

Run: `venv\Scripts\python research/backtesting/run_backtest.py`
Verify it produces metrics without crashing.

**Step 3: Commit**

```bash
git add research/backtesting/strategy.py research/backtesting/run_backtest.py tests/research/test_strategy.py
git commit -m "feat: add strategy and run script for backtesting"
```
