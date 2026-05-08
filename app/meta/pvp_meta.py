"""
PvP Meta Engine for AQS.
Tracks weapon popularity, armor popularity, and calculates meta demand score.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from datetime import datetime
from app.meta.killboard_meta import fetch_events, compute_meta

class MetaDemandScore(BaseModel):
    item_id: str
    score: float = Field(..., ge=0.0, le=1.0)
    components: dict[str, float] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)

class PvPMetaEngine:
    def __init__(self, base_api_url: str = "https://gameinfo.albiononline.com/api/gameinfo"):
        self.base_api_url = base_api_url

    async def update_meta(self) -> dict[str, MetaDemandScore]:
        """Fetch killboard events and calculate meta demand scores."""
        # Task 11.1: Use killboard APIs
        try:
            events = await fetch_events(self.base_api_url, pages=5, limit=50)
            meta_result = compute_meta(events)
        except Exception as e:
            print(f"Error fetching killboard events: {e}")
            return {}

        # Task 11.2: Create meta_demand_score
        scores = {}
        # We rank items by counts
        total_counts = sum(count for _, count in meta_result.item_counts)
        
        for item_id, count in meta_result.item_counts:
            # Mock components for now as we don't have full market data streams here
            # In a real system, these would be fetched from DB or other modules
            killboard_usage = count / total_counts if total_counts > 0 else 0
            
            # Normalize to 0-1 range for the score component
            # Let's say top item gets full 35% weight
            kb_score = min(killboard_usage * 10, 1.0) # Scale up to make it meaningful
            
            # Mocking other components as per Task 11.2 weights
            market_turnover = 0.5 # Mock
            volume_acceleration = 0.5 # Mock
            price_acceleration = 0.5 # Mock
            crafting_demand = 0.5 # Mock
            bm_pull_through = 0.5 # Mock
            
            final_score = (
                (kb_score * 0.35) +
                (market_turnover * 0.25) +
                (volume_acceleration * 0.15) +
                (price_acceleration * 0.10) +
                (crafting_demand * 0.10) +
                (bm_pull_through * 0.05)
            )
            
            scores[item_id] = MetaDemandScore(
                item_id=item_id,
                score=min(final_score, 1.0),
                components={
                    "killboard_usage": kb_score,
                    "market_turnover": market_turnover,
                    "volume_acceleration": volume_acceleration,
                    "price_acceleration": price_acceleration,
                    "crafting_demand": crafting_demand,
                    "bm_pull_through": bm_pull_through
                }
            )
            
        return scores
