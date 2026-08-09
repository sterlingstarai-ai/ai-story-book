"""
Celery tasks for async book generation
"""

import asyncio
from typing import Optional

from celery import shared_task

from src.core.errors import ErrorCode, client_safe_message
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



def _error_code_of(exc: Exception) -> str:
    """도메인 에러 코드를 보존한다(재시도 판단 근거). 그 외는 UNKNOWN."""
    from src.core.errors import StoryBookError

    if isinstance(exc, StoryBookError):
        return exc.code.value
    return ErrorCode.UNKNOWN.value


def run_async(coro):
    """Run async function in sync context for Celery.

    C1: 이 함수는 호출마다 이벤트 루프를 만들고 **닫는다**. 커넥션을 캐싱하는 풀과 만나면
    닫힌 루프에 묶인 커넥션이 다음 루프에서 재사용되어 'attached to a different loop'로
    폭발한다. 그 재사용을 실제로 막는 것은 워커 엔진의 NullPool
    (`core.database.configure_for_worker()`)이며 — 태스크 **간** 교차는 여기서만 막힌다.

    그럼에도 **태스크당 정확히 한 번만 호출하라**: 한 태스크 안에서 두 번 부르면 본작업이
    실패했을 때 실패 마킹 경로까지 같은 이유로 죽어 잡이 `queued`에 영구 잔류한다
    (사용자는 SLA 10분이 지나야 실패를 본다). 상태조회·본작업·실패마킹을 한 코루틴에 넣는다.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _mark_job_failed_async(
    job_id: str, message: str, error_code: Optional[str] = None
) -> None:
    """Best-effort async DB update for failed jobs from Celery context.

    H10 fence: orchestrator.mark_job_failed·job_monitor와 동일하게 queued/running일 때만
    failed로 전이한다. 무조건 덮어쓰면 done 커밋 직후 SoftTimeLimitExceeded 등이 도달했을 때
    배달된 책이 failed로 뒤집히고 환불까지 나가 '책 + 환불' 이중지급이 된다.
    """
    from sqlalchemy import select, update

    from src.core.database import AsyncSessionLocal
    from src.core.utils import utcnow
    from src.models.db import Job

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(["queued", "running"]))
            .values(
                status="failed",
                # A1-R: 원문(pydantic 덤프·모델 응답 조각)을 저장하지 않는다 — 로그로만.
                # 코드도 함께 저장해야 클라이언트가 재시도 가능 여부를 판단할 수 있다.
                error_code=error_code or ErrorCode.UNKNOWN.value,
                error_message=client_safe_message(error_code, message)[:300],
                updated_at=utcnow(),
            )
        )
        transitioned = result.rowcount == 1
        await session.commit()

        if not transitioned:
            logger.warning(
                "celery mark_job_failed skipped (job already terminal)", job_id=job_id
            )
            return

        job = (
            await session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            return
        user_key = job.user_key  # 커밋 후 만료 대비 미리 캡처

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
    # C1: 상태조회 → 본작업 → 실패마킹을 **하나의 코루틴 = 하나의 이벤트 루프**로 실행한다.
    return run_async(_run_book_task_async(job_id, spec_dict, user_key))


async def _run_book_task_async(job_id: str, spec_dict: dict, user_key: str) -> dict:
    """generate_book_task 본체 — 단일 이벤트 루프 안에서 완결(C1)."""
    from src.models.dto import BookSpec
    from src.services.orchestrator import start_book_generation

    # Idempotency guard for Celery redelivery (acks_late + reject_on_worker_lost).
    # A redelivered message must never re-run a job that already reached a
    # terminal state, else re-inserts collide on the unique job_id constraints
    # and a recoverable redelivery becomes a permanent UNKNOWN failure.
    current_status = await _get_job_status_async(job_id)
    if is_redelivery_noop(current_status):
        logger.info(
            "Skipping redelivery of terminal job",
            job_id=job_id,
            status=current_status,
        )
        return {"status": "skipped", "reason": "already_terminal", "job_id": job_id}

    try:
        spec = BookSpec(**spec_dict)
        result = await start_book_generation(job_id, spec, user_key)

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
        # Update job status to failed — 같은 루프 안이므로 이 경로가 죽지 않는다.
        try:
            await _mark_job_failed_async(job_id, str(e), error_code=_error_code_of(e))
        except Exception as db_error:
            logger.error("Failed to update job status", error=str(db_error))

        raise


async def _run_series_generation_async(
    job_id: str,
    request_dict: dict,
    user_key: str,
    character_id: Optional[str],
    prev_book_id: Optional[str],
):
    """직렬화 가능한 id 인자로 character/prev_book을 DB 재조회 후 시리즈 생성 실행(M11).

    start_series_generation은 ORM 객체 character·prev_book을 받아 Celery 직렬화가 불가하므로,
    태스크는 id만 받아 워커 프로세스에서 재조회한다.
    """
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Character
    from src.models.dto import SeriesNextRequest
    from src.services.orchestrator import start_series_generation

    async with AsyncSessionLocal() as session:
        character = None
        if character_id:
            character = (
                await session.execute(
                    select(Character).where(Character.id == character_id)
                )
            ).scalar_one_or_none()
        prev_book = None
        if prev_book_id:
            prev_book = (
                await session.execute(select(Book).where(Book.id == prev_book_id))
            ).scalar_one_or_none()

    request = SeriesNextRequest(**request_dict)
    return await start_series_generation(
        job_id, request, user_key, character, prev_book
    )


@shared_task(
    bind=True,
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=720,
    soft_time_limit=600,
)
def generate_series_task(
    self,
    job_id: str,
    request_dict: dict,
    user_key: str,
    character_id: Optional[str] = None,
    prev_book_id: Optional[str] = None,
):
    """Celery task for series ('다음 권') generation (M11).

    이전엔 create_series_next가 무조건 API 프로세스 BackgroundTasks로 10분 파이프라인을
    실행해 재시작 시 유실·API 지연이 있었다. 직렬화 가능한 id 인자로 워커에서 실행한다.
    """
    logger.info("Starting series generation task", job_id=job_id)
    # C1: 단일 이벤트 루프 — generate_book_task 미러.
    return run_async(
        _run_series_task_async(
            job_id, request_dict, user_key, character_id, prev_book_id
        )
    )


async def _run_series_task_async(
    job_id: str,
    request_dict: dict,
    user_key: str,
    character_id: Optional[str],
    prev_book_id: Optional[str],
) -> dict:
    """generate_series_task 본체 — 단일 이벤트 루프 안에서 완결(C1)."""
    # M23 미러: 재전달 멱등 가드 — terminal 잡은 재실행하지 않는다(재큐 실패 루프 차단).
    current_status = await _get_job_status_async(job_id)
    if is_redelivery_noop(current_status):
        logger.info(
            "Skipping redelivery of terminal series job",
            job_id=job_id,
            status=current_status,
        )
        return {"status": "skipped", "reason": "already_terminal", "job_id": job_id}

    try:
        result = await _run_series_generation_async(
            job_id, request_dict, user_key, character_id, prev_book_id
        )
        logger.info("Series generation completed", job_id=job_id)
        return {"status": "success", "book_id": result.book_id if result else None}

    except IntegrityError as e:
        logger.warning(
            "Absorbing idempotent series redelivery collision",
            job_id=job_id,
            error=str(e),
        )
        return {"status": "skipped", "reason": "duplicate_redelivery", "job_id": job_id}

    except Exception as e:
        logger.error("Series generation failed", job_id=job_id, error=str(e))
        try:
            await _mark_job_failed_async(job_id, str(e), error_code=_error_code_of(e))
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
