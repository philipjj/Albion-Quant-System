import asyncio
import random
import time

from app.core.logging import log


class DeterministicRateLimiter:
    """
    Deterministic Async Rate Limiter for AQS v3.1+.
    Ensures hard spacing between requests and dynamic adjustment based on server pressure.
    """
    def __init__(self, min_interval: float = 0.5):
        self.min_interval = min_interval
        self.slowdown_factor = 1.0
        self.max_slowdown = 5.0
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        """
        Global entry point for all API calls. 
        Guarantees min_interval * slowdown_factor spacing between the END of the last 
        request's acquisition and the START of the next.
        """
        async with self._lock:
            now = time.monotonic()
            # Calculate the next allowed start time
            effective_interval = self.min_interval * self.slowdown_factor
            target_time = self.last_request_time + effective_interval
            
            wait_time = target_time - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            self.last_request_time = time.monotonic()

    def report_error(self, status_code: int):
        """
        Call this when a request fails.
        If status is 429, we aggressively increase the slowdown factor.
        """
        if status_code == 429:
            self.slowdown_factor = min(self.slowdown_factor * 1.25, self.max_slowdown)
            log.warning(f"⚖️ RATE LIMITER: 429 Detected. Slowing down. Factor: {self.slowdown_factor:.2f}")

    def report_success(self):
        """
        Call this when a request succeeds.
        Slowly decays the slowdown factor back to 1.0.
        """
        if self.slowdown_factor > 1.0:
            # Very slow recovery (1% per success)
            self.slowdown_factor = max(self.slowdown_factor * 0.99, 1.0)
            if self.slowdown_factor == 1.0:
                log.info("⚖️ RATE LIMITER: Back to normal speed (1.0x)")

    def get_retry_jitter(self) -> float:
        """Standardized jitter for retry logic."""
        return random.uniform(0.1, 1.0)

# Global Instance
limiter = DeterministicRateLimiter()
