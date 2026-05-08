# Stage 3 VWAP Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the missing VWAP calculation engine to resolve failing tests and lay the foundation for execution simulation.

**Architecture:** Create `app/simulation/vwap.py` and implement `calculate_vwap` taking a list of trades with price and volume. Verify with the existing test in `tests/app/test_vwap.py`.

**Tech Stack:** Python 3.10+

---

### Task 1: Implement calculate_vwap

**Files:**
- Create: `app/simulation/vwap.py`
- Test: `tests/app/test_vwap.py`

**Step 1: Verify existing test fails**

The test already exists at `tests/app/test_vwap.py` and imports from `app.simulation.vwap`. It should fail because the file is missing.

Run: `venv\Scripts\python -m pytest tests/app/test_vwap.py`
Expected: ModuleNotFoundError

**Step 2: Create file and implement calculate_vwap**

Create `app/simulation/vwap.py`:
```python
from typing import List, Dict

def calculate_vwap(trades: List[Dict[str, float]]) -> float:
    """
    Calculates the Volume Weighted Average Price (VWAP).
    Formula: sum(price * volume) / sum(volume)
    """
    if not trades:
        return 0.0
        
    total_value = sum(trade["price"] * trade["volume"] for trade in trades)
    total_volume = sum(trade["volume"] for trade in trades)
    
    if total_volume == 0:
        return 0.0
        
    return total_value / total_volume
```

**Step 3: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/app/test_vwap.py`
Expected: PASS

**Step 4: Commit**

```bash
git add app/simulation/vwap.py
git commit -m "feat: implement calculate_vwap"
```
