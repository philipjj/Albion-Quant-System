"""
Meta Loadout Tracking for AQS.
Tracks common builds and popularity.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel
from app.meta.killboard_meta import fetch_events, compute_meta, _parse_tier_enchant

class LoadoutTrend(BaseModel):
    weapon: str
    tier: str
    usage_trend: str # "up", "down", "stable"
    meta_strength: float

class LoadoutTracker:
    def __init__(self, base_api_url: str = "https://gameinfo.albiononline.com/api/gameinfo"):
        self.base_api_url = base_api_url

    async def get_popular_loadouts(self) -> list[LoadoutTrend]:
        """Fetch events and extract popular loadouts."""
        try:
            events = await fetch_events(self.base_api_url, pages=5, limit=50)
            meta_result = compute_meta(events)
        except Exception as e:
            print(f"Error fetching killboard events: {e}")
            return []

        loadouts = []
        for tier_bucket, builds in meta_result.tier_to_builds.items():
            for build in builds:
                slots = build.get("slots", {})
                weapon_data = slots.get("MainHand", {})
                weapon_type = weapon_data.get("Type")
                
                if weapon_type:
                    # Extract base weapon name (remove tier and enchantment)
                    # e.g. T6_MAIN_SWORD -> MAIN_SWORD
                    parts = weapon_type.split("_")
                    if len(parts) > 1 and parts[0].startswith("T"):
                        base_weapon = "_".join(parts[1:])
                    else:
                        base_weapon = weapon_type
                        
                    # Calculate meta strength based on count
                    # Mock trend for now
                    loadouts.append(LoadoutTrend(
                        weapon=base_weapon,
                        tier=tier_bucket,
                        usage_trend="up", # Mock
                        meta_strength=min(build["count"] / 10.0, 1.0) # Scale count to 0-1
                    ))
                    
        return loadouts
