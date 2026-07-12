from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis

from app.config.settings import settings

logger = logging.getLogger(__name__)

_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.from_url(
            settings.redis_url,
            password=settings.redis_password or None,
            decode_responses=True,
            max_connections=20,
        )
        logger.info("Redis client initialized")
    return _pool


async def close_redis():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
