from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class AlphaSignal:
    """
    Immutable representation of an alpha signal.
    """
    signal_type: str
    item_id: str
    cluster_id: str
    alpha_score: float
    confidence: float
    persistence_score: float
    manipulation_risk: float
    timestamp: datetime
