from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.models.db import CreditTransaction, Job, UserCredits
from src.services.job_monitor import _db_timestamp, job_monitor


def test_db_timestamp_keeps_naive_values_unchanged():
    naive = datetime(2026, 3, 15, 9, 30, 0)

    assert _db_timestamp(naive) == naive


def test_db_timestamp_normalizes_to_naive_utc():
    seoul_time = datetime(2026, 3, 15, 18, 30, 0, tzinfo=timezone(timedelta(hours=9)))

    assert _db_timestamp(seoul_time) == datetime(2026, 3, 15, 9, 30, 0)


async def _seed_charged(db, uk, job_id, start=3):
    db.add(UserCredits(user_key=uk, credits=start - 1, total_purchased=0, total_used=1))
    db.add(CreditTransaction(user_key=uk, amount=-1, balance_after=start - 1,
        transaction_type="usage", description="책 생성", reference_id=job_id))
    await db.commit()


async def _balance(db, uk):
    db.expire_all()
    return (await db.execute(
        select(UserCredits.credits).where(UserCredits.user_key == uk))).scalar_one()


@pytest.mark.asyncio
async def test_stuck_job_fails_immediately_with_refund(db_session):
    """M18: 스턱 잡은 좀비 재큐(queued 복귀) 대신 즉시 실패+환불로 종결한다."""
    uk = "m18-stuck"
    await _seed_charged(db_session, uk, "job-stuck")
    job = Job(id="job-stuck", status="running", user_key=uk, retry_count=0)
    db_session.add(job)
    await db_session.commit()

    await job_monitor._handle_stuck_job(db_session, job, "STUCK_RUNNING")
    await db_session.commit()

    assert job.status == "failed"  # queued 재큐 아님
    assert (job.retry_count or 0) == 0  # 재시도 카운트 증가 없음
    assert await _balance(db_session, uk) == 3  # 환불됨


@pytest.mark.asyncio
async def test_no_zombie_requeue(db_session):
    """M18: 두 번 호출해도 queued로 복귀하지 않고 환불 1회만."""
    uk = "m18-zombie"
    await _seed_charged(db_session, uk, "job-z")
    job = Job(id="job-z", status="running", user_key=uk, retry_count=0)
    db_session.add(job)
    await db_session.commit()

    await job_monitor._handle_stuck_job(db_session, job, "STUCK_RUNNING")
    await job_monitor._handle_stuck_job(db_session, job, "STUCK_RUNNING")
    await db_session.commit()

    assert job.status == "failed"
    refunds = (await db_session.execute(select(CreditTransaction).where(
        CreditTransaction.reference_id == "job-z",
        CreditTransaction.transaction_type == "refund"))).scalars().all()
    assert len(refunds) == 1
    assert await _balance(db_session, uk) == 3
