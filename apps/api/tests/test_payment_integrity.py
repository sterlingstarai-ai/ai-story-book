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


# ── M16: credit_transactions 멱등성 DB 강제(refund/purchase 부분 유니크) ──
@pytest.mark.asyncio
async def test_refund_partial_unique_blocks_duplicate(db_session):
    """같은 reference_id로 transaction_type='refund' 2행 직접 insert → 2번째 IntegrityError."""
    db_session.add(
        CreditTransaction(
            user_key="m16r", amount=1, balance_after=1,
            transaction_type="refund", reference_id="job-r",
        )
    )
    await db_session.commit()
    db_session.add(
        CreditTransaction(
            user_key="m16r", amount=1, balance_after=2,
            transaction_type="refund", reference_id="job-r",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_purchase_partial_unique_blocks_duplicate(db_session):
    """같은 (user_key, reference_id) transaction_type='purchase' 2행 → 2번째 IntegrityError."""
    db_session.add(
        CreditTransaction(
            user_key="m16p", amount=10, balance_after=10,
            transaction_type="purchase", reference_id="pay-1",
        )
    )
    await db_session.commit()
    db_session.add(
        CreditTransaction(
            user_key="m16p", amount=10, balance_after=20,
            transaction_type="purchase", reference_id="pay-1",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 다른 사용자·다른 reference_id는 허용(부분·복합 스코프 확인).
    db_session.add(
        CreditTransaction(
            user_key="m16p2", amount=10, balance_after=10,
            transaction_type="purchase", reference_id="pay-1",
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_refund_for_job_absorbs_db_duplicate(db_session, monkeypatch):
    """앱 레벨 already-체크를 통과해도(동시 race 시뮬) DB 부분 유니크가 이중 환불을 차단하고
    refund_for_job이 IntegrityError를 흡수해 False 반환·잔액 불변(멱등)."""
    uk = "m16absorb"
    await _seed_charged(db_session, uk, "job-a")
    assert await credits_service.refund_for_job(db_session, uk, "job-a") is True
    assert await _balance(db_session, uk) == 3

    # 두 번째 호출에서 already-체크가 미스하도록 강제(경쟁 세션이 방금 커밋한 상황 재현) →
    # add_credits가 uq_refund 위반 → 세이브포인트 흡수 → False, 잔액 불변.
    monkeypatch.setattr(credits_service, "_job_already_refunded", _always_false)
    assert await credits_service.refund_for_job(db_session, uk, "job-a") is False
    db_session.expire_all()
    assert await _balance(db_session, uk) == 3


async def _always_false(*args, **kwargs):
    return False


@pytest.mark.asyncio
async def test_admin_add_duplicate_transaction_id_idempotent(client, headers, monkeypatch):
    """X-Admin-Key로 같은 transaction_id 재전송 → 잔액 1회만 반영(멱등 200)."""
    from src.core.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "adminkey")
    admin_headers = {**headers, "X-Admin-Key": "adminkey"}
    body = {"amount": 10, "transaction_id": "pay_dup"}

    r1 = await client.post("/v1/credits/add", json=body, headers=admin_headers)
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/v1/credits/add", json=body, headers=admin_headers)
    assert r2.status_code == 200, r2.text  # 멱등(2번째도 성공 응답)

    bal = await client.get("/v1/credits/balance", headers=headers)
    assert bal.json()["credits"] == 13  # 신규 3 + 10 (20 아님)


# ── L8: get_or_create_credits 동시 최초 요청 PK 충돌 흡수 ──
@pytest.mark.asyncio
async def test_get_or_create_credits_absorbs_concurrent_insert(db_session, monkeypatch):
    """신규 사용자 동시 첫 요청 PK 충돌을 흡수·재조회(500·보너스 이중지급 없음)."""
    from src.core.database import AsyncSessionLocal

    uk = "l8-race"
    real_record = credits_service._record_transaction
    fired = {"done": False}

    async def racing_record(*args, **kwargs):
        if not fired["done"]:
            fired["done"] = True
            # 경쟁 세션이 같은 PK를 먼저 커밋(별도 세션, 같은 test.db).
            async with AsyncSessionLocal() as other:
                other.add(
                    UserCredits(user_key=uk, credits=3, total_purchased=0, total_used=0)
                )
                other.add(
                    CreditTransaction(
                        user_key=uk, amount=3, balance_after=3,
                        transaction_type="bonus", description="신규 가입 보너스 크레딧",
                    )
                )
                await other.commit()
        return await real_record(*args, **kwargs)

    monkeypatch.setattr(credits_service, "_record_transaction", racing_record)

    uc = await credits_service.get_or_create_credits(db_session, uk, commit=False)
    await db_session.commit()
    assert uc is not None

    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(UserCredits).where(UserCredits.user_key == uk)
        )
    ).scalars().all()
    assert len(rows) == 1  # 이중 행 없음
    bonuses = (
        await db_session.execute(
            select(CreditTransaction).where(
                CreditTransaction.user_key == uk,
                CreditTransaction.transaction_type == "bonus",
            )
        )
    ).scalars().all()
    assert len(bonuses) == 1  # 보너스 이중 지급 없음


# ── H10: 잡 상태 write-back fence + 완료 후 환불 clawback(MA2) ──
async def _seed_refunded(db, user_key: str, job_id: str, start: int = 3) -> None:
    """usage(-1) + refund(+1) 시딩(SLA 실패+환불 상태 모사). 잔액 = start(순비용 0)."""
    db.add(UserCredits(user_key=user_key, credits=start, total_purchased=0, total_used=1))
    db.add(CreditTransaction(user_key=user_key, amount=-1, balance_after=start - 1,
        transaction_type="usage", description="책 생성", reference_id=job_id))
    db.add(CreditTransaction(user_key=user_key, amount=1, balance_after=start,
        transaction_type="refund", description="생성 실패 환불", reference_id=job_id))
    await db.commit()


@pytest.mark.asyncio
async def test_done_writeback_fenced_against_failed(db_session):
    """SLA로 failed+환불된 잡을 워커가 done으로 뒤집지 못한다(fence) + 책 배달분 clawback(MA2)."""
    from src.services.orchestrator import mark_job_done

    uk = "h10-fence"
    await _seed_refunded(db_session, uk, "job-f")  # 잔액 3(usage+refund 상쇄)
    db_session.add(Job(id="job-f", status="failed", user_key=uk))
    await db_session.commit()

    await mark_job_done("job-f")

    db_session.expire_all()
    job = await db_session.get(Job, "job-f")
    assert job.status == "failed"  # done으로 안 뒤집힘
    # 책이 배달됐으므로 환불을 clawback → 순비용 1(잔액 2).
    assert await _balance(db_session, uk) == 2
    clawbacks = (await db_session.execute(select(CreditTransaction).where(
        CreditTransaction.reference_id == "job-f",
        CreditTransaction.transaction_type == "clawback"))).scalars().all()
    assert len(clawbacks) == 1


@pytest.mark.asyncio
async def test_done_after_refund_claws_back(db_session):
    """running 중 잘못 환불된 잡이 완주(done)하면 환불을 clawback해 이중지급을 막는다."""
    from src.services.orchestrator import mark_job_done

    uk = "h10-claw"
    await _seed_refunded(db_session, uk, "job-c")
    db_session.add(Job(id="job-c", status="running", user_key=uk))
    await db_session.commit()

    await mark_job_done("job-c")

    db_session.expire_all()
    job = await db_session.get(Job, "job-c")
    assert job.status == "done"
    assert await _balance(db_session, uk) == 2  # usage만 순반영(clawback으로 환불 회수)


@pytest.mark.asyncio
async def test_update_job_status_skips_terminal(db_session):
    """done 잡에 update_job_status 호출 → running으로 회귀하지 않는다(fence)."""
    from src.services.orchestrator import update_job_status

    db_session.add(Job(id="job-t", status="done", user_key="u"))
    await db_session.commit()

    await update_job_status("job-t", "중간단계", 55)

    db_session.expire_all()
    job = await db_session.get(Job, "job-t")
    assert job.status == "done"


@pytest.mark.asyncio
async def test_mark_job_failed_skips_done(db_session):
    """done 잡에 mark_job_failed 호출 → failed로 되돌리지 않고 환불도 안 한다(fence)."""
    from src.core.errors import ErrorCode
    from src.services.orchestrator import mark_job_failed

    uk = "h10-donefail"
    db_session.add(UserCredits(user_key=uk, credits=3, total_purchased=0, total_used=0))
    db_session.add(Job(id="job-d", status="done", user_key=uk))
    await db_session.commit()

    await mark_job_failed("job-d", ErrorCode.LLM_TIMEOUT, "late failure")

    db_session.expire_all()
    job = await db_session.get(Job, "job-d")
    assert job.status == "done"
    assert await _balance(db_session, uk) == 3  # 환불 안 됨


@pytest.mark.asyncio
async def test_get_or_create_streak_absorbs_concurrent_insert(db_session, monkeypatch):
    """L8: get_or_create_streak 동시 최초 요청 PK 충돌 흡수·재조회(500·이중 행 없음)."""
    from src.models.db import DailyStreak
    from src.services.streak import streak_service

    uk = "l8-streak-race"
    # 경쟁 세션이 스트릭 행을 먼저 커밋하도록 db.commit을 시임(첫 커밋 직전 트리거).
    real_commit = db_session.commit
    fired = {"done": False}

    async def racing_commit(*args, **kwargs):
        if not fired["done"]:
            fired["done"] = True
            from src.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as other:
                other.add(DailyStreak(user_key=uk, current_streak=0, longest_streak=0, total_days=0))
                await other.commit()
        return await real_commit(*args, **kwargs)

    monkeypatch.setattr(db_session, "commit", racing_commit)

    streak = await streak_service.get_or_create_streak(db_session, uk)
    assert streak is not None

    monkeypatch.undo()
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(DailyStreak).where(DailyStreak.user_key == uk)
        )
    ).scalars().all()
    assert len(rows) == 1
