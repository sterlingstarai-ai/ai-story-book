"""결제 무결성 — 멱등성 중복차단 + 실패 잡 멱등 환불.

- (user_key, idempotency_key) 부분 유니크 인덱스가 동시 중복 잡을 DB 레벨에서 차단(이중차감 방지).
- refund_for_job: 과금된 잡만·1회만 환불(over/double-refund 방지).
- job_monitor가 스턱 잡을 최종 실패 처리할 때 silent 크레딧 손실 없이 환불.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.errors import ErrorCode
from src.models.db import CreditTransaction, Job, UserCredits
from src.services.credits import credits_service


async def _balance(db, user_key: str) -> int:
    res = await db.execute(
        select(UserCredits.credits).where(UserCredits.user_key == user_key)
    )
    return res.scalar_one()


async def _seed_charged(db, user_key: str, job_id: str, start: int = 3) -> None:
    """UserCredits + 'usage' 트랜잭션을 직접 생성(use_credit 모킹 우회)."""
    db.add(
        UserCredits(
            user_key=user_key, credits=start - 1, total_purchased=0, total_used=1
        )
    )
    db.add(
        CreditTransaction(
            user_key=user_key,
            amount=-1,
            balance_after=start - 1,
            transaction_type="usage",
            description="책 생성",
            reference_id=job_id,
        )
    )
    await db.commit()


# ── 멱등성 부분 유니크 인덱스 ──
@pytest.mark.asyncio
async def test_idempotency_partial_unique_blocks_duplicate(db_session):
    db_session.add(Job(id="job-a", status="done", user_key="u1", idempotency_key="k1"))
    await db_session.commit()

    db_session.add(Job(id="job-b", status="done", user_key="u1", idempotency_key="k1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_idempotency_scoped_per_user_and_allows_null(db_session):
    # 다른 유저는 같은 키 허용 + idempotency_key NULL은 제약 대상 아님(부분 인덱스)
    db_session.add(Job(id="job-u1", status="done", user_key="ua", idempotency_key="shared"))
    db_session.add(Job(id="job-u2", status="done", user_key="ub", idempotency_key="shared"))
    db_session.add(Job(id="job-n1", status="done", user_key="uc", idempotency_key=None))
    db_session.add(Job(id="job-n2", status="done", user_key="uc", idempotency_key=None))
    await db_session.commit()  # 충돌 없이 통과해야 함


# ── 멱등 환불 ──
@pytest.mark.asyncio
async def test_refund_for_job_idempotent_and_charged_only(db_session):
    uk = "pay1"
    await _seed_charged(db_session, uk, "job-x")
    assert await _balance(db_session, uk) == 2

    # 과금된 잡 → 환불 True, 잔액 복구
    assert await credits_service.refund_for_job(db_session, uk, "job-x") is True
    assert await _balance(db_session, uk) == 3

    # 재호출 → False(이중환불 방지), 잔액 불변
    assert await credits_service.refund_for_job(db_session, uk, "job-x") is False
    assert await _balance(db_session, uk) == 3

    # 과금된 적 없는 잡 → False(over-refund 방지)
    assert await credits_service.refund_for_job(db_session, uk, "job-never") is False
    assert await _balance(db_session, uk) == 3


# ── job_monitor 실패 처리 시 환불 ──
@pytest.mark.asyncio
async def test_job_monitor_refunds_failed_stuck_job(db_session):
    from src.services.job_monitor import job_monitor

    uk = "pay2"
    await _seed_charged(db_session, uk, "job-stuck")
    job = Job(id="job-stuck", status="running", user_key=uk)
    db_session.add(job)
    await db_session.commit()

    await job_monitor._mark_job_failed(
        db_session, job, "STUCK_RUNNING", "Max retries exceeded"
    )
    await db_session.commit()

    assert job.status == "failed"
    assert await _balance(db_session, uk) == 3  # 크레딧 먹튀 방지(환불됨)


# ── C2: 파이프라인 인-플라이트 최종 실패 시 환불(orchestrator / celery 경로) ──
@pytest.mark.asyncio
async def test_orchestrator_mark_job_failed_refunds_charged_job(db_session):
    """mark_job_failed(orchestrator)가 선차감 크레딧을 환불한다(수정 전엔 잔액 2)."""
    from src.services.orchestrator import mark_job_failed

    uk = "c2-orch"
    await _seed_charged(db_session, uk, "job-fail")
    db_session.add(Job(id="job-fail", status="running", user_key=uk))
    await db_session.commit()
    assert await _balance(db_session, uk) == 2

    await mark_job_failed("job-fail", ErrorCode.LLM_JSON_INVALID, "boom")

    db_session.expire_all()
    assert await _balance(db_session, uk) == 3  # 환불됨
    job = await db_session.get(Job, "job-fail")
    assert job.status == "failed"
    refunds = (
        await db_session.execute(
            select(CreditTransaction).where(
                CreditTransaction.reference_id == "job-fail",
                CreditTransaction.transaction_type == "refund",
            )
        )
    ).scalars().all()
    assert len(refunds) == 1


@pytest.mark.asyncio
async def test_mark_job_failed_refund_idempotent(db_session):
    """두 번 호출해도 refund 1건·잔액 3 유지(멱등)."""
    from src.services.orchestrator import mark_job_failed

    uk = "c2-idem"
    await _seed_charged(db_session, uk, "job-idem")
    db_session.add(Job(id="job-idem", status="running", user_key=uk))
    await db_session.commit()

    await mark_job_failed("job-idem", ErrorCode.IMAGE_FAILED, "boom1")
    await mark_job_failed("job-idem", ErrorCode.IMAGE_FAILED, "boom2")

    db_session.expire_all()
    assert await _balance(db_session, uk) == 3
    refunds = (
        await db_session.execute(
            select(CreditTransaction).where(
                CreditTransaction.reference_id == "job-idem",
                CreditTransaction.transaction_type == "refund",
            )
        )
    ).scalars().all()
    assert len(refunds) == 1


@pytest.mark.asyncio
async def test_tasks_mark_job_failed_async_refunds(db_session):
    """Celery 경로 _mark_job_failed_async도 환불한다."""
    from src.services.tasks import _mark_job_failed_async

    uk = "c2-task"
    await _seed_charged(db_session, uk, "job-task")
    db_session.add(Job(id="job-task", status="running", user_key=uk))
    await db_session.commit()

    await _mark_job_failed_async("job-task", "boom")

    db_session.expire_all()
    assert await _balance(db_session, uk) == 3
    job = await db_session.get(Job, "job-task")
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_mark_job_failed_persists_status_even_if_refund_fails(db_session, monkeypatch):
    """MA3: 환불이 강제 실패해도 status=='failed'는 영속(먼저 커밋됨)."""
    from src.services.orchestrator import mark_job_failed

    uk = "c2-refundfail"
    await _seed_charged(db_session, uk, "job-rf")
    db_session.add(Job(id="job-rf", status="running", user_key=uk))
    await db_session.commit()

    async def boom_refund(*args, **kwargs):
        raise RuntimeError("refund backend down")

    # mark_job_failed의 지연 import가 참조하는 동일 싱글톤을 직접 패치.
    monkeypatch.setattr(credits_service, "refund_for_job", boom_refund)

    # 환불 실패가 예외로 전파되지 않아야 함(잡 실패 마킹을 막지 않음).
    await mark_job_failed("job-rf", ErrorCode.STORAGE_UPLOAD_FAILED, "x")

    db_session.expire_all()
    job = await db_session.get(Job, "job-rf")
    assert job.status == "failed"  # 상태는 영속
    assert await _balance(db_session, uk) == 2  # 환불은 안 됨(강제 실패)
