from pydantic import BaseModel

from app.shared.domain.opportunity import Opportunity


class Alpha(BaseModel):
    opportunity: Opportunity
    expected_value: float  # ERPH
    decay_risk: float
    confidence: float
