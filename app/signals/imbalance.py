"""
Order book imbalance signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.execution.imbalance import calculate_imbalance
from app.core.config import settings

def generate_imbalance_signal(item_id: str, cluster_id: str, v_bid: float, v_ask: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on order book imbalance.
    """
    imbalance = calculate_imbalance(v_bid, v_ask)
    
    # Simple logic: high imbalance -> high alpha score
    alpha_score = abs(imbalance)
    
    return AlphaSignal(
        signal_type="imbalance",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=alpha_score,
        confidence=settings.imbalance_default_confidence,
        persistence_score=settings.imbalance_default_persistence,
        manipulation_risk=settings.imbalance_default_manipulation_risk,
        timestamp=datetime.utcnow()
    )
