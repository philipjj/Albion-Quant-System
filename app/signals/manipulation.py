"""
Manipulation signal detection.
"""

from datetime import datetime
from statistics import median

from app.signals.models import AlphaSignal


def detect_manipulation(item_id: str, price_history: list[float]) -> float:
    """
    Returns a manipulation risk score between 0 and 1.
    Flags sudden price spikes compared to the historical median.
    """
    if not price_history or len(price_history) < 3:
        return 0.0

    hist_median = median(price_history)
    if hist_median == 0:
        return 0.0

    latest_price = price_history[-1]
    ratio = latest_price / hist_median

    if ratio > 3.0:
        return 1.0
    if ratio > 2.0:
        return 0.8
    if ratio > 1.5:
        return 0.5

    return 0.0
