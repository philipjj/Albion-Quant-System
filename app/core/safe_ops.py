from typing import Any, Optional

def safe_int(value: Any, default: int = 0) -> int:
    """Safely converts a value to int, returning default if None or invalid."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely converts a value to float, returning default if None or invalid."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
