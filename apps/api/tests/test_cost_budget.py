"""S4: 전역 일일 생성 예산 가드레일 (cost-DoS 상한).

X-User-Key는 클라이언트가 임의 발급하는 UUID라 사실상 미인증이고, 신규 키마다 3크레딧이
지급된다. 따라서 per-user 통제(rate limit·일일한도·무료플랜)는 전부 키 로테이션으로 우회되고
LLM/이미지 실비용이 무제한 소진된다. 완전 해법(디바이스 attestation)은 제품 결정이므로,
이번에는 **서버측 전역 상한**만 둬서 청구서 폭증을 막는다.

정책(창업자 결정): Redis 장애로 카운터를 읽을 수 없으면 **fail-open + 알림 강화** —
가용성을 지키되 '비용 가드레일이 무음으로 비활성'되는 상태를 error 로그로 반드시 남긴다.
"""

import pytest

from src.core.config import settings
from src.core.cost_budget import (
    consume_daily_generation_budget,
    daily_budget_key,
)


class _FakeRedis:
    """최하위 Redis 경계 대체 — INCR/EXPIRE 의미만 재현."""

    def __init__(self):
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> bool:
        self.expires[key] = ttl
        return True


class _BrokenRedis:
    async def incr(self, key: str):
        import redis.asyncio as redis

        raise redis.RedisError("redis down")

    async def expire(self, key: str, ttl: int):
        return False


@pytest.fixture
def budget_env(monkeypatch):
    monkeypatch.setattr(settings, "daily_generation_budget", 3)
    fake = _FakeRedis()

    async def fake_get_redis():
        return fake

    from src.core import cost_budget

    monkeypatch.setattr(cost_budget.rate_limiter, "get_redis", fake_get_redis)
    return fake


@pytest.mark.asyncio
async def test_budget_allows_requests_under_limit(budget_env):
    """정상 범위는 통과 — 가드레일이 평상시 트래픽을 막으면 안 된다."""
    for _ in range(3):
        allowed, used = await consume_daily_generation_budget()
        assert allowed is True
    assert used == 3


@pytest.mark.asyncio
async def test_budget_blocks_over_limit(budget_env):
    """전역 상한 초과 → 차단(호출부가 429로 변환)."""
    for _ in range(3):
        await consume_daily_generation_budget()

    allowed, used = await consume_daily_generation_budget()
    assert allowed is False, "전역 예산을 넘겨도 통과하면 비용 상한이 없는 것"
    assert used == 4


@pytest.mark.asyncio
async def test_budget_key_is_per_day(budget_env, monkeypatch):
    """키가 날짜별이라 다음 날 예산이 자연 리셋된다."""
    from datetime import datetime

    from src.core import cost_budget

    monkeypatch.setattr(
        cost_budget, "utcnow", lambda: datetime(2026, 7, 29, 12, 0, 0)
    )
    day1 = daily_budget_key()
    monkeypatch.setattr(
        cost_budget, "utcnow", lambda: datetime(2026, 7, 30, 12, 0, 0)
    )
    assert daily_budget_key() != day1


@pytest.mark.asyncio
async def test_budget_sets_expiry_so_counters_do_not_leak(budget_env):
    """카운터에 TTL이 없으면 날짜 키가 무한 누적된다."""
    await consume_daily_generation_budget()
    assert budget_env.expires, "일일 카운터에 만료가 설정돼야 함"


@pytest.mark.asyncio
async def test_budget_fails_open_but_alerts_when_redis_down(monkeypatch, caplog):
    """창업자 결정: Redis 장애 시 fail-open + **알림 강화**.

    무음 통과(감사 #8이 지적한 fail-open의 핵심 문제)를 금지 — 비용 가드레일이 비활성
    됐다는 사실이 error 레벨로 반드시 남아야 운영이 즉시 인지한다.
    """
    from src.core import cost_budget

    monkeypatch.setattr(settings, "daily_generation_budget", 1)

    async def broken_get_redis():
        return _BrokenRedis()

    monkeypatch.setattr(cost_budget.rate_limiter, "get_redis", broken_get_redis)

    with caplog.at_level("ERROR"):
        allowed, used = await consume_daily_generation_budget()

    assert allowed is True, "가용성 우선 — 장애 창에서 생성을 막지 않는다"
    assert used == 0
    assert any(
        record.levelname == "ERROR" for record in caplog.records
    ), "비용 가드레일 비활성이 무음이면 운영이 인지하지 못한다"


@pytest.mark.asyncio
async def test_budget_disabled_when_limit_not_positive(monkeypatch):
    """예산 0/음수 = 기능 비활성(기본 배포에서 의도치 않은 차단 방지)."""
    from src.core import cost_budget

    monkeypatch.setattr(settings, "daily_generation_budget", 0)

    called = {"n": 0}

    async def should_not_be_called():
        called["n"] += 1
        raise AssertionError("비활성인데 Redis를 건드리면 안 됨")

    monkeypatch.setattr(cost_budget.rate_limiter, "get_redis", should_not_be_called)

    allowed, used = await consume_daily_generation_budget()
    assert allowed is True
    assert called["n"] == 0


# ───────────────── 엔드포인트 실경로: 상한 도달 시 429 ─────────────────


@pytest.mark.asyncio
async def test_create_book_returns_429_when_global_budget_exhausted(
    client, headers, valid_book_spec, monkeypatch
):
    """전역 예산 소진 시 생성 요청이 429로 차단된다(실경로).

    per-user 한도가 아니라 전역 상한이므로, 키를 바꿔도 같은 429가 나온다 —
    이것이 키 로테이션 비용 공격을 막는 지점이다.
    """
    from src.routers import books as books_router

    async def exhausted():
        return False, 999

    monkeypatch.setattr(
        books_router, "consume_daily_generation_budget", exhausted
    )

    res = await client.post("/v1/books", json=valid_book_spec, headers=headers)
    assert res.status_code == 429, res.text
    body = res.json()
    detail = body.get("error", {}).get("details") or body.get("detail")
    assert "service_budget_exceeded" in str(detail) or "service_budget_exceeded" in str(body)

    # 다른 user_key(로테이션)도 동일하게 차단돼야 전역 상한의 의미가 있다.
    other = {"X-User-Key": "11111111-2222-3333-4444-555555555555"}
    res2 = await client.post("/v1/books", json=valid_book_spec, headers=other)
    assert res2.status_code == 429, res2.text


@pytest.mark.asyncio
async def test_create_book_passes_when_budget_available(
    client, headers, valid_book_spec, monkeypatch
):
    """예산 여유 시 정상 생성 — 가드레일이 평상시를 막으면 안 된다."""
    from src.routers import books as books_router

    async def ok():
        return True, 1

    monkeypatch.setattr(books_router, "consume_daily_generation_budget", ok)

    res = await client.post("/v1/books", json=valid_book_spec, headers=headers)
    assert res.status_code in (200, 201), res.text
