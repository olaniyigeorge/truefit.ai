# RedisCacheAdapter(CachePort): Implements the CachePort interface using Redis as the underlying cache mechanism.


import redis.asyncio as redis
from typing import Any, Optional
import json

from config import AppConfig
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

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def increment(self, key: str, *, ttl_seconds: Optional[int] = None) -> int:
        """Atomic increment — useful for rate limiting."""
        ...

    @abstractmethod
    async def is_healthy(self) -> bool: ...