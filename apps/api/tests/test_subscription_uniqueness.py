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


@pytest.mark.asyncio
async def test_create_subscription_savepoint_preserves_outer_tx_work(db_session, monkeypatch):
    """CTO 포워드리스크: commit=False로 IAP restore 트랜잭션 안에서 create_subscription이 동시
    race로 IntegrityError를 맞아도, 호출자의 미커밋 UPDATE(영수증 권한 이전)가 폐기되지 않는다.
    production(autoflush=False)을 no_autoflush로 재현. **세이브포인트(begin_nested)가 load-bearing**:
    옛 무조건 db.rollback()으로 되돌리면 전체 트랜잭션이 롤백돼 saved.user_key가 이전 소유자로
    복귀(검증됨). pre-savepoint flush는 방어적 보강."""
    from src.models.db import IAPReceipt

    uk = "fwd-risk-user"
    # 경쟁 세션이 이미 커밋해 둔 active 구독(첫 조회가 이를 못 보게 시임).
    db_session.add(_active(uk, "basic"))
    # 이전 소유자의 커밋된 영수증(restore가 user_key를 재지정할 대상 — persistent mutation).
    db_session.add(
        IAPReceipt(
            user_key="fwd-old-owner", platform="apple", product_id="subscription_premium",
            transaction_id="fwd-tx", store_transaction_id="FWD-STORE",
            status="verified", payload={},
        )
    )
    await db_session.commit()

    receipt = (
        await db_session.execute(
            select(IAPReceipt).where(IAPReceipt.transaction_id == "fwd-tx")
        )
    ).scalar_one()

    real_get = credits_service.get_active_subscription
    calls = {"n": 0}

    async def fake_get(db, user_key):
        calls["n"] += 1
        if calls["n"] == 1 and user_key == uk:
            return None  # stale-miss → 인서트가 경쟁 active와 충돌
        return await real_get(db, user_key)

    monkeypatch.setattr(credits_service, "get_active_subscription", fake_get)

    # production autoflush=False를 재현하고 restore 흐름을 흉내: 영수증 소유 재지정(미커밋
    # UPDATE) 후 구독 생성.
    with db_session.no_autoflush:
        receipt.user_key = uk
        receipt.status = "restored"
        sub = await credits_service.create_subscription(
            db_session, uk, "premium", commit=False, grant_credits=False
        )
    await db_session.commit()

    assert sub is not None
    db_session.expire_all()
    saved = (
        await db_session.execute(
            select(IAPReceipt).where(IAPReceipt.transaction_id == "fwd-tx")
        )
    ).scalar_one()
    assert saved.user_key == uk  # 미커밋 UPDATE(권한 이전)가 세이브포인트 롤백에 폐기되지 않음
    assert await _active_count(db_session, uk) == 1
