"""
Liquidity gap signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal
from app.core.config import settings

def generate_liquidity_gap_signal(item_id: str, cluster_id: str, gap_size: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on liquidity gap.
    """
    return AlphaSignal(
        signal_type="liquidity_gap",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=gap_size,
        confidence=settings.liquidity_gap_default_confidence,
        persistence_score=settings.liquidity_gap_default_persistence,
        manipulation_risk=settings.liquidity_gap_default_manipulation_risk,
        timestamp=datetime.utcnow()
    )
