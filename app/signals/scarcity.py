"""
Scarcity signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.core.config import settings

def generate_scarcity_signal(item_id: str, cluster_id: str, supply: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on item scarcity.
    """
    # Low supply -> high scarcity -> high alpha score
    alpha_score = 1.0 / (supply + 1.0)
    
    return AlphaSignal(
        signal_type="scarcity",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=alpha_score,
        confidence=settings.scarcity_default_confidence,
        persistence_score=settings.scarcity_default_persistence,
        manipulation_risk=settings.scarcity_default_manipulation_risk,
        timestamp=datetime.utcnow()
    )
