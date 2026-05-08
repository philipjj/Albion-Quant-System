"""
Substitution signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal

def generate_substitution_signal(item_id: str, cluster_id: str, premium: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on substitution premium.
    """
    # High premium compared to cluster average -> high alpha score for substitute!
    return AlphaSignal(
        signal_type="substitution",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=premium,
        confidence=0.6,
        persistence_score=0.6,
        manipulation_risk=0.1,
        timestamp=datetime.utcnow()
    )
