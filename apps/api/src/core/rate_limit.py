"""Rate limiting using Redis sliding window."""

from fastapi import HTTPException, Request
from datetime import datetime, timezone
import redis.asyncio as redis
from typing import Optional
import structlog

from src.core.config import settings


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


logger = structlog.get_logger()


class RateLimiter:
    """Redis-based sliding window rate limiter."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None

    async def get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(settings.redis_url)
        return self._redis

    async def is_allowed(self, user_key: str) -> tuple[bool, int]:
        """
        Check if request is allowed for user.

        Returns:
            tuple: (is_allowed, remaining_requests)
        """
        r = await self.get_redis()
        now = utcnow().timestamp()
        window_start = now - settings.rate_limit_window

        key = f"rate_limit:{user_key}"

        pipe = r.pipeline()
        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Count requests in window
        pipe.zcard(key)
        # Set expiry
        pipe.expire(key, settings.rate_limit_window + 1)

        results = await pipe.execute()
        request_count = results[2]

        remaining = max(0, settings.rate_limit_requests - request_count)
        is_allowed = request_count <= settings.rate_limit_requests

        return is_allowed, remaining

    async def close(self):
        if self._redis:
            await self._redis.close()


rate_limiter = RateLimiter()


async def check_rate_limit(request: Request):
    """FastAPI dependency for rate limiting."""
    user_key = request.headers.get("X-User-Key")

    if not user_key:
        # Let the endpoint handle missing user_key
        return

    try:
        is_allowed, remaining = await rate_limiter.is_allowed(user_key)

        # Add headers for client
        request.state.rate_limit_remaining = remaining
        request.state.rate_limit_limit = settings.rate_limit_requests

        if not is_allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": f"요청 한도 초과. {settings.rate_limit_window}초 후 다시 시도해주세요.",
                    "retry_after": settings.rate_limit_window,
                },
            )
    except redis.RedisError as e:
        # If Redis is down, log and allow request (fail open for availability)
        # In production, consider fail-closed behavior for security-critical endpoints
        logger.warning(
            "Rate limiter Redis error - allowing request (fail-open)",
            user_key=user_key[:8] + "..." if user_key else None,
            error=str(e),
        )
    except Exception as e:
        # Unexpected errors should be logged but not block requests
        logger.error(
            "Rate limiter unexpected error",
            user_key=user_key[:8] + "..." if user_key else None,
            error=str(e),
        )
