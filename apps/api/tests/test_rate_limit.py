import pytest
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
import redis.asyncio as redis
from src.core.config import settings
from src.core.rate_limit import RateLimiter, check_rate_limit, rate_limiter


@pytest.mark.asyncio
async def test_is_allowed_uses_unique_members_and_bounded_atomic_script(monkeypatch):
    limiter = RateLimiter()
    from tests.fake_redis import FakeRedis
    fake = FakeRedis()
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=fake))
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("src.core.rate_limit.utcnow", lambda: instant)
    for _ in range(settings.rate_limit_requests):
        decision = await limiter.is_allowed("test-user")
        assert decision.allowed
    denied = await limiter.is_allowed("test-user")
    assert not denied.allowed
    assert denied.retry_after == settings.rate_limit_window
    key = f"rate_limit:write:{hashlib.sha256(b'test-user').hexdigest()}"
    assert len(fake.sorted_sets[key]) == settings.rate_limit_requests


@pytest.mark.asyncio
async def test_rejected_polls_do_not_extend_window_or_consume_write_slots(monkeypatch):
    from datetime import timedelta
    from tests.fake_redis import FakeRedis
    limiter, fake = RateLimiter(), FakeRedis()
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=fake))
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = [instant]
    monkeypatch.setattr("src.core.rate_limit.utcnow", lambda: clock[0])
    for _ in range(settings.rate_limit_requests):
        assert (await limiter.is_allowed("test-user")).allowed
    clock[0] += timedelta(seconds=30)
    for _ in range(30):
        decision = await limiter.is_allowed("test-user")
        assert not decision.allowed and decision.retry_after == 30
        assert (await limiter.is_allowed("test-user", bucket="read")).allowed
    clock[0] += timedelta(seconds=30)
    assert (await limiter.is_allowed("test-user")).allowed


@pytest.mark.asyncio
async def test_check_rate_limit_raises_429_when_limit_exceeded(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    request = SimpleNamespace(
        headers={"X-User-Key": "test-user"},
        state=SimpleNamespace(),
    )
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(return_value=(False, 0)))

    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(request)

    assert exc.value.status_code == 429
    assert request.state.rate_limit_remaining == 0
    assert request.state.rate_limit_limit == settings.rate_limit_requests
    assert exc.value.headers == {"Retry-After": str(settings.rate_limit_window)}


@pytest.mark.asyncio
async def test_check_rate_limit_allows_when_within_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    request = SimpleNamespace(
        headers={"X-User-Key": "test-user"},
        state=SimpleNamespace(),
    )
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(return_value=(True, 3)))

    await check_rate_limit(request)

    assert request.state.rate_limit_remaining == 3
    assert request.state.rate_limit_limit == settings.rate_limit_requests


@pytest.mark.asyncio
async def test_ping_returns_true_when_redis_responds(monkeypatch: pytest.MonkeyPatch):
    limiter = RateLimiter()
    redis_client = MagicMock()
    redis_client.ping = AsyncMock(return_value=True)
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis_client))

    assert await limiter.ping() is True


@pytest.mark.asyncio
async def test_ping_returns_false_on_redis_error(monkeypatch: pytest.MonkeyPatch):
    limiter = RateLimiter()
    monkeypatch.setattr(
        limiter,
        "get_redis",
        AsyncMock(side_effect=redis.RedisError("Connection refused")),
    )

    assert await limiter.ping() is False


@pytest.mark.asyncio
async def test_close_prefers_aclose_when_available():
    limiter = RateLimiter()
    redis_client = MagicMock()
    redis_client.aclose = AsyncMock()
    redis_client.close = AsyncMock()
    limiter._redis = redis_client

    await limiter.close()

    redis_client.aclose.assert_awaited_once()
    redis_client.close.assert_not_called()
    assert limiter._redis is None


@pytest.mark.asyncio
async def test_close_falls_back_to_close_when_aclose_missing():
    limiter = RateLimiter()

    class LegacyRedisClient:
        def __init__(self):
            self.close = AsyncMock()

    redis_client = LegacyRedisClient()
    limiter._redis = redis_client

    await limiter.close()

    redis_client.close.assert_awaited_once()
    assert limiter._redis is None


@pytest.mark.asyncio
async def test_close_noop_when_redis_not_initialized():
    limiter = RateLimiter()

    await limiter.close()

    assert limiter._redis is None
