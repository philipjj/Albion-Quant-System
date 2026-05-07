import time
from datetime import datetime, timedelta
from typing import Any, Dict

from app.core.logging import log


class MetricsManager:
    """
    Centralized metrics tracking for AQS.
    Handles API performance, data integrity, and trading analytics.
    """
    def __init__(self):
        self.api_metrics = {
            "requests_total": 0,
            "retries_total": 0,
            "errors_429": 0,
            "errors_other": 0,
            "latency_history": [], # Last 100 requests
        }
        self.data_metrics = {
            "records_ingested": 0,
            "stale_rejected": 0,
            "invalid_rejected": 0,
            "duplicates_filtered": 0,
        }
        self.trading_metrics = {
            "opportunities_found": 0,
            "false_positives": 0,
            "average_spread": 0.0,
        }
        self.start_time = datetime.utcnow()

    def track_api_request(self, latency: float, status_code: int, retries: int = 0):
        self.api_metrics["requests_total"] += 1
        self.api_metrics["retries_total"] += retries
        
        if status_code == 200:
            self.api_metrics["latency_history"].append(latency)
            if len(self.api_metrics["latency_history"]) > 100:
                self.api_metrics["latency_history"].pop(0)
        elif status_code == 429:
            self.api_metrics["errors_429"] += 1
        else:
            self.api_metrics["errors_other"] += 1

    def track_data_ingestion(self, ingested: int, stale: int = 0, invalid: int = 0):
        self.data_metrics["records_ingested"] += ingested
        self.data_metrics["stale_rejected"] += stale
        self.data_metrics["invalid_rejected"] += invalid

    def get_summary(self) -> dict[str, Any]:
        uptime = datetime.utcnow() - self.start_time
        avg_latency = 0
        if self.api_metrics["latency_history"]:
            avg_latency = sum(self.api_metrics["latency_history"]) / len(self.api_metrics["latency_history"])
            
        return {
            "uptime_seconds": int(uptime.total_seconds()),
            "api": {
                "total_requests": self.api_metrics["requests_total"],
                "avg_latency_ms": int(avg_latency * 1000),
                "error_rate": f"{(self.api_metrics['errors_other'] / max(1, self.api_metrics['requests_total'])) * 100:.2f}%",
                "count_429": self.api_metrics["errors_429"]
            },
            "data": {
                "records_total": self.data_metrics["records_ingested"],
                "rejection_rate": f"{( (self.data_metrics['stale_rejected'] + self.data_metrics['invalid_rejected']) / max(1, self.data_metrics['records_ingested'])) * 100:.2f}%"
            }
        }

# Global Instance
metrics = MetricsManager()
