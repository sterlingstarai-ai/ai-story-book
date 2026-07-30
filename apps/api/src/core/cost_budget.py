"""전역 일일 생성 예산 가드레일 (S4 — cost-DoS 상한).

X-User-Key는 클라이언트가 임의로 발급하는 UUID라 사실상 미인증이고, 신규 키마다 가입
보너스 크레딧이 지급된다. 그래서 per-user 통제(레이트리밋 10/분·일일 20권·무료플랜 월 2권)는
전부 **키 로테이션 한 번으로 우회**되고, LLM/이미지 실비용이 무제한 소진된다.

완전 해법(디바이스 attestation·IP 지문)은 제품 결정이라 별도 스코프다. 여기서는 개별
식별자와 무관한 **서버측 전역 상한**만 둬서 최악의 청구서를 막는다 — 공격자가 키를 아무리
돌려도 하루 총 생성량이 예산을 넘지 못한다.

**Redis 장애 시 정책(창업자 결정): fail-open + 알림 강화.** 가용성을 우선하되, 감사 #8이
지적한 '무음 비활성'은 금지 — 가드레일이 꺼졌다는 사실을 error 레벨로 남겨 운영이 즉시
인지하게 한다.
"""

from typing import Tuple

import redis.asyncio as redis
import structlog

from src.core.config import settings
from src.core.rate_limit import rate_limiter
from src.core.utils import utcnow

logger = structlog.get_logger()

# 카운터가 날짜 키마다 무한 누적되지 않도록 하루 + 여유만큼만 보관.
_BUDGET_TTL_SECONDS = 60 * 60 * 26


def daily_budget_key() -> str:
    """UTC 날짜 기준 전역 카운터 키. 사용자·IP와 무관한 전역 단일 카운터다."""
    return f"cost_budget:generation:{utcnow().strftime('%Y%m%d')}"


async def consume_daily_generation_budget() -> Tuple[bool, int]:
    """전역 일일 생성 예산을 1 소비하고 (허용여부, 사용량)을 반환한다.

    - 예산이 0 이하면 기능 비활성(기본 배포에서 의도치 않은 차단 방지).
    - Redis 장애면 (True, 0)으로 통과시키되 **error 로그**를 남긴다(무음 비활성 금지).
    """
    limit = int(getattr(settings, "daily_generation_budget", 0) or 0)
    if limit <= 0:
        return True, 0

    key = daily_budget_key()
    try:
        r = await rate_limiter.get_redis()
        used = int(await r.incr(key))
        if used == 1:
            # 첫 증가에서만 TTL 부여(이후 EXPIRE로 창을 밀지 않도록).
            await r.expire(key, _BUDGET_TTL_SECONDS)
    except redis.RedisError as exc:
        # fail-open: 장애 창에서 서비스 핵심 기능을 막지 않는다. 다만 비용 상한이 사라진
        # 상태이므로 조용히 넘기지 않고 운영이 즉시 볼 수 있게 error로 남긴다.
        logger.error(
            "cost budget guardrail DISABLED (redis unavailable) — 전역 비용 상한 없음",
            error=str(exc),
            budget_key=key,
        )
        return True, 0

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
