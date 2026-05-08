"""
Patch Parser for AQS.
Extracts structured information from patch notes content.
"""

from __future__ import annotations
import re
from pydantic import BaseModel

class ParsedPatchChange(BaseModel):
    item: str
    change: str # "buff", "nerf"
    severity: float # 0.0 to 1.0
    expected_market_impact: str # "low", "medium", "high"

class PatchParser:
    def parse_content(self, content: str) -> list[ParsedPatchChange]:
        """Parse patch content to extract changes."""
        changes = []
        
        # Simple rule-based parser as NLP usually requires heavy dependencies
        # Task 12.2: Extract affected item, change type, severity
        
        # Look for "increased" or "buff"
        buff_matches = re.findall(r"([A-Za-z\s]+?)\s*(?:damage|healing|cooldown reduction)?\s*(?:increased|buffed)", content, re.IGNORECASE)
        for match in buff_matches:
            item = match.strip()
            if item:
                changes.append(ParsedPatchChange(
                    item=item,
                    change="buff",
                    severity=0.5, # Default severity
                    expected_market_impact="medium"
                ))
                
        # Look for "reduced" or "nerf"
        nerf_matches = re.findall(r"([A-Za-z\s]+?)\s*(?:damage|healing|cooldown)?\s*(?:reduced|nerfed)", content, re.IGNORECASE)
        for match in nerf_matches:
            item = match.strip()
            if item:
                changes.append(ParsedPatchChange(
                    item=item,
                    change="nerf",
                    severity=0.5,
                    expected_market_impact="medium"
                ))

                
        return changes
