"""Rate limiting using Redis sliding window."""

from fastapi import HTTPException, Request
import redis.asyncio as redis
from typing import Optional
import structlog
import uuid
import hashlib

from src.core.config import settings
from src.core.exceptions import APIError, RateLimitError
from src.core.utils import utcnow

logger = structlog.get_logger()


def _rate_limit_member(now_ts: float) -> str:
    """Build unique sorted-set member to prevent timestamp collision overrides."""
    return f"{now_ts}:{uuid.uuid4().hex}"


class RateLimiter:
    """Redis-based sliding window rate limiter."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None

    async def get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url, socket_connect_timeout=2, socket_timeout=2
            )
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

        # Headers may contain a recovered device bearer. Redis persistence and
        # diagnostics must not expose a credential capable of accessing a child.
        key = f"rate_limit:{hashlib.sha256(user_key.encode()).hexdigest()}"
        member = _rate_limit_member(now)

        pipe = r.pipeline()
        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Add current request
        pipe.zadd(key, {member: now})
        # Count requests in window
        pipe.zcard(key)
        # Set expiry
        pipe.expire(key, settings.rate_limit_window + 1)

        results = await pipe.execute()
        request_count = results[2]

        remaining = max(0, settings.rate_limit_requests - request_count)
        is_allowed = request_count <= settings.rate_limit_requests

        return is_allowed, remaining

    async def ping(self) -> bool:
        """Check Redis connectivity without mutating rate-limit state."""
        try:
            r = await self.get_redis()
            pong = await r.ping()
            return bool(pong)
        except redis.RedisError:
            return False

    async def close(self):
        if not self._redis:
            return

        # redis-py async client API changed across versions (`close` -> `aclose`).
        # Prefer `aclose` when available and fall back to legacy `close`.
        aclose = getattr(self._redis, "aclose", None)
        if aclose is not None:
            await aclose()
        else:
            await self._redis.close()

        self._redis = None


rate_limiter = RateLimiter()


async def check_rate_limit(request: Request):
    """FastAPI dependency for rate limiting."""
    # 테스트에선 기본 우회(시간 기반 리미터가 실행 속도에 따라 플래키 429를 냄).
    # 레이트리밋을 검증하는 테스트만 rate_limit_enforce_in_testing=True로 켠다.
    if settings.testing and not settings.rate_limit_enforce_in_testing:
        return
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
            # M2: 봉투 코드는 **다른 모든 코드와 같은 UPPER_SNAKE**여야 한다. 여기만
            # 소문자 `rate_limit_exceeded` 였던 탓에, 서버 봉투 코드를 우선하는 모바일
            # (api_error.dart)이 `RATE_LIMIT_EXCEEDED` 분기에 매칭하지 못해 en/ja
            # 사용자에게 한국어 서버 문구가 그대로 노출됐다(M15 로컬라이즈 우회).
            # retry_after 는 details 로 내린다(RateLimitError 계약).
            raise RateLimitError(retry_after=settings.rate_limit_window)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Rate limit verification unavailable; request blocked",
            error_type=type(e).__name__,
        )
        raise APIError(
            status_code=503,
            error_code="SERVICE_UNAVAILABLE",
            message="요청 한도를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
            details={"retry_after": 30},
            headers={"Retry-After": "30"},
        ) from e
