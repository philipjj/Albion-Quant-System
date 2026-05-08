# AQS vNext Stage 1: Domain Models (Signal, Opportunity, Alpha) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the remaining core domain models (`Signal`, `Opportunity`, `Alpha`) specified in the roadmap to enable probabilistic alpha modeling.

**Architecture:** We will create these models in the `shared/domain/` directory. They will build on each other (Signal -> Opportunity -> Alpha) as described in the roadmap ontology.

**Tech Stack:** Python 3.10+, Pydantic v2

---

### Task 1: Create Signal Domain Model

**Files:**
- Create: `shared/domain/signal.py`
- Create: `tests/shared/test_signal.py`

**Step 1: Write the failing test**

Create `tests/shared/test_signal.py`:
```python
from datetime import datetime
from shared.domain.signal import Signal

def test_signal_creation():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5,
        metadata={"spread_pct": 0.55}
    )
    assert sig.item_id == "T8_HEAD_CLOTH"
    assert sig.signal_type == "spread_anomaly"
```

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/shared/test_signal.py`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

Create `shared/domain/signal.py`:
```python
from datetime import datetime
from pydantic import BaseModel, Field

class Signal(BaseModel):
    item_id: str
    city: str
    timestamp: datetime
    signal_type: str
    strength: float
    metadata: dict = Field(default_factory=dict)
```

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/shared/test_signal.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/domain/signal.py tests/shared/test_signal.py
git commit -m "feat: add Signal domain model"
```

---

### Task 2: Create Opportunity Domain Model

**Files:**
- Create: `shared/domain/opportunity.py`
- Create: `tests/shared/test_opportunity.py`

**Step 1: Write the failing test**

Create `tests/shared/test_opportunity.py`:
```python
from datetime import datetime
from shared.domain.signal import Signal
from shared.domain.opportunity import Opportunity

def test_opportunity_creation():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5
    )
    opp = Opportunity(
        signal=sig,
        vwap_estimation=1150.0,
        slippage=5.0,
        fill_probability=0.8,
        transport_cost=50.0,
        estimated_profit=100.0
    )
    assert opp.signal.item_id == "T8_HEAD_CLOTH"
    assert opp.fill_probability == 0.8
```

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/shared/test_opportunity.py`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

Create `shared/domain/opportunity.py`:
```python
from shared.domain.signal import Signal
from pydantic import BaseModel

class Opportunity(BaseModel):
    signal: Signal
    vwap_estimation: float
    slippage: float
    fill_probability: float
    transport_cost: float
    estimated_profit: float
```

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/shared/test_opportunity.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/domain/opportunity.py tests/shared/test_opportunity.py
git commit -m "feat: add Opportunity domain model"
```

---

### Task 3: Create Alpha Domain Model

**Files:**
- Create: `shared/domain/alpha.py`
- Create: `tests/shared/test_alpha.py`

**Step 1: Write the failing test**

Create `tests/shared/test_alpha.py`:
```python
from datetime import datetime
from shared.domain.signal import Signal
from shared.domain.opportunity import Opportunity
from shared.domain.alpha import Alpha

def test_alpha_creation():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5
    )
    opp = Opportunity(
        signal=sig,
        vwap_estimation=1150.0,
        slippage=5.0,
        fill_probability=0.8,
        transport_cost=50.0,
        estimated_profit=100.0
    )
    alpha = Alpha(
        opportunity=opp,
        expected_value=80.0,
        decay_risk=0.1,
        confidence=0.9
    )
    assert alpha.opportunity.signal.item_id == "T8_HEAD_CLOTH"
    assert alpha.expected_value == 80.0
```

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/shared/test_alpha.py`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

Create `shared/domain/alpha.py`:
```python
from shared.domain.opportunity import Opportunity
from pydantic import BaseModel

class Alpha(BaseModel):
    opportunity: Opportunity
    expected_value: float  # ERPH
    decay_risk: float
    confidence: float
```

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/shared/test_alpha.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/domain/alpha.py tests/shared/test_alpha.py
git commit -m "feat: add Alpha domain model"
```
