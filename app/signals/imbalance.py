"""
Order book imbalance signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.execution.imbalance import calculate_imbalance

def generate_imbalance_signal(item_id: str, cluster_id: str, v_bid: float, v_ask: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on order book imbalance.
    """
    imbalance = calculate_imbalance(v_bid, v_ask)
    
    # Simple logic: high imbalance -> high alpha score
    alpha_score = abs(imbalance)
    confidence = 0.8  # Static for now
    
    return AlphaSignal(
        signal_type="imbalance",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=alpha_score,
        confidence=confidence,
        persistence_score=0.5,
        manipulation_risk=0.1,
        timestamp=datetime.utcnow()
    )
