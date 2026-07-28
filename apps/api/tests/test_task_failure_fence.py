import pytest

from src.models.db import Job


@pytest.mark.asyncio
async def test_celery_failure_path_does_not_flip_done_job(db_session, monkeypatch):
    """#19(H10): Celery 예외 경로가 done 잡을 failed로 덮어쓰고 환불하면 안 된다.

    orchestrator.mark_job_failed·job_monitor에는 조건부 UPDATE fence가 있는데 형제 경로인
    tasks._mark_job_failed_async만 read-then-write로 무조건 덮어썼다. done 커밋 직후
    SoftTimeLimitExceeded 등이 오면 '배달된 책 + 환불'(이중지급)이 된다.
    """
    from src.services import tasks as tasks_module

    job_id = "job_done_fence"
    db_session.add(Job(id=job_id, status="done", progress=100, user_key="fence-user"))
    await db_session.commit()

    refunded = {"called": False}

    class _FakeCredits:
        async def refund_for_job(self, *a, **kw):
            refunded["called"] = True

    monkeypatch.setattr("src.services.credits.credits_service", _FakeCredits())

    # 테스트 세션과 같은 DB를 쓰도록 AsyncSessionLocal은 실제 구현 사용.
    await tasks_module._mark_job_failed_async(job_id, "soft time limit exceeded")

    db_session.expire_all()
    job = await db_session.get(Job, job_id)
    assert job.status == "done", "done 잡이 failed로 뒤집히면 안 됨"
    assert refunded["called"] is False, "배달된 책에 환불하면 이중지급"
