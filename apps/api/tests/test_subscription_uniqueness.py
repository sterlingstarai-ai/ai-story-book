"""M17 — 사용자당 active 구독 최대 1행을 DB(부분 유니크)로 강제 + 동시 create 흡수.

check-then-write(get_active_subscription SELECT 후 active INSERT) 사이에 DB 제약이 없어
동시 두 verify/restore가 active 2행을 만들면 periodic_credits가 영구 이중 지급하던 결함.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.utils import utcnow
from src.models.db import Subscription
from src.services.credits import credits_service


def _active(user_key: str, plan: str = "basic", cpm: int = 10) -> Subscription:
    now = utcnow()
    return Subscription(
        user_key=user_key,
        plan=plan,
        status="active",
        credits_per_month=cpm,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )


async def _active_count(db, user_key: str) -> int:
    res = await db.execute(
        select(Subscription).where(
            Subscription.user_key == user_key, Subscription.status == "active"
        )
    )
    return len(res.scalars().all())


@pytest.mark.asyncio
async def test_active_subscription_partial_unique_blocks_second(db_session):
    """같은 user_key로 active 2행 직접 insert 시 두 번째는 IntegrityError."""
    uk = "uniq-user"
    db_session.add(_active(uk, "basic"))
    await db_session.commit()

    db_session.add(_active(uk, "premium", 30))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # cancelled/expired는 제약 대상 아님 — active 옆에 공존 가능.
    other = _active(uk, "basic")
    other.status = "cancelled"
    db_session.add(other)
    await db_session.commit()  # 충돌 없어야 함


@pytest.mark.asyncio
async def test_create_subscription_happy_upgrade_keeps_single_active(db_session):
    """정상 업그레이드(basic→premium): 기존 active 취소를 먼저 flush → 단일 active 유지."""
    uk = "upgrade-user"
    await credits_service.create_subscription(db_session, uk, "basic")
    assert await _active_count(db_session, uk) == 1

    await credits_service.create_subscription(db_session, uk, "premium")
    assert await _active_count(db_session, uk) == 1
    active = await credits_service.get_active_subscription(db_session, uk)
    assert active is not None and active.plan == "premium"


@pytest.mark.asyncio
async def test_create_subscription_absorbs_race_integrity_error(db_session, monkeypatch):
    """경쟁 패자 시뮬레이션: 첫 조회가 경쟁 active를 못 봐 flush가 부분 유니크 위반 →
    IntegrityError 흡수·재조회 후 재시도 → 최종 active 정확히 1행."""
    uk = "race-user"
    # 경쟁 세션이 이미 커밋해 둔 active 구독.
    db_session.add(_active(uk, "basic"))
    await db_session.commit()

    real_get = credits_service.get_active_subscription
    calls = {"n": 0}

    async def fake_get(db, user_key):
        calls["n"] += 1
        if calls["n"] == 1 and user_key == uk:
            return None  # stale-miss: 경쟁 active를 못 본 상황
        return await real_get(db, user_key)

    monkeypatch.setattr(credits_service, "get_active_subscription", fake_get)

    sub = await credits_service.create_subscription(db_session, uk, "premium")
    assert sub is not None
    assert await _active_count(db_session, uk) == 1
