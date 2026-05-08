"""
Recommendations.
Defines the structure of a market recommendation.
"""
from datetime import datetime
from pydantic import BaseModel, Field

class Recommendation(BaseModel):
    item_id: str
    city: str
    timestamp: datetime
    action: str  # 'buy', 'sell', 'hold'
    reason: str
    confidence: float
    metadata: dict = Field(default_factory=dict)
