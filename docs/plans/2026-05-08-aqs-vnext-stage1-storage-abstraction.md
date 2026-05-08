# AQS vNext Stage 1: Storage Abstraction Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a storage abstraction layer (Repository pattern) to decouple core logic from SQLite, as specified in the roadmap.

**Architecture:**
- Create an abstract base class `IMarketDataRepository` in `shared/domain/repository.py`.
- Create a concrete implementation `SQLiteMarketDataRepository` in `app/db/repository.py`.
- Refactor `app/ingestion/collector.py` to use the repository instead of direct SQLAlchemy/SQLite upserts.

**Tech Stack:** Python 3.10+, Pydantic v2, SQLAlchemy

---

### Task 1: Define Repository Interface

**Files:**
- Create: `shared/domain/repository.py`
- Create: `tests/shared/test_repository_interface.py`

**Step 1: Write the failing test**

Create `tests/shared/test_repository_interface.py` verifying that `IMarketDataRepository` cannot be instantiated and defines the required methods.

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/shared/test_repository_interface.py`
Expected: FAIL

**Step 3: Write minimal implementation**

In `shared/domain/repository.py`:
```python
from abc import ABC, abstractmethod
from shared.domain.market_snapshot import MarketSnapshot

class IMarketDataRepository(ABC):
    @abstractmethod
    def save_snapshots(self, snapshots: list[MarketSnapshot]) -> None:
        pass
        
    @abstractmethod
    def get_latest_snapshot(self, item_id: str, city: str) -> MarketSnapshot | None:
        pass
```

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/shared/test_repository_interface.py`
Expected: PASS

**Step 5: Commit**

```bash
git add shared/domain/repository.py tests/shared/test_repository_interface.py
git commit -m "feat: define IMarketDataRepository interface"
```

---

### Task 2: Implement SQLite Repository

**Files:**
- Create: `app/db/repository.py`
- Create: `tests/app/test_sqlite_repository.py`

**Step 1: Write the failing test**

Create `tests/app/test_sqlite_repository.py` testing `save_snapshots` and `get_latest_snapshot` against a test SQLite database.

**Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/app/test_sqlite_repository.py`
Expected: FAIL

**Step 3: Write minimal implementation**

In `app/db/repository.py`:
- Implement `SQLiteMarketDataRepository` inheriting from `IMarketDataRepository`.
- Map `MarketSnapshot` fields to `MarketPrice` DB model.
- Use the existing `sqlite_upsert` logic or standard SQLAlchemy if possible (to be determined during implementation).

**Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/app/test_sqlite_repository.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/db/repository.py tests/app/test_sqlite_repository.py
git commit -m "feat: implement SQLiteMarketDataRepository"
```

---

### Task 3: Refactor Collector to Use Repository

**Files:**
- Modify: `app/ingestion/collector.py`

**Step 1: Write the failing test**

(Optional or rely on existing integration tests if any, or create a mock-based test).

**Step 2: Modify implementation**

- Inject `IMarketDataRepository` into `MarketCollector`.
- Replace line 316+ upsert logic with `repository.save_snapshots(...)`.

**Step 3: Verify**

Run existing ingestion tests or manual verification.

**Step 4: Commit**

```bash
git add app/ingestion/collector.py
git commit -m "feat: refactor collector to use storage abstraction"
```
