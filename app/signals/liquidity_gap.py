"""
Liquidity gap signal generation.
"""
from datetime import datetime
from app.signals.models import AlphaSignal

def generate_liquidity_gap_signal(item_id: str, cluster_id: str, gap_size: float) -> AlphaSignal:
    """
    Generates an AlphaSignal based on liquidity gap.
    """
    return AlphaSignal(
        signal_type="liquidity_gap",
        item_id=item_id,
        cluster_id=cluster_id,
        alpha_score=gap_size,
        confidence=0.6,
        persistence_score=0.5,
        manipulation_risk=0.2,
        timestamp=datetime.utcnow()
    )
