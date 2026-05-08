from datetime import datetime
from pydantic import BaseModel, Field

class Signal(BaseModel):
    item_id: str
    city: str
    timestamp: datetime
    signal_type: str
    strength: float
    metadata: dict = Field(default_factory=dict)
