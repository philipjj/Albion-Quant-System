"""
Meta scanning via the Albion Gameinfo (killboard) events API.

This is separate from market/crafting "meta" and answers the Discord use-case:
"what builds/sets are players actually wearing by tier (4.0+)?"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

SLOT_ORDER = [
    "MainHand",
    "OffHand",
    "Head",
    "Armor",
    "Shoes",
    "Cape",
    "Bag",
    "Mount",
    "Food",
    "Potion",
]


def _parse_tier_enchant(item_type: str | None) -> tuple[int, int] | None:
    if not item_type:
        return None
    if not item_type.startswith("T"):
        return None
    try:
        tier = int(item_type[1])
    except Exception:
        return None
    enchant = 0
    if "@" in item_type:
        try:
            enchant = int(item_type.rsplit("@", 1)[1])
        except Exception:
            enchant = 0
    return tier, enchant


def _tier_bucket_from_equipment(equipment: dict[str, Any]) -> str | None:
    """
    Bucket builds by weapon tier.enchant (e.g. 4.0, 6.2).
    If weapon missing, fall back to armor.
    """
    for slot in ("MainHand", "Armor", "Head", "Shoes"):
        item_type = (equipment.get(slot) or {}).get("Type")
        te = _parse_tier_enchant(item_type)
        if te:
            tier, enchant = te
            if tier >= 4:
                return f"{tier}.{enchant}"
    return None


def _equipment_signature(equipment: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Builds a stable signature for equipment and a normalized dict."""
    parts = []
    normalized: dict[str, dict[str, Any]] = {}
    for slot in SLOT_ORDER:
        eq = equipment.get(slot) or {}
        item_type = eq.get("Type")
        quality = eq.get("Quality", 1)
        if item_type:
            parts.append(f"{slot}:{item_type}@{quality}")
            normalized[slot] = {"Type": item_type, "Quality": quality}
    return "|".join(parts), normalized


@dataclass(frozen=True)
class MetaResult:
    tier_to_builds: dict[str, list[dict[str, Any]]]
    item_counts: list[tuple[str, int]]
    sample_events: int


async def fetch_events(base_url: str, *, pages: int = 3, limit: int = 51) -> list[dict[str, Any]]:
    """
    Fetch recent killboard events.

    Known constraints: limit is typically 0-51; offset + limit has server-side caps.
    """
    events: list[dict[str, Any]] = []
    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "AlbionQuant/0.1 meta-scanner"}) as client:
        for page in range(pages):
            offset = page * limit
            resp = await client.get(f"{base_url.rstrip('/')}/events", params={"limit": limit, "offset": offset})
            resp.raise_for_status()
            data = resp.json()
            batch = data if isinstance(data, list) else data.get("Events") if isinstance(data, dict) else []
            if not batch:
                break
            events.extend(batch)
    return events


def compute_meta(events: list[dict[str, Any]], *, top_builds_per_tier: int = 3) -> MetaResult:
    tier_build_counts: dict[str, dict[str, dict[str, Any]]] = {}
    item_counts: dict[str, int] = {}

    def add_equipment(eq: dict[str, Any]):
        bucket = _tier_bucket_from_equipment(eq)
        if not bucket:
            return
        sig, normalized = _equipment_signature(eq)

        tier_bucket = tier_build_counts.setdefault(bucket, {})
        entry = tier_bucket.get(sig)
        if not entry:
            entry = {"sig": sig, "count": 0, "slots": normalized}
            tier_bucket[sig] = entry
        entry["count"] += 1

        for item_data in normalized.values():
            item_id = item_data["Type"]
            te = _parse_tier_enchant(item_id)
            if te and te[0] >= 4:
                item_counts[item_id] = item_counts.get(item_id, 0) + 1

    for ev in events:
        killer = (ev.get("Killer") or {}).get("Equipment") or {}
        victim = (ev.get("Victim") or {}).get("Equipment") or {}
        if isinstance(killer, dict) and killer:
            add_equipment(killer)
        if isinstance(victim, dict) and victim:
            add_equipment(victim)

    tier_to_builds: dict[str, list[dict[str, Any]]] = {}
    for tier, builds in tier_build_counts.items():
        ranked = sorted(builds.values(), key=lambda x: x["count"], reverse=True)[:top_builds_per_tier]
        tier_to_builds[tier] = ranked

    item_ranked = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)
    return MetaResult(
        tier_to_builds=tier_to_builds,
        item_counts=item_ranked,
        sample_events=len(events),
    )

