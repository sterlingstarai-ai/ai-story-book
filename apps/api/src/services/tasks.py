"""
Celery tasks for async book generation
"""

import asyncio
from typing import Optional

from celery import shared_task
from sqlalchemy.exc import IntegrityError
import structlog


logger = structlog.get_logger()


# Job states from which a redelivered Celery message must NOT re-execute.
# acks_late + reject_on_worker_lost cause a message to be redelivered when a
# worker dies mid-task; re-running a job that already reached a terminal state
# would re-insert rows keyed by the unique job_id (story_drafts/image_prompts/
# books) and turn a recoverable redelivery into a permanent failure.
_TERMINAL_JOB_STATUSES = frozenset({"done", "failed"})


def is_redelivery_noop(status: Optional[str]) -> bool:
    """Pure guard: True when a redelivered task should skip re-execution.

    Terminal jobs (done/failed) are no-ops; queued/running/unknown proceed.
    """
    return status in _TERMINAL_JOB_STATUSES


def run_async(coro):
    """Run async function in sync context for Celery."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _mark_job_failed_async(job_id: str, message: str) -> None:
    """Best-effort async DB update for failed jobs from Celery context."""
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal
    from src.models.db import Job

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        user_key = job.user_key  # 커밋 후 만료 대비 미리 캡처
        job.status = "failed"
        job.error_message = message[:300]
        # 실패 상태를 먼저 영속화(MA3) 후 별도 트랜잭션으로 선차감 크레딧 환불(멱등).
        await session.commit()

        try:
            from src.services.credits import credits_service

            await credits_service.refund_for_job(
                session,
                user_key,
                job_id,
                description="생성 실패 환불(자동)",
                commit=True,
            )
        except Exception as refund_exc:  # noqa: BLE001
            logger.warning(
                "failed-job refund error", job_id=job_id, error=str(refund_exc)
            )


async def _get_job_status_async(job_id: str) -> Optional[str]:
    """Read the job's current status (None if the job row is missing)."""
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal
    from src.models.db import Job

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Job.status).where(Job.id == job_id))
        return result.scalar_one_or_none()


async def _regenerate_page_async(
    job_id: str,
    page_number: int,
    target: str,
) -> dict:
    """Resolve book by job_id and run page regeneration."""
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal
    from src.models.db import Book
    from src.services.orchestrator import regenerate_page

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Book).where(Book.job_id == job_id))
        book = result.scalar_one_or_none()

    if not book:
        raise ValueError(f"Book not found for job_id={job_id}")

    return await regenerate_page(
        job_id=job_id,
        book_id=book.id,
        page_number=page_number,
        mode=target,
        feedback=None,
    )


@shared_task(
    bind=True,
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=720,
    soft_time_limit=600,
)
def generate_book_task(self, job_id: str, spec_dict: dict, user_key: str):
    """
    Celery task for book generation.

    Args:
        job_id: Job ID
        spec_dict: BookSpec as dictionary
        user_key: User key
    """
    logger.info("Starting book generation task", job_id=job_id)

    # Idempotency guard for Celery redelivery (acks_late + reject_on_worker_lost).
    # A redelivered message must never re-run a job that already reached a
    # terminal state, else re-inserts collide on the unique job_id constraints
    # and a recoverable redelivery becomes a permanent UNKNOWN failure.
    current_status = run_async(_get_job_status_async(job_id))
    if is_redelivery_noop(current_status):
        logger.info(
            "Skipping redelivery of terminal job",
            job_id=job_id,
            status=current_status,
        )
        return {"status": "skipped", "reason": "already_terminal", "job_id": job_id}

    try:
        from src.services.orchestrator import start_book_generation
        from src.models.dto import BookSpec

        spec = BookSpec(**spec_dict)
        result = run_async(start_book_generation(job_id, spec, user_key))

        logger.info("Book generation completed", job_id=job_id)
        return {"status": "success", "book_id": result.book_id if result else None}

    except IntegrityError as e:
        # A duplicate-insert collision on the unique job_id means a prior (or
        # concurrent) execution already claimed/created this job's rows. This is
        # a recoverable redelivery, not a real failure: absorb it as a no-op
        # rather than marking the job failed or re-raising (which would trigger
        # yet another Celery redelivery → permanent failure loop). The offending
        # session is owned and rolled back by the orchestrator's own context
        # manager, so there is nothing to roll back here.
        logger.warning(
            "Absorbing idempotent redelivery collision",
            job_id=job_id,
            error=str(e),
        )
        return {"status": "skipped", "reason": "duplicate_redelivery", "job_id": job_id}

    except Exception as e:
        logger.error("Book generation failed", job_id=job_id, error=str(e))
        # Update job status to failed
        try:
            run_async(_mark_job_failed_async(job_id, str(e)))
        except Exception as db_error:
            logger.error("Failed to update job status", error=str(db_error))

        raise


@shared_task(
    bind=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=180,
    soft_time_limit=150,
)
def regenerate_page_task(
    self,
    job_id: str,
    page_number: int,
    target: str,
    user_key: str,
):
    """
    Celery task for page regeneration.

    Args:
        job_id: Job ID
        page_number: Page number (1-indexed)
        target: Regeneration target ('text', 'image', 'both')
        user_key: User key
    """
    logger.info(
        "Starting page regeneration task",
        job_id=job_id,
        page_number=page_number,
        target=target,
    )

    try:
        result = run_async(
            _regenerate_page_async(
                job_id=job_id,
                page_number=page_number,
                target=target,
            )
        )
        logger.info(
            "Page regeneration completed", job_id=job_id, page_number=page_number
        )
        return {"status": "success", "result": result}

    except Exception as e:
        logger.error(
            "Page regeneration failed",
            job_id=job_id,
            page_number=page_number,
            error=str(e),
        )
        raise self.retry(exc=e, countdown=5)
