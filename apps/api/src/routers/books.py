from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import Optional
from datetime import timedelta
import math
import uuid
import structlog

from src.core.database import get_db
from src.core.book_assets import build_generation_warnings, build_page_asset_status
from src.core.config import settings
from src.core.dependencies import get_profile_id, get_user_key
from src.models.dto import (
    BookSpec,
    CreateBookResponse,
    JobStatus,
    JobState,
    RegeneratePageRequest,
    RegeneratePageResponse,
    SeriesNextRequest,
    BookResult,
    PageResult,
)
from src.models.db import ChildProfile, Job, Book, Page
from src.services.orchestrator import start_book_generation, regenerate_page
from src.services.pdf import pdf_service
from src.services.tts import tts_service
from src.services.storage import storage_service
from src.services.credits import credits_service
from src.core.utils import utcnow
from src.core.errors import ErrorCode
from src.core.exceptions import (
    AuthorizationError,
    InternalServerError,
    NotFoundError,
    PaymentRequiredError,
    ValidationError,
)

logger = structlog.get_logger()

router = APIRouter()

_FREE_PLAN_ALLOWED_STYLES = {"watercolor", "cartoon"}
_FREE_PLAN_BLOCKED_FEATURES = {
    "pdf": "PDF 내보내기",
    "audio": "오디오",
}


def _is_free_plan_policy_enabled() -> bool:
    if not getattr(settings, "free_plan_enforcement_enabled", True):
        return False
    if settings.testing and not getattr(settings, "free_plan_enforce_in_testing", False):
        return False
    return True


def _normalize_style(style: object) -> str:
    value = getattr(style, "value", style)
    if value is None:
        return ""
    return str(value).strip().lower()


def _month_window(reference):
    start = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def _resolve_effective_plan(db: AsyncSession, user_key: str) -> str:
    subscription = await credits_service.get_active_subscription(db, user_key)
    if not subscription or not isinstance(subscription.plan, str):
        return "free"
    normalized = subscription.plan.strip().lower()
    return normalized if normalized else "free"


async def _count_monthly_book_creations(db: AsyncSession, user_key: str) -> int:
    month_start, month_end = _month_window(utcnow())
    result = await db.execute(
        select(func.count(Job.id)).where(
            Job.user_key == user_key,
            Job.created_at >= month_start,
            Job.created_at < month_end,
            Job.status.in_(["queued", "running", "done"]),
            or_(Job.id.startswith("job_"), Job.id.startswith("series_")),
        )
    )
    return int(result.scalar() or 0)


async def _enforce_free_plan_create_limits(
    db: AsyncSession,
    user_key: str,
    style: object,
) -> None:
    if not _is_free_plan_policy_enabled():
        return

    effective_plan = await _resolve_effective_plan(db, user_key)
    if effective_plan != "free":
        return

    normalized_style = _normalize_style(style)
    if normalized_style not in _FREE_PLAN_ALLOWED_STYLES:
        raise PaymentRequiredError(
            "무료 플랜은 watercolor/cartoon 스타일만 지원합니다. 베이직 이상으로 업그레이드해주세요."
        )

    monthly_limit = max(1, int(getattr(settings, "free_plan_monthly_book_limit", 2) or 2))
    monthly_created = await _count_monthly_book_creations(db, user_key)
    if monthly_created >= monthly_limit:
        raise PaymentRequiredError(
            f"무료 플랜은 월 {monthly_limit}권까지 생성할 수 있습니다. 베이직 이상으로 업그레이드해주세요."
        )


async def _enforce_free_plan_feature_access(
    db: AsyncSession,
    user_key: str,
    feature: str,
) -> None:
    if not _is_free_plan_policy_enabled():
        return

    effective_plan = await _resolve_effective_plan(db, user_key)
    if effective_plan != "free":
        return

    feature_name = _FREE_PLAN_BLOCKED_FEATURES.get(feature, "해당")
    raise PaymentRequiredError(
        f"무료 플랜에서는 {feature_name} 기능을 사용할 수 없습니다. 베이직 이상으로 업그레이드해주세요."
    )


