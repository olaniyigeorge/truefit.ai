import redis.asyncio as redis
from typing import Any, Optional
import json

from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger
from src.truefit_core.application.ports import CachePort


class RedisCacheAdapter(CachePort):

    def __init__(self, conn_url: str | None):
        if not conn_url and not AppConfig.REDIS_URL:
            raise RuntimeError("Redis URL is not configured.")
        self._client: redis.Redis = redis.from_url(AppConfig.REDIS_URL, decode_responses=True)

    async def get_instance(cls):
        if cls._instance is None:
            if not AppConfig.REDIS_URL:
                raise RuntimeError("Redis URL is not configured.")
            cls._instance = redis.from_url(AppConfig.REDIS_URL, decode_responses=True)
        return cls._instance

    async def close_instance(cls):
        if cls._instance:
            await cls._instance.close()
            cls._instance = None


    async def get(self, key: str) -> Optional[Any]:
        data = await self._client.get(key)
        return json.loads(data) if data else None

    
    async def set(self, key: str, value: Any, *, ttl_seconds: Optional[int] = None) -> bool:
        try:
            await self._client.setex(key, ttl=ttl_seconds, value=value)
            return True
        except Exception as e:
            logger.info("Error setting value to Redis:", e)
            return False

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        return await self._client.exists(key) > 0

    async def increment(self, key: str, *, ttl_seconds: Optional[int] = None) -> int:
        """Atomic increment — useful for rate limiting."""
        new_value = await self._client.incr(key)
        if ttl_seconds is not None:
            await self._client.expire(key, ttl_seconds)
        return new_value

    async def is_healthy(self) -> bool:
        try:
            print("Pinging Redis...", self._client)
            await self._client.ping()
            return True
        except Exception:
            return False
        


redis_client = RedisCacheAdapter(AppConfig.REDIS_URL)