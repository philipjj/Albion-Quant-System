# Fix Discord Webhook Failures and Duplicates Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Diagnose and fix Discord webhook failures and prevent duplicate alerts caused by retries.

**Analysis:**
The logs show `Discord webhook failed: (Attempt 1/3)` with an empty error message, and the timing suggests a 10-second timeout. When a webhook times out, it may have actually reached Discord, but the client retries, leading to duplicates.

**Plan:**
1. Improve logging in `DiscordAlerter._send_webhook` to show the exception type (`repr(e)`).
2. Increase the timeout from 10.0 to 20.0 seconds to give Discord more time to respond under load.
3. Add a check to see if we can avoid retrying on specific errors if appropriate, or just rely on the longer timeout.

---

### Task 1: Improve Discord Webhook Logging and Timeout

**Files:**
- Modify: `app/alerts/discord.py`

**Step 1: Modify `_send_webhook`**
- Change `timeout=10.0` to `timeout=20.0` in `httpx.AsyncClient`.
- Change `log.error(f"Discord webhook failed: {e} ...")` to `log.error(f"Discord webhook failed: {repr(e)} ...")` to see the exception type.

**Step 2: Commit changes**
- Commit the changes locally.

---

### Task 2: Verify and Monitor

**Step 1: Run the application**
- Ask the user to run the application again and monitor if the error persists or if the details are revealed.