def _build_page_dict(p) -> dict:
    """Build standardized page response dict from a Page model."""
    asset_status = build_page_asset_status(
        p.image_url,
        audio_urls=[
            getattr(p, "audio_url", None),
            getattr(p, "audio_url_ko", None),
            getattr(p, "audio_url_en", None),
        ],
    )
    return {
        "page_number": p.page_number,
        "text": p.text,
        "image_url": p.image_url or "",
        "image_prompt": p.image_prompt,
        "audio_url": p.audio_url,
        "text_ko": p.text_ko,
        "text_en": p.text_en,
        "audio_url_ko": p.audio_url_ko,
        "audio_url_en": p.audio_url_en,
        "vocab": p.vocab,
        "comprehension_questions": p.comprehension,
        "quiz": p.quiz,
        "asset_status": asset_status,
    }


def _build_book_dict(book, pages, include_job_id: bool = False) -> dict:
    """Build standardized book response dict from Book + Pages models."""
    generation_warnings = build_generation_warnings(
        cover_image_url=book.cover_image_url,
        page_images=[(p.page_number, p.image_url) for p in pages],
    )
    result = {
        "book_id": book.id,
        "title": book.title,
        "language": book.language,
        "target_age": book.target_age,
        "style": book.style,
        "cover_image_url": book.cover_image_url or "",
        "series_id": book.series_id,
        "series_index": book.series_index,
        "title_ko": book.title_ko,
        "title_en": book.title_en,
        "pages": [_build_page_dict(p) for p in pages],
        "learning_assets": book.learning_assets,
        "generation_warnings": generation_warnings,
        "created_at": book.created_at.isoformat(),
    }
    if include_job_id:
        result["job_id"] = book.job_id
        result["theme"] = book.theme
        result["character_id"] = book.character_id
        result["pdf_url"] = book.pdf_url
        result["audio_url"] = book.audio_url
    return result


def _build_book_result(book, pages, include_job_id: bool = False) -> BookResult:
    """Build a strongly typed BookResult to keep response serialization aligned."""
    return BookResult.model_validate(
        _build_book_dict(book, pages, include_job_id=include_job_id)
    )


def get_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract idempotency key from header"""
    return x_idempotency_key


async def _create_job_with_credit(
    *,
    db: AsyncSession,
    user_key: str,
    job_id: str,
    current_step: str,
    credit_description: str,
    refund_description: str,
    idempotency_key: Optional[str] = None,
    profile_id: Optional[str] = None,
):
    """
    Create a queued job with credit deduction and automatic refund on failure.
    """
    has_credits = await credits_service.has_credits(db, user_key, required=1)
    if not has_credits:
        raise PaymentRequiredError("크레딧이 부족합니다. 크레딧을 충전해주세요.")

    credit_used = await credits_service.use_credit(
        db,
        user_key,
        amount=1,
        description=credit_description,
        reference_id=job_id,
    )
    if not credit_used:
        raise PaymentRequiredError("크레딧 차감에 실패했습니다.")

    try:
        job = Job(
            id=job_id,
            status="queued",
            progress=0,
            current_step=current_step,
            user_key=user_key,
            profile_id=profile_id,
            idempotency_key=idempotency_key,
        )
        db.add(job)
        await db.commit()
    except Exception as e:
        logger.error(
            "Job creation failed, refunding credit",
            job_id=job_id,
            user_key=user_key,
            error=str(e),
        )
        await db.rollback()
        await credits_service.add_credits(
            db,
            user_key,
            amount=1,
            transaction_type="refund",
            description=refund_description,
            reference_id=job_id,
        )
        raise InternalServerError(
            message="잡 생성에 실패했습니다. 크레딧이 환불되었습니다."
        ) from e


async def _mark_job_failed_with_refund(
    *,
    db: AsyncSession,
    user_key: str,
    job_id: str,
    fail_message: str,
    refund_description: str,
) -> None:
    """Mark job failed and refund one credit in a single DB transaction."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job:
        job.status = "failed"
        job.error_code = ErrorCode.QUEUE_FAILED.value
        job.error_message = fail_message[:300]

    await credits_service.add_credits(
        db=db,
        user_key=user_key,
        amount=1,
        transaction_type="refund",
        description=refund_description,
        reference_id=job_id,
    )


