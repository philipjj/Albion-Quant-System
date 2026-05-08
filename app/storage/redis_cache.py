import json
import logging
from typing import Optional, List
import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from shared.domain.market_snapshot import MarketSnapshot
from shared.domain.opportunity import Opportunity

logger = logging.getLogger(__name__)

class RedisCache:
    """
    Redis cache layer for hot market data and opportunities.
    Uses async Redis client.
    Handles connection errors gracefully for environments without Redis.
    """
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
        self._connected = True

    async def get_hot_snapshot(self, item_id: str, city: str) -> Optional[MarketSnapshot]:
        if not self._connected:
            return None
        key = f"snapshot:{item_id}:{city}"
        try:
            data = await self.redis.get(key)
            if not data:
                return None
            return MarketSnapshot(**json.loads(data))
        except RedisConnectionError:
            logger.warning("Redis connection failed. Running without Redis cache.")
            self._connected = False
            return None
        except Exception as e:
            logger.error(f"Error reading from Redis: {e}")
            return None

    async def set_hot_snapshot(self, snapshot: MarketSnapshot, expire_seconds: int = 300) -> None:
        if not self._connected:
            return
        key = f"snapshot:{snapshot.item_id}:{snapshot.city}"
        try:
            await self.redis.set(key, json.dumps(snapshot.dict(), default=str), ex=expire_seconds)
        except RedisConnectionError:
            logger.warning("Redis connection failed. Running without Redis cache.")
            self._connected = False
        except Exception as e:
            logger.error(f"Error writing to Redis: {e}")

    async def get_active_opportunities(self) -> List[Opportunity]:
        if not self._connected:
            return []
        key = "active_opportunities"
        try:
            data = await self.redis.get(key)
            if not data:
                return []
            items = json.loads(data)
            return [Opportunity(**item) for item in items]
        except RedisConnectionError:
            logger.warning("Redis connection failed. Running without Redis cache.")
            self._connected = False
            return []
        except Exception as e:
            logger.error(f"Error reading opportunities from Redis: {e}")
            return []

    async def set_active_opportunities(self, opportunities: List[Opportunity], expire_seconds: int = 60) -> None:
        if not self._connected:
            return
        key = "active_opportunities"
        try:
            items = [o.dict() for o in opportunities]
            await self.redis.set(key, json.dumps(items, default=str), ex=expire_seconds)
        except RedisConnectionError:
            logger.warning("Redis connection failed. Running without Redis cache.")
            self._connected = False
        except Exception as e:
            logger.error(f"Error writing opportunities to Redis: {e}")
