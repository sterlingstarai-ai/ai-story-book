"""전역 일일 생성 예산 가드레일 (S4 — cost-DoS 상한).

X-User-Key는 클라이언트가 임의로 발급하는 UUID라 사실상 미인증이고, 신규 키마다 가입
보너스 크레딧이 지급된다. 그래서 per-user 통제(레이트리밋 10/분·일일 20권·무료플랜 월 2권)는
전부 **키 로테이션 한 번으로 우회**되고, LLM/이미지 실비용이 무제한 소진된다.

완전 해법(디바이스 attestation·IP 지문)은 제품 결정이라 별도 스코프다. 여기서는 개별
식별자와 무관한 **서버측 전역 상한**만 둬서 최악의 청구서를 막는다 — 공격자가 키를 아무리
돌려도 하루 총 생성량이 예산을 넘지 못한다.

Redis 장애 시 신규 생성을 일시 중단한다. 비용 한도를 확인하지 못한 요청을 통과시키면
키 회전으로 비용 제한을 우회할 수 있으므로, 복구 후 사용자가 다시 요청하도록 한다.
"""

from typing import Tuple

import redis.asyncio as redis
import structlog
from sqlalchemy import text

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import APIError
from src.core.rate_limit import rate_limiter
from src.core.utils import to_local_date, utcnow
from src.models.generation_budget import GenerationBudgetActivation  # noqa: F401

logger = structlog.get_logger()

# 카운터가 날짜 키마다 무한 누적되지 않도록 하루 + 여유만큼만 보관.
_BUDGET_TTL_SECONDS = 60 * 60 * 26

# The increment and expiry must be one Redis operation: a worker killed after
# INCR must not leave an immortal daily key. Repair legacy keys without TTL
# without extending the lifetime of keys that already expire.
_ADMIT_AND_EXPIRE = """
local used = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) == -1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return used
"""


def daily_budget_key() -> str:
    """한국 날짜 기준 전역 카운터 키. 사용자·IP와 무관한 단일 카운터다."""
    return f"cost_budget:generation:{to_local_date(utcnow()).strftime('%Y%m%d')}"


async def _postgres_current_day(db) -> str:
    if db.bind.dialect.name == "postgresql":
        return (await db.execute(text(
            "SELECT to_char(clock_timestamp() AT TIME ZONE 'Asia/Seoul', 'YYYYMMDD')"
        ))).scalar_one()
    if settings.testing:
        return to_local_date(utcnow(), tz="Asia/Seoul").strftime("%Y%m%d")
    raise ValueError("PostgreSQL required")


