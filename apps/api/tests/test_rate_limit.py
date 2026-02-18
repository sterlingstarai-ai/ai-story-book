import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from src.core.config import settings
from src.core.rate_limit import RateLimiter, check_rate_limit, rate_limiter


@pytest.mark.asyncio
async def test_is_allowed_uses_unique_zset_member(monkeypatch: pytest.MonkeyPatch):
    limiter = RateLimiter()

    pipe = MagicMock()
    pipe.zremrangebyscore.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zcard.return_value = pipe
    pipe.expire.return_value = pipe
    pipe.execute = AsyncMock(return_value=[0, 1, 1, True])

    redis_client = MagicMock()
    redis_client.pipeline.return_value = pipe
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis_client))

    fixed_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.core.rate_limit.utcnow", lambda: fixed_dt)

    class _FixedUUID:
        hex = "abc123"

    monkeypatch.setattr("src.core.rate_limit.uuid.uuid4", lambda: _FixedUUID())

    allowed, remaining = await limiter.is_allowed("test-user")

    now_ts = fixed_dt.timestamp()
    window_start = now_ts - settings.rate_limit_window

    pipe.zremrangebyscore.assert_called_once_with("rate_limit:test-user", 0, window_start)
    pipe.zadd.assert_called_once_with(
        "rate_limit:test-user",
        {f"{now_ts}:abc123": now_ts},
    )
    pipe.zcard.assert_called_once_with("rate_limit:test-user")
    pipe.expire.assert_called_once_with("rate_limit:test-user", settings.rate_limit_window + 1)

    assert allowed is True
    assert remaining == max(0, settings.rate_limit_requests - 1)


@pytest.mark.asyncio
async def test_is_allowed_blocks_when_count_exceeds_limit(monkeypatch: pytest.MonkeyPatch):
    limiter = RateLimiter()

    over_limit_count = settings.rate_limit_requests + 1
    pipe = MagicMock()
    pipe.zremrangebyscore.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zcard.return_value = pipe
    pipe.expire.return_value = pipe
    pipe.execute = AsyncMock(return_value=[0, 1, over_limit_count, True])

    redis_client = MagicMock()
    redis_client.pipeline.return_value = pipe
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis_client))

    allowed, remaining = await limiter.is_allowed("test-user")

    assert allowed is False
    assert remaining == 0


@pytest.mark.asyncio
async def test_check_rate_limit_raises_429_when_limit_exceeded(
    monkeypatch: pytest.MonkeyPatch,
):
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


@pytest.mark.asyncio
async def test_check_rate_limit_allows_when_within_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    request = SimpleNamespace(
        headers={"X-User-Key": "test-user"},
        state=SimpleNamespace(),
    )
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(return_value=(True, 3)))

    await check_rate_limit(request)

    assert request.state.rate_limit_remaining == 3
    assert request.state.rate_limit_limit == settings.rate_limit_requests