async def _set_regen_job_status(
    regen_job_id: str,
    *,
    status: str,
    progress: int,
    current_step: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update regeneration job progress/state."""
    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Job).where(Job.id == regen_job_id))
        regen_job = result.scalar_one_or_none()
        if not regen_job:
            return

        regen_job.status = status
        regen_job.progress = progress
        regen_job.current_step = current_step
        regen_job.error_code = error_code
        regen_job.error_message = error_message
        regen_job.updated_at = utcnow()
        await session.commit()


async def _validate_profile_ownership(
    db: AsyncSession,
    user_key: str,
    profile_id: Optional[str],
) -> Optional[str]:
    if not isinstance(profile_id, str):
        return None
    normalized = profile_id.strip()
    if not normalized:
        return None
    profile_result = await db.execute(
        select(ChildProfile).where(
            ChildProfile.id == normalized,
            ChildProfile.user_key == user_key,
        )
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise ValidationError("유효하지 않은 프로필입니다.")
    return normalized


def _assert_book_profile_scope(
    book: Book,
    profile_id: Optional[str],
) -> None:
    if not isinstance(profile_id, str):
        return
    normalized = profile_id.strip()
    if not normalized:
        return
    if getattr(book, "profile_id", None) != normalized:
        raise AuthorizationError("선택한 프로필의 책이 아닙니다.")


def _assert_job_profile_scope(
    job: Job,
    profile_id: Optional[str],
) -> None:
    if not isinstance(profile_id, str):
        return
    normalized = profile_id.strip()
    if not normalized:
        return
    if getattr(job, "profile_id", None) != normalized:
        raise AuthorizationError("선택한 프로필의 작업이 아닙니다.")


async def _run_regeneration_job(
    regen_job_id: str,
    original_job_id: str,
    book_id: str,
    page_number: int,
    mode: str,
    feedback: Optional[str],
) -> None:
    """Execute regeneration and persist status transitions for polling."""
    await _set_regen_job_status(
        regen_job_id,
        status="running",
        progress=20,
        current_step="페이지 재생성 중...",
    )

    try:
        await regenerate_page(
            job_id=original_job_id,
            book_id=book_id,
            page_number=page_number,
            mode=mode,
            feedback=feedback,
        )
    except Exception as e:
        await _set_regen_job_status(
            regen_job_id,
            status="failed",
            progress=100,
            current_step="재생성 실패",
            error_code=ErrorCode.UNKNOWN.value,
            error_message=str(e)[:300],
        )
        logger.error(
            "Regeneration job failed",
            regen_job_id=regen_job_id,
            original_job_id=original_job_id,
            page_number=page_number,
            error=str(e),
        )
        return

    await _set_regen_job_status(
        regen_job_id,
        status="done",
        progress=100,
        current_step="완료",
    )


async def check_guardrails(db: AsyncSession, user_key: str):
    """
    Check system guardrails before creating a new job.
    Raises HTTPException if guardrails are violated.
    """
    # Check daily job limit per user
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_jobs_result = await db.execute(
        select(func.count(Job.id)).where(
            and_(Job.user_key == user_key, Job.created_at >= today_start)
        )
    )
    daily_job_count = daily_jobs_result.scalar() or 0

    if daily_job_count >= settings.daily_job_limit_per_user:
        next_day_start = today_start + timedelta(days=1)
        retry_after = max(1, math.ceil((next_day_start - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_limit_exceeded",
                "message": f"일일 생성 한도({settings.daily_job_limit_per_user}권)를 초과했습니다. 내일 다시 시도해주세요.",
                "limit": settings.daily_job_limit_per_user,
                "used": daily_job_count,
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    # Check total pending jobs in system
    pending_jobs_result = await db.execute(
        select(func.count(Job.id)).where(Job.status.in_(["queued", "running"]))
    )
    pending_count = pending_jobs_result.scalar() or 0

    if pending_count >= settings.max_pending_jobs:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "system_overloaded",
                "message": "시스템이 현재 많은 요청을 처리 중입니다. 잠시 후 다시 시도해주세요.",
                "retry_after": 60,
            },
            headers={"Retry-After": "60"},
        )


async def schedule_book_generation(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    job_id: str,
    spec: BookSpec,
    user_key: str,
) -> None:
    """책 생성 백그라운드 작업을 큐에 등록 (Celery/BackgroundTasks). 실패 시 크레딧 환불.

    create_book 과 오늘동화 생성(streak)에서 공유한다.
    """
    if settings.testing:
        logger.info(
            "Skipping book generation background task in testing mode", job_id=job_id
        )
        return
    try:
        if settings.use_celery:
            from src.services.tasks import generate_book_task

            generate_book_task.delay(job_id, spec.model_dump(), user_key)
        else:
            background_tasks.add_task(start_book_generation, job_id, spec, user_key)
    except Exception as e:
        logger.error(
            "Failed to enqueue book generation job",
            job_id=job_id,
            user_key=user_key[:8] + "...",
            error=str(e),
        )
        try:
            await _mark_job_failed_with_refund(
                db=db,
                user_key=user_key,
                job_id=job_id,
                fail_message="작업 큐 등록 실패",
                refund_description="큐 등록 실패 환불",
            )
        except Exception as refund_error:
            await db.rollback()
            logger.error(
                "Failed to refund credit after enqueue failure",
                job_id=job_id,
                user_key=user_key[:8] + "...",
                error=str(refund_error),
            )
        raise InternalServerError(
            "작업 시작에 실패했습니다. 크레딧은 환불되었습니다."
        ) from e


@router.post("", response_model=CreateBookResponse)
async def create_book(
    spec: BookSpec,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """
    새 동화책 생성 요청

    - 비동기로 처리되며 job_id 반환
    - GET /v1/books/{job_id}로 상태 조회
    - 크레딧 1개 필요
    """
    # Check guardrails (daily limit, system load)
    await check_guardrails(db, user_key)
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    # Check idempotency
    if idempotency_key:
        result = await db.execute(
            select(Job).where(
                Job.idempotency_key == idempotency_key,
                Job.user_key == user_key,
            )
        )
        existing_job = result.scalar_one_or_none()
        if existing_job:
            _assert_job_profile_scope(existing_job, scoped_profile_id)
            return CreateBookResponse(
                job_id=existing_job.id,
                status=JobState(existing_job.status),
                estimated_time_seconds=120,
            )

    await _enforce_free_plan_create_limits(db, user_key, spec.style)

    # Create new job
    job_id = f"job_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="대기 중",
        credit_description="책 생성",
        refund_description="잡 생성 실패 환불",
        idempotency_key=idempotency_key,
        profile_id=scoped_profile_id,
    )

    # Start background task (Celery or FastAPI BackgroundTasks)
    await schedule_book_generation(db, background_tasks, job_id, spec, user_key)

    return CreateBookResponse(
        job_id=job_id, status=JobState.queued, estimated_time_seconds=120
    )


@router.get("/{job_id}", response_model=JobStatus, response_model_exclude_none=True)
async def get_book_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    책 생성 상태 조회

    - status: queued, running, failed, done
    - progress: 0-100
    - done일 경우 result에 BookResult 포함
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise NotFoundError("Job", job_id)

    if job.user_key != user_key:
        raise AuthorizationError()
    _assert_job_profile_scope(job, profile_id)

    # Build response
    response = JobStatus(
        job_id=job.id,
        status=JobState(job.status),
        progress=job.progress,
        current_step=job.current_step,
        error=None,
        result=None,
    )

    # Add error info if failed
    if job.status == "failed" and job.error_code:
        from src.models.dto import ErrorInfo, ErrorCode

        try:
            error_code = ErrorCode(job.error_code)
        except ValueError:
            error_code = ErrorCode.UNKNOWN

        response.error = ErrorInfo(
            code=error_code, message=job.error_message or "Unknown error"
        )

    # Add result if done
    if job.status == "done":
        # Fetch book with pages
        book_result = await db.execute(select(Book).where(Book.job_id == job_id))
        book = book_result.scalar_one_or_none()

        if book:
            pages_result = await db.execute(
                select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
            )
            pages = pages_result.scalars().all()
            response.result = _build_book_result(book, pages)

    return response


@router.get("/{book_id}/detail")
async def get_book_detail(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    책 상세 정보 조회 (완료된 책)

    - 서재에서 책 상세 조회 시 사용
    - book_id 기반으로 조회
    """
    # Fetch book
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", book_id)

    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)

    # Fetch pages
    pages_result = await db.execute(
        select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
    )
    pages = pages_result.scalars().all()

    return _build_book_dict(book, pages, include_job_id=True)


