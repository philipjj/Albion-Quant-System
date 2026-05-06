"""
Feature Gate and Endpoint Health Monitoring.
Tracks which Albion API features are currently available for the active region.
"""
from app.core.logging import log


class FeatureGate:
    _instance = None

    # Feature states
    orders_supported = True
    history_supported = True
    prices_supported = True

    # Rate limiting protection
    is_rate_limited = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def report_failure(self, endpoint: str, status_code: int):
        """Handle different failure modes and update gates."""
        if status_code == 404:
            if endpoint == "orders" and self.orders_supported:
                self.orders_supported = False
                log.warning("⚠️ [GATE] Orders endpoint returned 404. Disabling supply metrics for this session.")
            elif endpoint == "history" and self.history_supported:
                self.history_supported = False
                log.error("❌ [GATE] History endpoint returned 404. Demand verification will be estimated.")

        elif status_code == 429:
            self.is_rate_limited = True
            log.error("🚫 [GATE] RATE LIMITED (429). Throttling all requests.")

        elif status_code >= 500:
            log.error(f"🔥 [GATE] API Server Error ({status_code}). Data may be stale.")

    def reset_limits(self):
        self.is_rate_limited = False

# Singleton instance
feature_gate = FeatureGate()
