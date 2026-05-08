from app.shared.domain.opportunity import Opportunity
from pydantic import BaseModel

class Alpha(BaseModel):
    opportunity: Opportunity
    expected_value: float  # ERPH
    decay_risk: float
    confidence: float
