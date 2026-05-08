"""
PvP Consumable Correlation for AQS.
Maps active PvP meta to consumable demand.
"""

from __future__ import annotations
from pydantic import BaseModel

class ConsumableCorrelation(BaseModel):
    meta_type: str # e.g. "burst_dps", "brawl", "healer"
    correlated_consumables: dict[str, float] # item_id -> impact_weight

class CorrelationMapper:
    def __init__(self):
        # Task 11.4: Map consumables to active PvP meta
        self.rules = [
            ConsumableCorrelation(
                meta_type="burst_dps",
                correlated_consumables={
                    "T8_POTION_COOLDOWN": 0.8,
                    "T8_POTION_STONESKIN": 0.5,
                    "T8_MEAL_STEW": 0.9,
                    "T8_MEAL_OMELETTE": 0.3
                }
            ),
            ConsumableCorrelation(
                meta_type="brawl",
                correlated_consumables={
                    "T8_POTION_HEAL": 0.9,
                    "T8_POTION_RESIST": 0.8,
                    "T8_MEAL_ROAST": 0.9,
                    "T8_MEAL_STEW": 0.6
                }
            ),
            ConsumableCorrelation(
                meta_type="healer",
                correlated_consumables={
                    "T8_POTION_CLEANSE": 0.9,
                    "T8_POTION_GIGANTIFY": 0.5,
                    "T8_MEAL_OMELETTE": 0.9,
                    "T8_MEAL_STEW": 0.2
                }
            )
        ]

    def get_consumable_impact(self, active_meta: str) -> dict[str, float]:
        """Get expected consumable demand impact for a given meta type."""
        for rule in self.rules:
            if rule.meta_type == active_meta:
                return rule.correlated_consumables
        return {}