@router.post(
    "/{job_id}/pages/{page_number}/regenerate", response_model=RegeneratePageResponse
)
async def regenerate_book_page(
    job_id: str,
    page_number: int,
    request: RegeneratePageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    특정 페이지 재생성

    - mode: text (텍스트만), image (이미지만), both (둘 다)
    - feedback: 재생성 시 반영할 피드백
    """
    # Verify job exists and is done
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise NotFoundError("Job", job_id)

    if job.user_key != user_key:
        raise AuthorizationError()
    _assert_job_profile_scope(job, profile_id)

    if job.status != "done":
        raise ValidationError("Book generation not complete")

    # Verify page exists
    book_result = await db.execute(select(Book).where(Book.job_id == job_id))
    book = book_result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", job_id)

    page_result = await db.execute(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise NotFoundError("Page", str(page_number))

    # Create regeneration task
    regen_job_id = f"regen_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    regen_job = Job(
        id=regen_job_id,
        status="queued",
        progress=0,
        current_step="페이지 재생성 대기 중",
        user_key=user_key,
    )
    db.add(regen_job)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(
            "Failed to create regeneration job",
            regen_job_id=regen_job_id,
            original_job_id=job_id,
            page_number=page_number,
            error=str(e),
        )
        raise InternalServerError("재생성 작업 생성에 실패했습니다.") from e

    background_tasks.add_task(
        _run_regeneration_job,
        regen_job_id,
        job_id,
        book.id,
        page_number,
        request.mode,
        request.feedback,
    )

    return RegeneratePageResponse(job_id=regen_job_id, status=JobState.queued)


@router.post("/series", response_model=CreateBookResponse)
async def create_series_next(
    request: SeriesNextRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    시리즈 다음 권 생성

    - 같은 캐릭터로 새로운 이야기 생성
    - previous_book_id가 있으면 연속성 유지, 없으면 topic 기반 생성
    """
    # Check guardrails (daily limit, system load)
    await check_guardrails(db, user_key)
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    from src.models.db import Character

    # Verify character exists
    char_result = await db.execute(
        select(Character).where(Character.id == request.character_id)
    )
    character = char_result.scalar_one_or_none()

    if not character:
        raise NotFoundError("캐릭터", request.character_id)

    if character.user_key != user_key:
        raise AuthorizationError()

    prev_book = None
    if request.previous_book_id:
        book_result = await db.execute(
            select(Book).where(Book.id == request.previous_book_id)
        )
        prev_book = book_result.scalar_one_or_none()

        if not prev_book:
            raise NotFoundError("Book", request.previous_book_id)
        if prev_book.user_key != user_key:
            raise AuthorizationError()

    await _enforce_free_plan_create_limits(db, user_key, request.style)

    # Create new job for series
    job_id = f"series_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="시리즈 생성 대기 중",
        credit_description="시리즈 생성",
        refund_description="시리즈 잡 생성 실패 환불",
        profile_id=scoped_profile_id,
    )

    # Start background task for series generation
    # 테스트 환경에서는 background_tasks 실행 스킵 (테스트 안정화)
    from src.services.orchestrator import start_series_generation

    if settings.testing:
        logger.info("Skipping series background task in testing mode", job_id=job_id)
    else:
        try:
            background_tasks.add_task(
                start_series_generation, job_id, request, user_key, character, prev_book
            )
        except Exception as e:
            logger.error(
                "Failed to enqueue series generation job",
                job_id=job_id,
                user_key=user_key[:8] + "...",
                error=str(e),
            )
            try:
                await _mark_job_failed_with_refund(
                    db=db,
                    user_key=user_key,
                    job_id=job_id,
                    fail_message="시리즈 작업 큐 등록 실패",
                    refund_description="시리즈 큐 등록 실패 환불",
                )
            except Exception as refund_error:
                await db.rollback()
                logger.error(
                    "Failed to refund credit after series enqueue failure",
                    job_id=job_id,
                    user_key=user_key[:8] + "...",
                    error=str(refund_error),
                )
            raise InternalServerError(
                "시리즈 작업 시작에 실패했습니다. 크레딧은 환불되었습니다."
            ) from e

    return CreateBookResponse(
        job_id=job_id, status=JobState.queued, estimated_time_seconds=120
    )


