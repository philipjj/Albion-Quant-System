"""
Hermes Signal Analysis.
Provides analysis of generated signals.
"""

from app.signals.models import AlphaSignal


def analyze_signals(signals: list[AlphaSignal]) -> str:
    """
    Analyzes a list of signals and returns an explanation.
    """
    if not signals:
        return "No signals to analyze."

    high_confidence = [s for s in signals if s.confidence > 0.8]
    return f"Analyzed {len(signals)} signals. Found {len(high_confidence)} high-confidence opportunities ready for execution."
