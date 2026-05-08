"""
Patch Impact Forecaster for AQS.
Predicts future market demand shifts based on patch changes.
"""

from __future__ import annotations
from pydantic import BaseModel
from app.meta.patch_parser import ParsedPatchChange

class ForecastTarget(BaseModel):
    market: str # "Gear", "Resources", "Artifacts", "Consumables", "Refining"
    impact: str # "Demand spike", "Material pressure", "Crafting demand", etc.
    confidence: str # "LOW", "MEDIUM", "HIGH"

class PatchImpactForecaster:
    def forecast_impact(self, changes: list[ParsedPatchChange]) -> list[ForecastTarget]:
        """Generate forecasts based on parsed patch changes."""
        forecasts = []
        
        for change in changes:
            if change.change == "buff":
                forecasts.append(ForecastTarget(
                    market="Gear",
                    impact=f"Demand spike for {change.item}",
                    confidence="HIGH" if change.severity > 0.7 else "MEDIUM"
                ))
                forecasts.append(ForecastTarget(
                    market="Artifacts",
                    impact="Crafting demand increase",
                    confidence="MEDIUM"
                ))
            elif change.change == "nerf":
                forecasts.append(ForecastTarget(
                    market="Gear",
                    impact=f"Liquidation warning for {change.item}",
                    confidence="HIGH" if change.severity > 0.7 else "MEDIUM"
                ))
                
        return forecasts