async def _postgres_counter(*, consume: bool, limit: int) -> tuple[bool, int]:
    """Commit an atomic reservation before any provider call; missing activation fails closed."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Lock first, then read the database clock. A request waiting across
            # midnight must not reserve against its old transaction-start day.
            lock = " FOR UPDATE" if db.bind.dialect.name == "postgresql" and consume else ""
            row = (await db.execute(text(
                "SELECT blocked_through_day, current_day, requests FROM generation_budget_activation WHERE id = 1"
                + lock
            ))).one_or_none()
            if row is None:
                raise ValueError("generation budget not initialized")
            day = await _postgres_current_day(db)
            activation, current, count = row
            if (not all(isinstance(d, str) and len(d) == 8 and d.isdigit() for d in (activation, current))
                    or current < activation or not isinstance(count, int) or count < 0):
                raise ValueError("invalid generation budget")
            if day <= activation or day < current:
                return False, limit
            if not consume:
                used = count if day == current else 0
                return used < limit, used
            result = await db.execute(text("""
                UPDATE generation_budget_activation
                SET requests = CASE WHEN current_day < :day THEN 1 ELSE requests + 1 END,
                    current_day = :day
                WHERE id = 1 AND :day > blocked_through_day AND :day >= current_day
                  AND (current_day < :day OR requests < :request_limit)
                RETURNING requests
            """), {"day": day, "request_limit": limit})
            used = result.scalar_one_or_none()
            return (False, limit + 1) if used is None else (True, int(used))


async def generation_budget_snapshot() -> dict:
    """Read the Korea-day admission counter without consuming a request."""
    limit = int(settings.daily_generation_budget or 0)
    result = {"limit": limit, "used": None, "unit": "generation_requests"}
    if limit <= 0:
        return {**result, "status": "disabled"}
    if settings.generation_budget_store == "postgres":
        try:
            allowed, used = await _postgres_counter(consume=False, limit=limit)
        except Exception:
            return {**result, "status": "unavailable"}
        return {**result, "used": used, "status": "available" if allowed else "exhausted"}
    try:
        client = await rate_limiter.get_redis()
        used = int(await client.get(daily_budget_key()) or 0)
        if used < 0:
            raise ValueError("Invalid counter")
    except (redis.RedisError, ValueError, TypeError):
        return {**result, "status": "unavailable"}
    return {**result, "used": used, "status": "exhausted" if used >= limit else "available"}


async def consume_daily_generation_budget() -> Tuple[bool, int]:
    """전역 일일 생성 예산을 1 소비하고 (허용여부, 사용량)을 반환한다.

    - 비테스트 환경에서 예산이 0 이하면 생성 중단. readiness를 우회하여
      API에 직접 요청해도 비용 제한 누락을 지나갈 수 없어야 한다.
    - 테스트 환경의 예산 0 이하는 기존처럼 기능을 비활성화한다.
    - Redis 장애면 503으로 중단해 확인할 수 없는 비용을 발생시키지 않는다.
    """
    limit = int(getattr(settings, "daily_generation_budget", 0) or 0)
    if limit <= 0:
        if settings.testing:
            return True, 0
        logger.error("cost budget unconfigured; generation blocked")
        raise APIError(
            status_code=503,
            error_code="SERVICE_UNAVAILABLE",
            message="생성 한도를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
            details={"retry_after": 30},
            headers={"Retry-After": "30"},
        )

    key = daily_budget_key()
    try:
        if settings.generation_budget_store == "postgres":
            allowed, used = await _postgres_counter(consume=True, limit=limit)
            if not allowed:
                return False, used
        else:
            r = await rate_limiter.get_redis()
            used = int(await r.eval(_ADMIT_AND_EXPIRE, 1, key, _BUDGET_TTL_SECONDS))
        if used < 1:
            raise ValueError('Invalid generation counter')
    except Exception as exc:
        logger.error(
            "cost budget verification unavailable; generation blocked",
            error_type=type(exc).__name__,
            budget_key=key,
        )
        raise APIError(
            status_code=503,
            error_code="SERVICE_UNAVAILABLE",
            message="생성 한도를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
            details={"retry_after": 30},
            headers={"Retry-After": "30"},
        ) from exc

    if used > limit:
        logger.error(
            "daily generation budget exhausted — 전역 생성 상한 도달",
            used=used,
            limit=limit,
            budget_key=key,
        )
        return False, used

    # 임계 근접(80%)에서 미리 경고해 운영이 상한 도달 전에 인지하게 한다.
    if used >= max(1, int(limit * 0.8)):
        logger.warning(
            "daily generation budget nearing limit",
            used=used,
            limit=limit,
        )
    return True, used


async def require_daily_generation_budget(endpoint: str) -> None:
    """Admit a paid provider call against the same global generation budget."""
    allowed, used = await consume_daily_generation_budget()
    if not allowed:
        raise APIError(
            status_code=429,
            error_code="SERVICE_BUDGET_EXCEEDED",
            message="오늘 생성 가능한 전체 한도에 도달했어요. 잠시 후 다시 시도해주세요.",
            details={
                "limit": settings.daily_generation_budget,
                "used": used,
                "endpoint": endpoint,
                "retry_after": 3600,
            },
            headers={"Retry-After": "3600"},
        )
