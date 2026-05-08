"""
Scarcity signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal

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
        confidence=0.7,
        persistence_score=0.8,
        manipulation_risk=0.2,
        timestamp=datetime.utcnow()
    )
