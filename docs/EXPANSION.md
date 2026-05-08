# AQS Expansion — PvP Meta Engine & Patch Intelligence System

This document describes the implementation of Phases 11-17 of the AQS Expansion Plan.

## Objective
Transform AQS from a reactive market scanner into a predictive economic warfare engine by integrating PvP meta detection and patch intelligence.

## Implemented Modules

### 1. PvP Meta Intelligence (Phase 11)
*   `app/meta/pvp_meta.py`: Tracks weapon/armor popularity and calculates a weighted `meta_demand_score`.
*   `app/meta/loadouts.py`: Tracks popular builds and usage trends from killboard data.
*   `app/meta/correlations.py`: Maps meta shifts to consumable demand (e.g., burst DPS -> poison potions).

### 2. Patch Intelligence System (Phase 12)
*   `app/meta/patch_tracker.py`: Monitors patch notes and NDA updates.
*   `app/meta/patch_parser.py`: Uses regex/rule-based matching to extract buffs/nerfs and severity.
*   `app/meta/impact_forecast.py`: Predicts demand shifts before they happen.

### 3. Meta-Aware Scoring (Phase 13)
*   `app/core/scoring.py`: Applied `meta_multiplier` (1.25) and `patch_multiplier` (1.40) to scoring algorithms.

### 4. Alert Categories (Phase 14)
*   `app/alerts/discord.py`: Added `send_categorized_alert` supporting:
    *   `META SURGE`
    *   `PATCH BUFF`
    *   `PATCH NERF`
    *   `BUILD ROTATION`
    *   `RESOURCE PRESSURE`
    *   `BM META PULL`

### 5. Scheduler Integration (Phase 15)
*   `app/workers/scheduler.py`: Scheduled jobs for:
    *   Meta Scan (every 10 minutes)
    *   Patch Monitor (every 30 minutes)
    *   Loadout Clustering (every 20 minutes)

### 6. Database Extensions (Phase 16)
*   `app/db/models.py`: Added models for `MetaSnapshot`, `PatchEventModel`, `LoadoutCluster`, `ItemMetaScore`, and `PatchForecast`.

## Final System Behavior (Phase 17)
The system now operates autonomously to:
1.  Detect meta rotations from killboard activity.
2.  Parse patch notes to anticipate buffs/nerfs.
3.  Forecast market impact and adjust opportunity scores.
4.  Send high-fidelity alerts to Discord before the market reprices.
