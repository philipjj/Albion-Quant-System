"""
Volatility signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.core.config import settings

def generate_volatility_signal(item_id: str, cluster_id: str, volatility: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on volatility.
    """
    return AlphaSignal(
        signal_type="volatility",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=volatility,
        confidence=settings.volatility_default_confidence,
        persistence_score=settings.volatility_default_persistence,
        manipulation_risk=settings.volatility_default_manipulation_risk,
        timestamp=datetime.utcnow()
    )
