"""
Substitution signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.core.config import settings

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
        confidence=settings.substitution_default_confidence,
        persistence_score=settings.substitution_default_persistence,
        manipulation_risk=settings.substitution_default_manipulation_risk,
        timestamp=datetime.utcnow()
    )
