"""
Volatility signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal

def generate_volatility_signal(item_id: str, cluster_id: str, volatility: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on volatility.
    """
    return AlphaSignal(
        signal_type="volatility",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=volatility,
        confidence=0.5,
        persistence_score=0.4,
        manipulation_risk=0.3,
        timestamp=datetime.utcnow()
    )
