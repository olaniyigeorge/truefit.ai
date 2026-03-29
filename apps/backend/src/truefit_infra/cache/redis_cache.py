import redis.asyncio as redis
from typing import Any, Optional
import json

from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger
from src.truefit_core.application.ports import CachePort


class RedisCacheAdapter(CachePort):

    def __init__(self, conn_url: str | None = None) -> None:
        url = conn_url or AppConfig.REDIS_URL
        if not url:
            raise RuntimeError("Redis URL is not configured.")
        self._client: redis.Redis = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[Any]:
        data = await self._client.get(key)
        return json.loads(data) if data else None

    async def set(
        self, key: str, value: Any, *, ttl_seconds: Optional[int] = None
    ) -> bool:
        try:
            serialized = json.dumps(
                value
            )  
            if ttl_seconds is not None:
                await self._client.setex(
                    key, ttl_seconds, serialized
                ) 
            else:
                await self._client.set(key, serialized)
            return True
        except Exception as e:
            logger.error(f"[Cache] SET {key} failed: {e}")
            return False

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        return await self._client.exists(key) > 0

    async def increment(self, key: str, *, ttl_seconds: Optional[int] = None) -> int:
        new_value = await self._client.incr(key)
        if ttl_seconds is not None:
            await self._client.expire(key, ttl_seconds)
        return new_value

    async def is_healthy(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception:
            return False


redis_client = RedisCacheAdapter(AppConfig.REDIS_URL)