@router.get("/{book_id}/pdf")
async def export_book_pdf(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    책을 PDF로 내보내기

    - 완료된 책만 PDF로 내보낼 수 있음
    - 표지 + 본문 페이지 + 끝 페이지로 구성
    """
    # Fetch book
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", book_id)

    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)
    await _enforce_free_plan_feature_access(db, user_key, "pdf")

    # Fetch pages
    pages_result = await db.execute(
        select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
    )
    pages = pages_result.scalars().all()

    # Build BookResult for PDF generation
    from src.models.dto import Language, TargetAge

    book_data = BookResult(
        book_id=book.id,
        title=book.title,
        language=Language(book.language),
        target_age=TargetAge(book.target_age),
        style=book.style,
        cover_image_url=book.cover_image_url or "",
        pages=[
            PageResult(
                page_number=p.page_number,
                text=p.text,
                image_url=p.image_url or "",
                image_prompt=p.image_prompt or "",
                audio_url=p.audio_url,
                asset_status=build_page_asset_status(
                    p.image_url,
                    audio_urls=[
                        getattr(p, "audio_url", None),
                        getattr(p, "audio_url_ko", None),
                        getattr(p, "audio_url_en", None),
                    ],
                ),
            )
            for p in pages
        ],
        created_at=book.created_at,
        generation_warnings=build_generation_warnings(
            cover_image_url=book.cover_image_url,
            page_images=[(p.page_number, p.image_url) for p in pages],
        ),
    )

    # Generate PDF
    try:
        pdf_bytes = await pdf_service.generate_pdf(book_data)
    except Exception as e:
        logger.error("PDF generation failed", book_id=book_id, error=str(e))
        raise InternalServerError(
            "PDF 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e

    # Return PDF as response
    # Use URL encoding for Korean filename to avoid header encoding issues
    from urllib.parse import quote

    safe_filename = f"storybook_{book.id}.pdf"
    encoded_filename = quote(f"{book.title.replace(' ', '_')}.pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{encoded_filename}"
        },
    )


@router.post("/{book_id}/audio")
async def generate_book_audio(
    book_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    책 오디오 생성 (TTS)

    - 모든 페이지에 대해 TTS 오디오 생성
    - 비동기로 처리되며 완료 후 각 페이지의 audio_url 업데이트
    """
    # Fetch book
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", book_id)

    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)
    await _enforce_free_plan_feature_access(db, user_key, "audio")

    # Fetch pages
    pages_result = await db.execute(
        select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
    )
    pages = pages_result.scalars().all()

    if not pages:
        raise NotFoundError("Pages", book_id)

    # Start background task for audio generation
    background_tasks.add_task(
        _generate_audio_for_book,
        book_id,
        [
            {
                "page_number": p.page_number,
                "text": p.text,
                "text_ko": p.text_ko,
                "text_en": p.text_en,
                "page_id": p.id,
            }
            for p in pages
        ],
        book.target_age,
        book.language,
    )

    return {"status": "processing", "message": "오디오 생성이 시작되었습니다."}


