"""Rate limiting using Redis sliding window."""

from fastapi import HTTPException, Request
import redis.asyncio as redis
from typing import Optional
import structlog
import uuid
import hashlib
from dataclasses import dataclass
from datetime import timezone
from src.core.config import settings
from src.core.exceptions import APIError, RateLimitError
from src.core.utils import utcnow


# Count only admitted requests; rejected retries neither occupy a slot nor extend
# the recovery window. Lua keeps check-and-admit atomic across API replicas.
_ADMIT_SCRIPT = """
local key, now, window, limit = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local first = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, 0, math.max(1, math.ceil(tonumber(first[2]) + window - now))}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('EXPIRE', key, math.ceil(window) + 1)
return {1, limit - count - 1, 0}
"""


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: int

    def __iter__(self):
        # Existing adapter callers consume the two-value contract.
        yield self.allowed
        yield self.remaining


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

    async def is_allowed(self, user_key: str, *, bucket: str = "write") -> RateDecision:
        """Atomically admit into a bounded read or write window."""
        r = await self.get_redis()
        now = utcnow().replace(tzinfo=timezone.utc).timestamp()
        limit = settings.rate_limit_read_requests if bucket == "read" else settings.rate_limit_requests
        key = f"rate_limit:{bucket}:{hashlib.sha256(user_key.encode()).hexdigest()}"
        admitted, remaining, retry_after = await r.eval(
            _ADMIT_SCRIPT, 1, key, now, settings.rate_limit_window,
            limit, _rate_limit_member(now),
        )
        return RateDecision(bool(admitted), int(remaining), int(retry_after))

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
        # Bound malformed/missing-credential requests too, without trusting
        # arbitrary proxy forwarding headers or recording an IP in Redis.
        client = getattr(request, "client", None)
        user_key = "anonymous:" + (getattr(client, "host", None) or "unknown")
    bucket = "read" if getattr(request, "method", "POST") in {"GET", "HEAD"} else "write"
    limit = settings.rate_limit_read_requests if bucket == "read" else settings.rate_limit_requests

    try:
        decision = await rate_limiter.is_allowed(user_key, bucket=bucket)
        is_allowed, remaining = decision

        # Add headers for client
        request.state.rate_limit_remaining = remaining
        request.state.rate_limit_limit = limit

        if not is_allowed:
            # M2: 봉투 코드는 **다른 모든 코드와 같은 UPPER_SNAKE**여야 한다. 여기만
            # 소문자 `rate_limit_exceeded` 였던 탓에, 서버 봉투 코드를 우선하는 모바일
            # (api_error.dart)이 `RATE_LIMIT_EXCEEDED` 분기에 매칭하지 못해 en/ja
            # 사용자에게 한국어 서버 문구가 그대로 노출됐다(M15 로컬라이즈 우회).
            # retry_after 는 details 로 내린다(RateLimitError 계약).
            raise RateLimitError(retry_after=getattr(decision, "retry_after", settings.rate_limit_window))
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
