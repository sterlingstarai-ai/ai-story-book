"""Failure and concurrency regressions at the generation/credit boundaries."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as redis
from sqlalchemy import func, select

from src.core.config import settings
from src.core.errors import ErrorCode
from src.core.exceptions import APIError
from src.models.db import Book, CreditTransaction, Job, StoragePurgeTask, UserCredits
from src.services.credits import credits_service
from src.services.job_monitor import job_monitor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [redis.ConnectionError("credentials must not leak"), ValueError("bad counter")]
)
async def test_rate_limit_failure_blocks_without_leaking_details(monkeypatch, error):
    from src.core.rate_limit import check_rate_limit, rate_limiter

    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(side_effect=error))
    request = SimpleNamespace(headers={"X-User-Key": "owner"}, state=SimpleNamespace())
    with pytest.raises(APIError) as exc:
        await check_rate_limit(request)
    assert exc.value.status_code == 503
    assert str(error) not in exc.value.message
    assert exc.value.headers == {"Retry-After": "30"}


def test_generation_budget_rolls_at_korean_midnight(monkeypatch):
    from src.core import cost_budget

    monkeypatch.setattr(cost_budget, "utcnow", lambda: datetime(2026, 9, 5, 14, 59, 59))
    assert cost_budget.daily_budget_key().endswith("20260905")
    monkeypatch.setattr(cost_budget, "utcnow", lambda: datetime(2026, 9, 5, 15, 0, 0))
    assert cost_budget.daily_budget_key().endswith("20260906")


@pytest.mark.asyncio
async def test_redis_outage_does_not_create_job_or_charge_credit(
    client, headers, valid_book_spec, db_session, monkeypatch
):
    from src.core.rate_limit import rate_limiter

    monkeypatch.setattr(settings, "daily_generation_budget", 20)
    monkeypatch.setattr(
        rate_limiter, "get_redis", AsyncMock(side_effect=redis.ConnectionError("down"))
    )
    response = await client.post("/v1/books", json=valid_book_spec, headers=headers)
    assert response.status_code == 503
    assert await db_session.scalar(select(func.count(Job.id))) == 0
    assert await db_session.scalar(select(func.count(CreditTransaction.id))) == 0


async def _charged_job(db, job_id, status="failed", user_key="refund-owner"):
    await credits_service.get_or_create_credits(db, user_key)
    db.add(Job(id=job_id, user_key=user_key, status=status))
    await db.commit()
    await credits_service.use_credit(db, user_key, reference_id=job_id)


@pytest.mark.asyncio
async def test_failed_job_refund_recovers_after_transient_failure_once(db_session, monkeypatch):
    from src.services.orchestrator import mark_job_failed

    await _charged_job(db_session, "job_lost_refund", status="running")
    real_refund = credits_service.refund_for_job
    monkeypatch.setattr(
        credits_service,
        "refund_for_job",
        AsyncMock(side_effect=RuntimeError("temporary refund failure")),
    )
    await mark_job_failed("job_lost_refund", ErrorCode.UNKNOWN, "failed")
    db_session.expire_all()
    assert (await db_session.get(Job, "job_lost_refund")).status == "failed"
    assert await db_session.scalar(select(UserCredits.credits)) == 2
    await db_session.rollback()

    monkeypatch.setattr(credits_service, "refund_for_job", real_refund)
    assert await job_monitor.reconcile_failed_job_refunds() == 1
    assert await job_monitor.reconcile_failed_job_refunds() == 0
    assert await db_session.scalar(select(UserCredits.credits)) == 3
    assert (
        await db_session.scalar(
            select(func.count(CreditTransaction.id)).where(
                CreditTransaction.transaction_type == "refund"
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_refund_requires_usage_by_the_same_owner(db_session):
    await _charged_job(db_session, "job_owned")
    assert await credits_service.refund_for_job(db_session, "different-user", "job_owned") is False
    assert await db_session.get(UserCredits, "different-user") is None


@pytest.mark.asyncio
async def test_monitor_records_cleanup_for_interrupted_image_uploads(db_session):
    job = Job(id="job_partial", user_key="owner", status="running", image_keys=["legacy/image.png"])
    db_session.add(job)
    await db_session.commit()
    await job_monitor._mark_job_failed(db_session, job, "STUCK_RUNNING", "interrupted")
    await db_session.commit()
    targets = set((await db_session.scalars(select(StoragePurgeTask.target))).all())
    assert targets == {"jobs/job_partial/", "legacy/image.png"}


@pytest.mark.asyncio
async def test_claim_allows_only_one_start_and_skips_missing_jobs(db_session):
    from src.services.tasks import _claim_job_async

    db_session.add(Job(id="job_claim", user_key="owner", status="queued"))
    await db_session.commit()
    assert await _claim_job_async("job_claim") is True
    assert await _claim_job_async("job_claim") is False
    assert await _claim_job_async("missing") is False


@pytest.mark.asyncio
async def test_running_redelivery_does_not_call_paid_providers(
    db_session, valid_book_spec, monkeypatch
):
    from src.services import orchestrator, tasks

    db_session.add(Job(id="job_live_worker", user_key="owner", status="running"))
    await db_session.commit()
    run = AsyncMock()
    monkeypatch.setattr(orchestrator, "start_book_generation", run)
    result = await tasks._run_book_task_async("job_live_worker", valid_book_spec, "owner")
    assert result["status"] == "skipped"
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_retry_still_resolves_at_daily_limit(
    client, headers, valid_book_spec, db_session, monkeypatch
):
    db_session.add(
        Job(
            id="job_existing",
            user_key=headers["X-User-Key"],
            status="queued",
            idempotency_key="retry-once",
        )
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "daily_job_limit_per_user", 1)
    response = await client.post(
        "/v1/books", json=valid_book_spec, headers={**headers, "X-Idempotency-Key": "retry-once"}
    )
    assert response.status_code == 200
    assert response.json()["job_id"] == "job_existing"


@pytest.mark.asyncio
async def test_limit_recheck_rolls_back_credit_reservation(db_session, monkeypatch):
    from src.routers.books import _create_job_with_credit

    await _charged_job(db_session, "job_existing", status="queued")
    monkeypatch.setattr(settings, "daily_job_limit_per_user", 1)
    with pytest.raises(APIError) as exc:
        await _create_job_with_credit(
            db=db_session,
            user_key="refund-owner",
            job_id="job_rejected",
            current_step="queued",
            credit_description="test",
        )
    assert exc.value.error_code == "DAILY_LIMIT_EXCEEDED"
    assert await db_session.scalar(select(UserCredits.credits)) == 2
    assert await db_session.get(Job, "job_rejected") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "failed"])
async def test_book_and_done_state_commit_together(db_session, valid_book_spec, status):
    from src.core.errors import StoryBookError
    from src.models.dto import BookSpec
    from src.services import orchestrator

    spec = BookSpec(**valid_book_spec)
    story = await orchestrator.generate_story(spec)
    character = await orchestrator.generate_character_sheet(spec, story)
    prompts = await orchestrator.generate_image_prompts(spec, story, character)
    job_id = f"job_package_{status}"
    db_session.add(Job(id=job_id, user_key="owner", status=status))
    await db_session.commit()
    kwargs = dict(
        job_id=job_id,
        user_key="owner",
        spec=spec,
        story=story,
        character=character,
        image_prompts=prompts,
        image_urls={i: "" if i == 1 else f"https://example.com/page-{i}.png" for i in range(len(story.pages) + 1)},
    )
    if status == "failed":
        with pytest.raises(StoryBookError):
            await orchestrator.package_book(**kwargs)
        assert await db_session.scalar(select(func.count(Book.id))) == 0
    else:
        result = await orchestrator.package_book(**kwargs)
        db_session.expire_all()
        assert (await db_session.get(Job, job_id)).status == "done"
        assert (await db_session.get(Book, result.book_id)).job_id == job_id
        assert result.generation_warnings
        assert result.pages[0].image_url.startswith(orchestrator.PLACEHOLDER_IMAGE_URL)