async def _generate_audio_for_book(
    book_id: str,
    pages: list[dict],
    target_age: str,
    default_language: str,
):
    """책 오디오 생성 백그라운드 태스크 (5분 타임아웃)"""
    import asyncio

    try:
        await asyncio.wait_for(
            _generate_audio_pages(
                book_id=book_id,
                pages=pages,
                target_age=target_age,
                default_language=default_language,
            ),
            timeout=300,
        )
    except asyncio.TimeoutError:
        logger.error("Audio generation timed out", book_id=book_id, total_pages=len(pages))


async def _generate_audio_pages(
    book_id: str,
    pages: list[dict],
    target_age: str = "5-7",
    default_language: str = "ko",
):
    """실제 오디오 생성 로직 (페이지별 상태 추적)"""
    from src.core.database import AsyncSessionLocal

    succeeded = 0
    failed_pages = []

    async with AsyncSessionLocal() as db:
        for page_data in pages:
            try:
                # ko/en 모두 존재하면 각각 생성, 없으면 기본 텍스트로 생성
                generated_urls = {}
                text_by_language = {
                    "ko": page_data.get("text_ko") or page_data.get("text"),
                    "en": page_data.get("text_en"),
                }

                for language in ("ko", "en"):
                    source_text = text_by_language.get(language)
                    if not source_text:
                        continue
                    audio_bytes = await tts_service.synthesize_page(
                        source_text,
                        target_age=target_age,
                        language=language,
                    )
                    audio_key = (
                        f"books/{book_id}/audio/page_{page_data['page_number']}_{language}.mp3"
                    )
                    generated_urls[language] = await storage_service.upload_bytes(
                        audio_bytes,
                        audio_key,
                        content_type="audio/mpeg",
                    )

                page_result = await db.execute(
                    select(Page).where(Page.id == page_data["page_id"])
                )
                page = page_result.scalar_one_or_none()
                if page:
                    if "ko" in generated_urls:
                        page.audio_url_ko = generated_urls["ko"]
                    if "en" in generated_urls:
                        page.audio_url_en = generated_urls["en"]
                    # 하위 호환: 기본 언어 audio_url 유지
                    if default_language == "en" and "en" in generated_urls:
                        page.audio_url = generated_urls["en"]
                    elif "ko" in generated_urls:
                        page.audio_url = generated_urls["ko"]
                    elif generated_urls:
                        page.audio_url = next(iter(generated_urls.values()))
                    await db.commit()
                    succeeded += 1

            except Exception as e:
                try:
                    await db.rollback()
                except Exception as rollback_error:
                    logger.warning(
                        "Audio generation rollback failed",
                        book_id=book_id,
                        page_number=page_data["page_number"],
                        error=str(rollback_error),
                    )
                failed_pages.append(page_data["page_number"])
                logger.warning(
                    "Audio generation failed for page",
                    book_id=book_id,
                    page_number=page_data["page_number"],
                    error=str(e),
                )
                continue

    if failed_pages:
        logger.warning(
            "Audio generation partially failed",
            book_id=book_id,
            succeeded=succeeded,
            failed_pages=failed_pages,
        )
    else:
        logger.info(
            "Audio generation completed",
            book_id=book_id,
            total_pages=succeeded,
        )


