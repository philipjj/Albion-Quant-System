# Stage 1 TimescaleDB Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the database migration to PostgreSQL/TimescaleDB as specified in the roadmap.

**Architecture:** Update `MarketSnapshot` to include `quality`, and run the database initialization to create tables in PostgreSQL.

**Tech Stack:** Python 3.10+, SQLAlchemy, asyncpg

---

### Task 1: Update MarketSnapshot Model

**Files:**
- Modify: `shared/domain/market_snapshot.py`
- Test: `tests/shared/test_market_snapshot.py`

**Step 1: Update test**

Update `tests/shared/test_market_snapshot.py` to include `quality` in the test snapshot.

**Step 2: Update model**

Add `quality: int = 1` to `MarketSnapshot` in `shared/domain/market_snapshot.py`.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/shared/test_market_snapshot.py`

**Step 4: Commit**

```bash
git add shared/domain/market_snapshot.py tests/shared/test_market_snapshot.py
git commit -m "feat: add quality to MarketSnapshot model"
```

---

### Task 2: Verify and Run Database Initialization

**Files:**
- Create: `app/db/run_migration.py` (Script to run `init_db`)

**Step 1: Create migration script**

Create a script that imports `init_db` and runs it.

**Step 2: Run script**

Run the script. It will use the `DATABASE_URL` from `.env`.
*Note: If the user has not updated `.env` with correct credentials, this might fail. We will try to use a default local Postgres URL if it fails or ask the user.*

**Step 3: Commit**

```bash
git add app/db/run_migration.py
git commit -m "feat: add script to run database migrations"
```
