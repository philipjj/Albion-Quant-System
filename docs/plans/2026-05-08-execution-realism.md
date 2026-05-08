# Execution Realism Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement realistic execution simulation including VWAP, slippage, and fill probability.

**Architecture:** We will build a set of pure functions and classes in `app/simulation/` to calculate VWAP, simulate order book traversal, and estimate fill probabilities based on market conditions.

**Tech Stack:** Python 3.14, Pydantic, Pytest

---

### Task 1: VWAP Engine

**Files:**
- Create: `app/simulation/vwap.py`
- Test: `tests/app/test_vwap.py`

**Step 1: Write the failing test**

```python
import pytest
from app.simulation.vwap import calculate_vwap

def test_calculate_vwap():
    trades = [
        {"price": 100.0, "volume": 10.0},
        {"price": 102.0, "volume": 20.0},
        {"price": 99.0, "volume": 5.0}
    ]
    # (100*10 + 102*20 + 99*5) / (10 + 20 + 5) = (1000 + 2040 + 495) / 35 = 3535 / 35 = 101.0
    assert calculate_vwap(trades) == 101.0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/app/test_vwap.py`
Expected: FAIL (Module not found or function not defined)

**Step 3: Write minimal implementation**

```python
from typing import List, Dict

def calculate_vwap(trades: List[Dict[str, float]]) -> float:
    total_value = sum(t["price"] * t["volume"] for t in trades)
    total_volume = sum(t["volume"] for t in trades)
    if total_volume == 0:
        return 0.0
    return total_value / total_volume
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/app/test_vwap.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/simulation/vwap.py tests/app/test_vwap.py
git commit -m "feat: add VWAP calculation"
```

---

### Task 2: Order Book Traversal

**Files:**
- Create: `app/simulation/traversal.py`
- Test: `tests/app/test_traversal.py`

**Step 1: Write the failing test**

```python
import pytest
from app.simulation.traversal import traverse_book

def test_traverse_book():
    book = [
        {"price": 100.0, "volume": 10.0},
        {"price": 101.0, "volume": 20.0},
        {"price": 102.0, "volume": 5.0}
    ]
    # Traversed price for 15 units: (10*100 + 5*101) / 15 = (1000 + 505) / 15 = 1505 / 15 = 100.333...
    avg_price, filled = traverse_book(book, target_volume=15.0)
    assert abs(avg_price - 100.3333) < 0.001
    assert filled == 15.0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/app/test_traversal.py`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
from typing import List, Dict, Tuple

def traverse_book(book: List[Dict[str, float]], target_volume: float) -> Tuple[float, float]:
    total_cost = 0.0
    remaining = target_volume
    filled = 0.0
    
    for level in book:
        if remaining <= 0:
            break
        vol = min(level["volume"], remaining)
        total_cost += vol * level["price"]
        remaining -= vol
        filled += vol
        
    if filled == 0:
        return 0.0, 0.0
    return total_cost / filled, filled
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/app/test_traversal.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/simulation/traversal.py tests/app/test_traversal.py
git commit -m "feat: add order book traversal"
```

---

### Task 3: Fill Probability Estimation

**Files:**
- Create: `app/simulation/fills.py`
- Test: `tests/app/test_fills.py`

**Step 1: Write the failing test**

```python
import pytest
from app.simulation.fills import estimate_fill_probability

def test_estimate_fill_probability():
    prob = estimate_fill_probability(imbalance=0.8, volatility=0.1)
    assert prob > 0.5 # High imbalance (buy pressure) should lead to high fill prob for buys
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/app/test_fills.py`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def estimate_fill_probability(imbalance: float, volatility: float) -> float:
    # Simple heuristic for now
    base_prob = 0.5
    # Positive imbalance increases buy fill prob
    prob = base_prob + (imbalance * 0.3) - (volatility * 0.2)
    return max(0.0, min(1.0, prob))
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/app/test_fills.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/simulation/fills.py tests/app/test_fills.py
git commit -m "feat: add fill probability estimation"
```