@router.get("/{book_id}/pages/{page_number}/audio")
async def get_page_audio(
    book_id: str,
    page_number: int,
    language: str = Query(default="ko", pattern="^(ko|en)$"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    특정 페이지 오디오 URL 조회

    - 이미 생성된 오디오 URL 반환
    - 없으면 즉시 생성 후 반환
    """
    # Fetch book
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", book_id)

    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)
    await _enforce_free_plan_feature_access(db, user_key, "audio")

    # Fetch page
    page_result = await db.execute(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise NotFoundError("Page", str(page_number))

    if not isinstance(language, str):
        language = getattr(language, "default", "ko")
    if language not in {"ko", "en"}:
        language = "ko"

    audio_url_en = getattr(page, "audio_url_en", None)
    audio_url_ko = getattr(page, "audio_url_ko", None)
    audio_url_default = getattr(page, "audio_url", None)

    # 이미 오디오가 있으면 반환
    if language == "en" and audio_url_en:
        return {"audio_url": audio_url_en}
    if language == "ko" and audio_url_ko:
        return {"audio_url": audio_url_ko}
    if audio_url_default and language == "ko":
        return {"audio_url": audio_url_default}

    # 없으면 즉시 생성
    try:
        if language == "en":
            source_text = getattr(page, "text_en", None) or page.text
        else:
            source_text = getattr(page, "text_ko", None) or page.text
        audio_bytes = await tts_service.synthesize_page(
            source_text,
            target_age=getattr(book, "target_age", None),
            language=language,
        )

        # S3에 업로드
        audio_key = f"books/{book_id}/audio/page_{page_number}_{language}.mp3"
        audio_url = await storage_service.upload_bytes(
            audio_bytes, audio_key, content_type="audio/mpeg"
        )

        # DB 업데이트
        if language == "en":
            page.audio_url_en = audio_url
        else:
            page.audio_url_ko = audio_url
        if language == "ko":
            page.audio_url = audio_url
        await db.commit()

        return {"audio_url": audio_url}

    except Exception as e:
        try:
            await db.rollback()
        except Exception as rollback_error:
            logger.warning(
                "Audio generation rollback failed",
                book_id=book_id,
                page_number=page_number,
                error=str(rollback_error),
            )
        logger.error(
            "Audio generation failed", book_id=book_id, page_number=page_number, error=str(e)
        )
        raise InternalServerError(
            "오디오 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e
