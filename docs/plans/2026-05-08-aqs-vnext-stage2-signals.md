# AQS vNext Stage 2: Signal Generation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Signal Generation layer to produce `Signal` objects from `MarketSnapshot` data using features.

**Architecture:** We will create a base `SignalGenerator` class and a concrete `SpreadAnomalyGenerator` in `app/signals/`.

**Tech Stack:** Python 3.10+, Pydantic v2

---

### Task 1: Create SignalGenerator Base Class

**Files:**
- Create: `app/signals/base.py`
- Create: `app/signals/__init__.py`
- Create: `tests/app/test_signals.py`

**Step 1: Write the failing test**

Create `tests/app/test_signals.py`:
```python
import pytest
from datetime import datetime
from shared.domain.market_snapshot import MarketSnapshot
from app.signals.base import SignalGenerator

def test_base_signal_generator_not_implemented():
    class DummyGenerator(SignalGenerator):
        pass
        
    gen = DummyGenerator()
    snapshot = MarketSnapshot(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        best_bid=1000.0,
        best_ask=1200.0,
        bid_depth=10,
        ask_depth=10,
        spread=200.0,
        midprice=1100.0,
        rolling_volume=100,
        volatility=0.1
    )
    with pytest.raises(NotImplementedError):
        gen.generate(snapshot)
```

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/app/test_signals.py`
Expected: FAIL (ModuleNotFoundError or ImportError)

**Step 3: Write minimal implementation**

Create `app/signals/base.py`:
```python
from abc import ABC, abstractmethod
from typing import List
from shared.domain.market_snapshot import MarketSnapshot
from shared.domain.signal import Signal

class SignalGenerator(ABC):
    @abstractmethod
    def generate(self, snapshot: MarketSnapshot) -> List[Signal]:
        raise NotImplementedError("Subclasses must implement generate()")
```

Create `app/signals/__init__.py`:
```python
# app/signals/__init__.py
```

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/app/test_signals.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/signals/base.py app/signals/__init__.py tests/app/test_signals.py
git commit -m "feat: add SignalGenerator base class"
```

---

### Task 2: Create SpreadAnomalyGenerator

**Files:**
- Create: `app/signals/spread_anomaly.py`
- Modify: `tests/app/test_signals.py`

**Step 1: Write the failing test**

Add to `tests/app/test_signals.py`:
```python
from app.signals.spread_anomaly import SpreadAnomalyGenerator

def test_spread_anomaly_generator():
    gen = SpreadAnomalyGenerator(threshold=0.1) # 10% relative spread
    snapshot = MarketSnapshot(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        best_bid=1000.0,
        best_ask=1200.0, # spread = 200, relative = 200/1100 = 0.18
        bid_depth=10,
        ask_depth=10,
        spread=200.0,
        midprice=1100.0,
        rolling_volume=100,
        volatility=0.1
    )
    signals = gen.generate(snapshot)
    assert len(signals) == 1
    assert signals[0].signal_type == "spread_anomaly"
    assert signals[0].strength == 0.18181818181818182 # approximate or rounded
```

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/app/test_signals.py`
Expected: FAIL (ImportError)

**Step 3: Write minimal implementation**

Create `app/signals/spread_anomaly.py`:
```python
from typing import List
from shared.domain.market_snapshot import MarketSnapshot
from shared.domain.signal import Signal
from app.signals.base import SignalGenerator
from app.features.spread import calculate_relative_spread

class SpreadAnomalyGenerator(SignalGenerator):
    def __init__(self, threshold: float):
        self.threshold = threshold
        
    def generate(self, snapshot: MarketSnapshot) -> List[Signal]:
        rel_spread = calculate_relative_spread(snapshot.best_ask, snapshot.best_bid)
        if rel_spread > self.threshold:
            return [
                Signal(
                    item_id=snapshot.item_id,
                    city=snapshot.city,
                    timestamp=snapshot.timestamp,
                    signal_type="spread_anomaly",
                    strength=rel_spread,
                    metadata={"threshold": self.threshold}
                )
            ]
        return []
```

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/app/test_signals.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/signals/spread_anomaly.py tests/app/test_signals.py
git commit -m "feat: add SpreadAnomalyGenerator"
```
