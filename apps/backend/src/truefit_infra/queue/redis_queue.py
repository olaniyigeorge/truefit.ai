from __future__ import annotations

import json

import redis.asyncio as redis

from src.truefit_core.application.ports import QueuePort, DomainEvent
from src.truefit_infra.config import AppConfig
from src.truefit_core.common.utils import logger

_STREAM_PREFIX = "events"
_MAX_STREAM_LEN = 10_000


class RedisQueueAdapter(QueuePort):

    def __init__(self, conn_url: str | None = None) -> None:
        url = conn_url or AppConfig.REDIS_URL
        if not url:
            raise RuntimeError("Redis URL is not configured.")
        self._client: redis.Redis = redis.from_url(url, decode_responses=True)

    async def publish(self, event: DomainEvent) -> None:
        stream_key = f"{_STREAM_PREFIX}:{event.event_type}"
        try:
            await self._client.xadd(
                stream_key,
                {
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "aggregate_type": event.aggregate_type,
                    "occurred_at": event.occurred_at,
                    "payload": json.dumps(event.payload),
                },
                maxlen=_MAX_STREAM_LEN,
                approximate=True,
            )
            logger.debug(f"[Queue] {event.event_type} -> {stream_key}")
        except redis.RedisError as e:
            logger.error(f"[Queue] Failed to publish {event.event_type}: {e}")

    async def is_healthy(self) -> bool:
        try:
            return await self._client.ping()
        except redis.RedisError:
            return False
