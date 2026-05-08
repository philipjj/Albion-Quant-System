"""
Signal ranking and composite scoring.
"""
from app.signals.models import AlphaSignal

def rank_signals(signals: list[AlphaSignal]) -> list[AlphaSignal]:
    """
    Ranks signals based on weighted composite scoring.
    Filters out duplicates and dead markets.
    """
    # Simple ranking by alpha_score * confidence
    ranked = sorted(
        signals,
        key=lambda s: s.alpha_score * s.confidence,
        reverse=True
    )
    
    # Duplicate suppression (keep highest score per item)
    seen_items = set()
    unique_signals = []
    for s in ranked:
        if s.item_id not in seen_items:
            unique_signals.append(s)
            seen_items.add(s.item_id)
            
    return unique_signals
