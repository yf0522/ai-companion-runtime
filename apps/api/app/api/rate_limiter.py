"""Redis-based rate limiter for API and WebSocket endpoints."""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

# In-memory fallback when Redis is unavailable
_mem_store: dict[str, list[float]] = {}


class RateLimitBackendUnavailable(RuntimeError):
    """The shared limiter is unavailable and policy forbids local fallback."""


class RateLimiter:
    """Sliding-window limiter with an explicit dependency-failure policy."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        failure_mode: str | None = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.failure_mode = failure_mode

    async def check(self, key: str) -> bool:
        """Returns True if the request is allowed, False if rate limited."""
        try:
            return await self._check_redis(key)
        except Exception as exc:
            from app.config.settings import settings

            mode = self.failure_mode or settings.rate_limit_failure_mode
            if mode == "memory" and settings.app_env.lower() != "production":
                logger.warning("Redis rate limiter unavailable; using development fallback")
                return self._check_memory(key)
            raise RateLimitBackendUnavailable("Shared rate limiter unavailable") from exc

    async def _check_redis(self, key: str) -> bool:
        from app.storage.redis_client import get_redis
        r = await get_redis()
        rate_key = f"rate:{key}"
        now = time.time()

        pipe = r.pipeline()
        pipe.zremrangebyscore(rate_key, 0, now - self.window_seconds)
        pipe.zadd(rate_key, {str(now): now})
        pipe.zcard(rate_key)
        pipe.expire(rate_key, self.window_seconds)
        results = await pipe.execute()
        count = results[2]
        return count <= self.max_requests

    def _check_memory(self, key: str) -> bool:
        now = time.time()
        if key not in _mem_store:
            _mem_store[key] = []
        # Clean old entries
        _mem_store[key] = [t for t in _mem_store[key] if t > now - self.window_seconds]
        _mem_store[key].append(now)
        return len(_mem_store[key]) <= self.max_requests


# Pre-configured limiters
auth_limiter = RateLimiter(max_requests=10, window_seconds=60)      # 10 login/register per minute
ws_message_limiter = RateLimiter(max_requests=30, window_seconds=60)  # 30 messages per minute
ws_connect_limiter = RateLimiter(max_requests=5, window_seconds=60)   # 5 connections per minute


def get_asr_limiter() -> RateLimiter:
    from app.config.settings import settings

    return RateLimiter(
        max_requests=settings.asr_rate_limit_per_minute,
        window_seconds=60,
    )


def get_tts_limiter() -> RateLimiter:
    from app.config.settings import settings

    return RateLimiter(
        max_requests=settings.tts_rate_limit_per_minute,
        window_seconds=60,
    )


def clear_memory_store() -> None:
    """Test helper: reset in-memory rate-limit buckets."""
    _mem_store.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to auth endpoints via middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            path = request.url.path
            if path in ("/api/auth/login", "/api/auth/register"):
                client_ip = request.client.host if request.client else "unknown"
                key = f"auth:{client_ip}:{path}"
                allowed = await auth_limiter.check(key)
                if not allowed:
                    raise HTTPException(
                        status_code=429,
                        detail="Too many requests. Please try again later.",
                    )
            return await call_next(request)
        except RateLimitBackendUnavailable as exc:
            raise HTTPException(status_code=503, detail="Rate limiting unavailable") from exc
