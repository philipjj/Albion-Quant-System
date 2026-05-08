# AQS vNext Stage 1: Foundation Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Initialize the new modular repository structure and introduce the `MarketSnapshot` domain entity using Pydantic.

**Architecture:** We are moving from a monolith-ish `app/core` to a modular structure. We will start by creating the root-level `shared/` directory and adding the `MarketSnapshot` model there, ensuring it is isolated from market math or execution logic.

**Tech Stack:** Python 3.10+, Pydantic v2

---

### Task 1: Initialize New Directory Structure

**Files:**
- Create: `shared/__init__.py`
- Create: `shared/domain/__init__.py`

**Step 1: Create directories and init files**

Run:
```powershell
New-Item -ItemType Directory -Path shared/domain -Force
New-Item -ItemType File -Path shared/__init__.py
New-Item -ItemType File -Path shared/domain/__init__.py
```

**Step 2: Commit**

```bash
git add shared/
git commit -m "chore: initialize shared/domain directory structure"
```

---

### Task 2: Create MarketSnapshot Domain Model

**Files:**
- Create: `shared/domain/market_snapshot.py`
- Create: `tests/shared/test_market_snapshot.py`

**Step 1: Write the failing test**

Create `tests/shared/test_market_snapshot.py`:
```python
from datetime import datetime
from shared.domain.market_snapshot import MarketSnapshot

def test_market_snapshot_creation():
    snapshot = MarketSnapshot(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        best_bid=1000.0,
        best_ask=1200.0,
        bid_depth=50,
        ask_depth=40,
        spread=200.0,
        midprice=1100.0,
        rolling_volume=1000,
        volatility=0.05
    )
    assert snapshot.item_id == "T8_HEAD_CLOTH"
    assert snapshot.midprice == 1100.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_market_snapshot.py`
Expected: FAIL (ModuleNotFoundError: No module named 'shared.domain.market_snapshot')

**Step 3: Write minimal implementation**

Create `shared/domain/market_snapshot.py`:
```python
from datetime import datetime
from pydantic import BaseModel

class MarketSnapshot(BaseModel):
    item_id: str
    city: str
    timestamp: datetime
    
    best_bid: float
    best_ask: float
    
    bid_depth: int
    ask_depth: int
    
    spread: float
    midprice: float
    
    rolling_volume: int
    volatility: float
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/shared/test_market_snapshot.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/domain/market_snapshot.py tests/shared/test_market_snapshot.py
git commit -m "feat: add MarketSnapshot domain model"
```
