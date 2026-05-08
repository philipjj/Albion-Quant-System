# Stage 3 Order Book Traversal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the matching engine to traverse full order book depth instead of just matching against the best bid/ask.

**Architecture:** Update `match_order` to accept a list of order book levels (or derive them from snapshot) and iterate through them.

---

### Task 1: Update match_order to handle depth

**Files:**
- Modify: `app/simulation/matching_engine.py`
- Test: `tests/app/test_matching_engine.py`

**Step 1: Create test with depth**

Create or update `tests/app/test_matching_engine.py` to provide a snapshot with multiple depth levels (e.g., `asks: [[price, volume], ...]`) and verify that matching traverses them.

**Step 2: Update implementation**

Update `match_order` to:
- Check if snapshot has `asks` and `bids` lists (or similar structure).
- Iterate through levels to fill the size.
- Calculate average execution price correctly.

**Step 3: Verify tests pass**

Run: `venv\Scripts\python -m pytest tests/app/test_matching_engine.py`

**Step 4: Commit**

```bash
git add app/simulation/matching_engine.py tests/app/test_matching_engine.py
git commit -m "feat: upgrade matching engine to traverse order book depth"
```
