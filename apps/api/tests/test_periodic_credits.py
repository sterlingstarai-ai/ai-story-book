"""월간 구독 크레딧 리필(periodic_credits) 테스트."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from src.models.db import Subscription
from src.services.credits import SUBSCRIPTION_PLANS, credits_service
from src.services.periodic_credits import _db_utcnow, periodic_credits


async def _make_elapsed_subscription(db, user_key, plan="basic", status="active"):
    """구독 생성 후 결제 주기를 과거로 만들어 '경과' 상태로."""
    sub = await credits_service.create_subscription(db, user_key, plan)
    now = _db_utcnow()
    await db.execute(
        update(Subscription)
        .where(Subscription.id == sub.id)
        .values(
            status=status,
            current_period_start=now - timedelta(days=35),
            current_period_end=now - timedelta(days=5),
        )
    )
    await db.commit()
    return sub


@pytest.mark.asyncio
async def test_refill_grants_monthly_credits_when_period_elapsed(db_session):
    uk = "user-refill-1"
    await _make_elapsed_subscription(db_session, uk, "basic")
    before = await credits_service.get_credits(db_session, uk)

    n = await periodic_credits.grant_due_refills(db_session)

    assert n == 1
    after = await credits_service.get_credits(db_session, uk)
    assert after == before + SUBSCRIPTION_PLANS["basic"]["credits_per_month"]

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.user_key == uk)
        )
    ).scalars().first()
    assert sub.current_period_end > _db_utcnow()


@pytest.mark.asyncio
async def test_refill_is_idempotent(db_session):
    uk = "user-refill-2"
    await _make_elapsed_subscription(db_session, uk, "premium")
    await periodic_credits.grant_due_refills(db_session)
    mid = await credits_service.get_credits(db_session, uk)

    n2 = await periodic_credits.grant_due_refills(db_session)
    assert n2 == 0
    assert await credits_service.get_credits(db_session, uk) == mid


@pytest.mark.asyncio
async def test_refill_skips_cancelled_subscription(db_session):
    uk = "user-refill-3"
    await _make_elapsed_subscription(db_session, uk, "basic", status="cancelled")
    before = await credits_service.get_credits(db_session, uk)

    n = await periodic_credits.grant_due_refills(db_session)
    assert n == 0
    assert await credits_service.get_credits(db_session, uk) == before


@pytest.mark.asyncio
async def test_refill_skips_active_not_yet_elapsed(db_session):
    uk = "user-refill-4"
    await credits_service.create_subscription(db_session, uk, "basic")
    before = await credits_service.get_credits(db_session, uk)

    n = await periodic_credits.grant_due_refills(db_session)
    assert n == 0
    assert await credits_service.get_credits(db_session, uk) == before
