import asyncio
import time
import httpx
from typing import Optional, Any
from app.core.config import settings
from app.core.logging import log
from app.services.rate_limiter import limiter
from app.monitoring.metrics import metrics

class AQSHttpClient:
    """
    Centralized HTTP Client for AQS.
    Wraps httpx.AsyncClient with retry logic, rate limiting, and telemetry.
    """
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        self._timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=30.0,
            pool=30.0
        )
        self.telemetry = {
            "total_requests": 0,
            "retries": 0,
            "failures": 0,
            "latency_sum": 0.0,
            "status_codes": {}
        }

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=self._limits,
                headers={"Accept-Encoding": "gzip"},
                follow_redirects=True
            )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get(self, url: str, params: Optional[dict] = None, max_retries: int = 3) -> Optional[httpx.Response]:
        """Performs a GET request with rate limiting and retries."""
        await self._ensure_client()
        
        attempt = 0
        while attempt <= max_retries:
            # 1. Rate Limiter Acquisition
            await limiter.acquire()
            
            start_time = time.monotonic()
            try:
                self.telemetry["total_requests"] += 1
                resp = await self._client.get(url, params=params)
                latency = time.monotonic() - start_time
                metrics.track_api_request(latency, resp.status_code, attempt)
                
                # 2. Update Telemetry
                self.telemetry["latency_sum"] += latency
                code = resp.status_code
                self.telemetry["status_codes"][code] = self.telemetry["status_codes"].get(code, 0) + 1
                
                # 3. Handle Status
                if resp.status_code == 200:
                    limiter.report_success()
                    return resp
                
                if resp.status_code in [429, 500, 502, 503, 504]:
                    limiter.report_error(resp.status_code)
                    if attempt == max_retries:
                        log.error(f"🌐 HTTP: Max retries reached for {url} (Status: {resp.status_code})")
                        break
                    
                    # Exponential backoff + jitter
                    wait = (2 ** attempt) + limiter.get_retry_jitter()
                    log.warning(f"🌐 HTTP: Retry {attempt+1}/{max_retries} for {url} in {wait:.2f}s (Status: {resp.status_code})")
                    await asyncio.sleep(wait)
                    attempt += 1
                    self.telemetry["retries"] += 1
                    continue
                
                # Non-retryable errors (400, 401, 403, 404)
                log.error(f"🌐 HTTP: Non-retryable error {resp.status_code} for {url}")
                self.telemetry["failures"] += 1
                return resp
                
            except (httpx.RequestError, asyncio.TimeoutError) as e:
                metrics.track_api_request(0.0, 0, attempt)
                self.telemetry["failures"] += 1
                if attempt == max_retries:
                    log.error(f"🌐 HTTP: Connection failed after {max_retries} retries: {e}")
                    break
                
                wait = (2 ** attempt) + limiter.get_retry_jitter()
                log.warning(f"🌐 HTTP: Connection error. Retrying in {wait:.2f}s: {e}")
                await asyncio.sleep(wait)
                attempt += 1
                self.telemetry["retries"] += 1

        return None

# Global Instance
aqs_http = AQSHttpClient()
