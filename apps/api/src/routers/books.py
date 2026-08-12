from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    BackgroundTasks,
    Query,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import Optional
import math
import uuid
import structlog

from src.core.audio_feature import require_audio_supported
from src.core.cost_budget import consume_daily_generation_budget
from src.core.database import get_db
from src.core.book_assets import build_generation_warnings, build_page_asset_status
from src.core.config import settings
from src.core.consent import require_consent_for_characters, require_photo_consent
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
    RetellRequest,
    RetellResponse,
)
from src.models.db import ChildProfile, Job, Book, Page, Character
from src.services.orchestrator import start_book_generation
from src.services.job_runners import (
    run_audio_job,
    run_inpaint_job,
    run_regeneration_job,
    set_regen_job_status,
)
from src.services.image import supports_inpaint
from src.services.pdf import PDFFontError, pdf_service
from src.services.tts import tts_service
from src.services.storage import storage_service
from src.services.credits import credits_service
from src.core.utils import local_day_bounds_utc, local_month_bounds_utc, utcnow
from src.core.errors import (
    ErrorCode,
    PaymentReason,
    SafetyError,
    client_safe_message,
)
from src.core.exceptions import (
    APIError,
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


async def _resolve_effective_plan(db: AsyncSession, user_key: str) -> str:
    subscription = await credits_service.get_active_subscription(db, user_key)
    if not subscription or not isinstance(subscription.plan, str):
        return "free"
    normalized = subscription.plan.strip().lower()
    return normalized if normalized else "free"


async def _count_monthly_book_creations(db: AsyncSession, user_key: str) -> int:
    # '이번 달'도 사용자 tz 로컬 기준(일일 한도·스트릭과 일관, H2).
    from src.services.streak import load_user_tz

    tz = await load_user_tz(db, user_key)
    month_start, month_end = local_month_bounds_utc(tz=tz)
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
            "무료 플랜은 watercolor/cartoon 스타일만 지원합니다. 베이직 이상으로 업그레이드해주세요.",
            details={"reason": PaymentReason.FREE_PLAN_STYLE},
        )

    monthly_limit = max(1, int(getattr(settings, "free_plan_monthly_book_limit", 2) or 2))
    monthly_created = await _count_monthly_book_creations(db, user_key)
    if monthly_created >= monthly_limit:
        raise PaymentRequiredError(
            f"무료 플랜은 월 {monthly_limit}권까지 생성할 수 있습니다. 베이직 이상으로 업그레이드해주세요.",
            details={
                "reason": PaymentReason.FREE_PLAN_MONTHLY_LIMIT,
                "monthly_limit": monthly_limit,
            },
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
        f"무료 플랜에서는 {feature_name} 기능을 사용할 수 없습니다. 베이직 이상으로 업그레이드해주세요.",
        details={"reason": PaymentReason.FREE_PLAN_FEATURE, "feature": feature_name},
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
        raise PaymentRequiredError(
            "크레딧이 부족합니다. 크레딧을 충전해주세요.",
            details={"reason": PaymentReason.INSUFFICIENT_CREDITS},
        )

    credit_used = await credits_service.use_credit(
        db,
        user_key,
        amount=1,
        description=credit_description,
        reference_id=job_id,
    )
    if not credit_used:
        raise PaymentRequiredError(
            "크레딧 차감에 실패했습니다.",
            details={"reason": PaymentReason.CREDIT_CHARGE_FAILED},
        )

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


async def _dispatch_long_running_job(
    *,
    celery_task_name: str,
    runner,
    args: tuple,
    background_tasks: BackgroundTasks,
    job_id: str,
    fail_step: str,
    fail_message: str,
) -> None:
    """장기 실행 잡을 큐(Celery) 또는 API 프로세스(BackgroundTasks)로 위임한다.

    R1: 재생성·인페인트·오디오는 `USE_CELERY` 분기 없이 무조건 BackgroundTasks로 돌았다.
    create_book(:557)·create_series(:1114)가 이미 큐로 보내는 것과 달라, 배포·재시작 중이면
    잡이 비종료 상태로 남고(job_monitor가 15~30분 뒤에야 회수) 최대 90초×재시도의 이미지
    작업이 uvicorn 워커를 점유했다. 두 경로 모두 `runner`(services/job_runners) **동일
    함수**를 실행하므로 로직은 한 벌이다.

    enqueue 실패(브로커 다운)를 삼키면 잡 행이 `queued`로 영구 잔류하므로 fail-closed로
    즉시 failed 전이시킨다 — create_book의 QUEUE_FAILED 처리와 같은 계약.
    """
    if not settings.use_celery:
        background_tasks.add_task(runner, *args)
        return

    try:
        from src.services import tasks as celery_tasks

        getattr(celery_tasks, celery_task_name).delay(*args)
    except Exception as e:
        logger.error(
            "Failed to enqueue long-running job",
            job_id=job_id,
            task=celery_task_name,
            error=str(e),
        )
        await set_regen_job_status(
            job_id,
            status="failed",
            progress=100,
            current_step=fail_step,
            error_code=ErrorCode.QUEUE_FAILED.value,
            error_message=client_safe_message(
                ErrorCode.QUEUE_FAILED.value, fail_message
            )[:300],
        )
        raise InternalServerError(fail_message) from e


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


async def check_guardrails(db: AsyncSession, user_key: str):
    """
    Check system guardrails before creating a new job.
    Raises HTTPException if guardrails are violated.
    """
    # Check daily job limit per user — '하루' 경계는 사용자 tz 로컬 기준(스트릭/오늘읽음과 일관, H2).
    from src.services.streak import load_user_tz

    now = utcnow()
    tz = await load_user_tz(db, user_key)
    today_start, next_day_start = local_day_bounds_utc(now, tz=tz)
    daily_jobs_result = await db.execute(
        select(func.count(Job.id)).where(
            and_(
                Job.user_key == user_key,
                Job.created_at >= today_start,
                Job.created_at < next_day_start,
            )
        )
    )
    daily_job_count = daily_jobs_result.scalar() or 0

    # S4: per-user 통제는 X-User-Key 로테이션으로 전부 우회되므로, 개별 식별자와 무관한
    # 전역 일일 생성 예산으로 총비용을 상한한다(초과 시 429). Redis 장애 시엔 fail-open이나
    # '가드레일 비활성' error 로그가 남는다(cost_budget 모듈).
    budget_ok, budget_used = await consume_daily_generation_budget()
    if not budget_ok:
        # M2: 봉투 코드는 UPPER_SNAKE(다른 모든 코드와 동일 규약). 소문자면 클라이언트가
        # 코드 매칭에 실패해 전용 안내 대신 서버 원문(한국어)을 그대로 띄운다.
        raise APIError(
            status_code=429,
            error_code="SERVICE_BUDGET_EXCEEDED",
            message="오늘 생성 가능한 전체 한도에 도달했어요. 잠시 후 다시 시도해주세요.",
            details={
                "limit": settings.daily_generation_budget,
                "used": budget_used,
                "retry_after": 3600,
            },
            headers={"Retry-After": "3600"},
        )

    if daily_job_count >= settings.daily_job_limit_per_user:
        retry_after = max(1, math.ceil((next_day_start - now).total_seconds()))
        raise APIError(
            status_code=429,
            error_code="DAILY_LIMIT_EXCEEDED",
            message=(
                f"일일 생성 한도({settings.daily_job_limit_per_user}권)를 "
                "초과했습니다. 내일 다시 시도해주세요."
            ),
            details={
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
        raise APIError(
            status_code=503,
            error_code="SYSTEM_OVERLOADED",
            message="시스템이 현재 많은 요청을 처리 중입니다. 잠시 후 다시 시도해주세요.",
            details={"retry_after": 60},
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
    char_ids = list(spec.character_ids or [])
    if spec.character_id:
        char_ids.append(spec.character_id)
    # 캐릭터 소유권 강제 — 타 유저 캐릭터(특히 아동 사진 파생) 도용 차단(IDOR).
    if char_ids:
        owned = await db.execute(
            select(Character.id).where(
                Character.id.in_(char_ids),
                Character.user_key == user_key,
            )
        )
        owned_ids = {row[0] for row in owned.all()}
        if any(cid not in owned_ids for cid in char_ids):
            raise AuthorizationError("선택한 캐릭터의 소유자가 아닙니다.")
    if spec.reference_image_base64:
        await require_photo_consent(db, user_key)
    # 사진/그림 파생 캐릭터(아동 얼굴 데이터)를 재사용하면 동의를 강제(철회 후 차단)
    await require_consent_for_characters(db, user_key, char_ids)

    # Create new job
    job_id = f"job_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="queued",  # M32
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

        # A1-R: 저장된 원문(pydantic 덤프·모델 응답 조각)을 그대로 서빙하지 않는다.
        # 수정 전에 저장된 행까지 막으려면 **서빙 시점** 위생이 정본이다(H2 읽기 경로 교훈).
        response.error = ErrorInfo(
            code=error_code,
            message=client_safe_message(job.error_code, job.error_message),
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

    await _dispatch_long_running_job(
        celery_task_name="regenerate_page_task",
        runner=run_regeneration_job,
        args=(
            regen_job_id,
            job_id,
            book.id,
            page_number,
            request.mode,
            request.feedback,
        ),
        background_tasks=background_tasks,
        job_id=regen_job_id,
        fail_step="재생성 실패",
        fail_message="재생성 작업 등록에 실패했습니다.",
    )

    return RegeneratePageResponse(job_id=regen_job_id, status=JobState.queued)


@router.post(
    "/{job_id}/pages/{page_number}/inpaint",
    response_model=RegeneratePageResponse,
    responses={
        409: {
            "description": (
                "이미지 제공자가 부분 재생성(인페인트)을 지원하지 않음 — "
                "클라이언트는 전체 재생성으로 폴백해야 함(L14 계약 명세)."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "code": "INPAINT_UNSUPPORTED",
                            "message": "현재 이미지 제공자는 부분 재생성을 지원하지 않습니다.",
                        }
                    }
                }
            },
        }
    },
)
async def inpaint_book_page(
    job_id: str,
    page_number: int,
    background_tasks: BackgroundTasks,
    mask: UploadFile = File(..., description="마스크 PNG(흰색=재생성할 영역)"),
    region_prompt: str = Form(..., max_length=200, description="이 영역을 어떻게 바꿀지"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    페이지 부분 재생성(인페인트) — 마스크 영역만 다시 그린다.
    image_provider가 replicate/fal일 때만 동작(아니면 409 → 클라이언트는 전체 재생성 폴백).
    """
    if not supports_inpaint():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INPAINT_UNSUPPORTED",
                "message": "현재 이미지 제공자는 부분 재생성을 지원하지 않습니다.",
            },
        )

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise NotFoundError("Job", job_id)
    if job.user_key != user_key:
        raise AuthorizationError()
    _assert_job_profile_scope(job, profile_id)
    if job.status != "done":
        raise ValidationError("Book generation not complete")

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

    # 마스크 업로드 → S3
    mask_bytes = await mask.read()
    if not mask_bytes:
        raise ValidationError("마스크 이미지가 비어 있습니다.")
    mask_key = f"masks/{book.id}/{page_number}/{uuid.uuid4().hex}.png"
    mask_url = await storage_service.upload_bytes(mask_bytes, mask_key, "image/png")

    inpaint_job_id = (
        f"inpaint_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )
    inpaint_job = Job(
        id=inpaint_job_id,
        status="queued",
        progress=0,
        current_step="부분 재생성 대기 중",
        user_key=user_key,
    )
    db.add(inpaint_job)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(
            "Failed to create inpaint job",
            inpaint_job_id=inpaint_job_id,
            original_job_id=job_id,
            page_number=page_number,
            error=str(e),
        )
        raise InternalServerError("부분 재생성 작업 생성에 실패했습니다.") from e

    await _dispatch_long_running_job(
        celery_task_name="inpaint_page_task",
        runner=run_inpaint_job,
        args=(
            inpaint_job_id,
            job_id,
            book.id,
            page_number,
            mask_url,
            region_prompt,
        ),
        background_tasks=background_tasks,
        job_id=inpaint_job_id,
        fail_step="부분 재생성 실패",
        fail_message="부분 재생성 작업 등록에 실패했습니다.",
    )

    return RegeneratePageResponse(job_id=inpaint_job_id, status=JobState.queued)


@router.post("/series", response_model=CreateBookResponse)
async def create_series_next(
    request: SeriesNextRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """
    시리즈 다음 권 생성

    - 같은 캐릭터로 새로운 이야기 생성
    - previous_book_id가 있으면 연속성 유지, 없으면 topic 기반 생성
    """
    # Check guardrails (daily limit, system load)
    await check_guardrails(db, user_key)
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    # H18: 재시도(타임아웃 후 재탭) 이중 생성·이중 차감 방지 — 기존 잡 반환.
    if idempotency_key:
        existing_job = (
            await db.execute(
                select(Job).where(
                    Job.idempotency_key == idempotency_key,
                    Job.user_key == user_key,
                )
            )
        ).scalar_one_or_none()
        if existing_job:
            _assert_job_profile_scope(existing_job, scoped_profile_id)
            return CreateBookResponse(
                job_id=existing_job.id,
                status=JobState(existing_job.status),
                estimated_time_seconds=120,
            )

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

    # 사진/그림 파생 캐릭터(아동 얼굴 데이터)로 시리즈 속편 생성 시 보호자 동의 강제(철회 후 차단)
    if getattr(character, "from_photo", False):
        await require_photo_consent(db, user_key)

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

    # H19: style 미지정 시 원작(prev_book) 스타일을 상속해 무료플랜 한도 검사(무결성 유지).
    from src.models.dto import Style as _Style

    effective_style = request.style
    if effective_style is None and prev_book and prev_book.style in {s.value for s in _Style}:
        effective_style = _Style(prev_book.style)
    await _enforce_free_plan_create_limits(db, user_key, effective_style)

    # Create new job for series
    job_id = f"series_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="시리즈 생성 대기 중",
        credit_description="시리즈 생성",
        refund_description="시리즈 잡 생성 실패 환불",
        idempotency_key=idempotency_key,
        profile_id=scoped_profile_id,
    )

    # Start background task for series generation
    # 테스트 환경에서는 background_tasks 실행 스킵 (테스트 안정화)
    from src.services.orchestrator import start_series_generation

    if settings.testing:
        logger.info("Skipping series background task in testing mode", job_id=job_id)
    else:
        try:
            # M11: 프로덕션(USE_CELERY)에서는 워커 태스크로 enqueue(API 프로세스 in-process
            # 실행 시 재시작 유실·API 지연). start_series_generation은 ORM 객체를 받아
            # 직렬화 불가하므로 id만 넘기고 태스크가 재조회한다(create_book 대칭).
            if settings.use_celery:
                from src.services.tasks import generate_series_task

                generate_series_task.delay(
                    job_id,
                    request.model_dump(),
                    user_key,
                    character.id if character else None,
                    prev_book.id if prev_book else None,
                )
            else:
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


@router.post("/{book_id}/retell", response_model=RetellResponse)
async def retell_book(
    book_id: str,
    request: RetellRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """
    '아이와 함께 자라는' 리텔 — 같은 책을 다른 연령대 본문으로 다시 써서 새 책으로 저장한다.
    삽화(표지·페이지 이미지)는 그대로 재사용하므로 이미지 생성/크레딧 소모가 없다.
    """
    # H17/G19: 요청 내에서 LLM 리텔을 동기 수행하므로 클라 타임아웃 후 서버는 완주한다
    # (재시도 시 중복 리텔 책 생성 + LLM 비용). H18의 잡 멱등 패턴을 미러해 같은
    # 시도키의 재요청은 기존 결과를 그대로 반환한다.
    if idempotency_key:
        existing_job = (
            await db.execute(
                select(Job).where(
                    Job.idempotency_key == idempotency_key,
                    Job.user_key == user_key,
                )
            )
        ).scalar_one_or_none()
        if existing_job:
            existing_book = (
                await db.execute(
                    select(Book).where(Book.job_id == existing_job.id)
                )
            ).scalar_one_or_none()
            if existing_book:
                return RetellResponse(
                    book_id=existing_book.id,
                    target_age=request.target_age,
                )

    # 원본 책 로드 + 소유권 검증
    source = (
        await db.execute(select(Book).where(Book.id == book_id))
    ).scalar_one_or_none()
    if not source:
        raise NotFoundError("Book", book_id)
    if source.user_key != user_key:
        raise AuthorizationError()

    source_pages = (
        await db.execute(
            select(Page).where(Page.book_id == book_id).order_by(Page.page_number)
        )
    ).scalars().all()
    if not source_pages:
        raise NotFoundError("Pages", book_id)

    # 본문만 새 연령대로 다시 쓰기 (텍스트 전용 LLM 호출)
    from src.services.llm import call_story_retext

    retold = await call_story_retext(
        title=source.title,
        pages_text=[p.text for p in source_pages],
        target_age=request.target_age.value,
        language=source.language,
    )

    # M12: 리텔 결과 출력 모더레이션 — 최초 생성 G 게이트 파리티. 위반 시 저장·공유 전 차단.
    from src.services.orchestrator import moderate_text_localized

    retold_text = " ".join(
        [retold.title or ""] + [p or "" for p in (retold.pages or [])]
    )
    if not await moderate_text_localized(retold_text, source.language):
        raise SafetyError(
            message="다시 쓴 이야기가 안전 기준을 통과하지 못했습니다",
            is_input=False,
        )

    # 새 잡(크레딧 미소모) + 새 책 + 페이지(이미지 재사용)
    new_job_id = f"retell_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    db.add(
        Job(
            id=new_job_id,
            status="done",
            user_key=user_key,
            idempotency_key=idempotency_key,  # H17/G19: 재시도 dedup 키
        )
    )
    await db.flush()

    new_book_id = f"book_{uuid.uuid4().hex[:16]}"
    new_book = Book(
        id=new_book_id,
        job_id=new_job_id,
        title=(retold.title or source.title)[:80],
        language=source.language,
        target_age=request.target_age.value,
        style=source.style,
        theme=source.theme,
        character_id=source.character_id,
        character_ids=source.character_ids,
        cover_image_url=source.cover_image_url,
        user_key=user_key,
        profile_id=source.profile_id,
        # 연령 변형 묶음 — 원본 책으로 역링크
        retelling_source_book_id=book_id,
    )
    db.add(new_book)

    for idx, src_page in enumerate(source_pages):
        text = retold.pages[idx] if idx < len(retold.pages) else src_page.text
        db.add(
            Page(
                book_id=new_book_id,
                page_number=src_page.page_number,
                text=text,
                image_url=src_page.image_url,
                image_prompt=src_page.image_prompt,
            )
        )

    await db.commit()
    logger.info(
        "Book retold for new age",
        source_book=book_id,
        new_book=new_book_id,
        target_age=request.target_age.value,
    )
    return RetellResponse(book_id=new_book_id, target_age=request.target_age)


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
    except PDFFontError as e:
        # H1: 번들 CJK 폰트 누락 = 배포 구성 결함. 조용히 Helvetica로 폴백해 글자가 전부
        # ■ 인 PDF를 배달하는 대신 실패시킨다. 상세는 로그로만(클라이언트엔 안정 키만).
        logger.error(
            "PDF font unavailable",
            book_id=book_id,
            language=getattr(book, "language", None),
            error=str(e),
        )
        raise InternalServerError(
            "PDF 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
            details={"reason": "pdf_font_unavailable"},
        ) from e
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


@router.post(
    "/{book_id}/audio",
    responses={
        409: {
            "description": (
                "이 배포에서 오디오 기능이 비활성(H1/G9) — 클라이언트는 "
                "/v1/config/capabilities의 audio_supported로 UI를 숨겨야 함."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "code": "AUDIO_NOT_SUPPORTED",
                            "message": "이 배포에서는 오디오 기능을 사용할 수 없습니다.",
                        }
                    }
                }
            },
        }
    },
)
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
    # H1/G9: 오디오 비활성 배포에서는 provider 해석 실패 500 대신 명시적 미지원으로 차단.
    require_audio_supported()

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

    # L5: fire-and-forget였던 배치 오디오를 audio_ Job 행으로 관측 가능하게 한다. 실패/타임아웃이
    # 잡 상태(done/failed)로 표면화되고 GET /v1/books/{job_id}로 폴링 가능(형제 regen/inpaint와 대칭).
    audio_job_id = f"audio_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    audio_job = Job(
        id=audio_job_id,
        status="running",
        progress=0,
        current_step="오디오 생성 대기 중",
        user_key=user_key,
    )
    db.add(audio_job)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("Failed to create audio job", book_id=book_id, error=str(e))
        raise InternalServerError("오디오 작업 생성에 실패했습니다.") from e

    # Start background task for audio generation
    await _dispatch_long_running_job(
        celery_task_name="generate_audio_task",
        runner=run_audio_job,
        args=(
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
            audio_job_id,
        ),
        background_tasks=background_tasks,
        job_id=audio_job_id,
        fail_step="오디오 생성 실패",
        fail_message="오디오 작업 등록에 실패했습니다.",
    )

    return {
        "status": "processing",
        "job_id": audio_job_id,
        "message": "오디오 생성이 시작되었습니다.",
    }


@router.get(
    "/{book_id}/pages/{page_number}/audio",
    responses={
        409: {
            "description": (
                "이 배포에서 오디오 기능이 비활성(H1/G9) — 클라이언트는 "
                "/v1/config/capabilities의 audio_supported로 UI를 숨겨야 함."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "code": "AUDIO_NOT_SUPPORTED",
                            "message": "이 배포에서는 오디오 기능을 사용할 수 없습니다.",
                        }
                    }
                }
            },
        }
    },
)
async def get_page_audio(
    book_id: str,
    page_number: int,
    language: str = Query(default="ko", pattern="^(ko|en|ja|zh|es)$"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    특정 페이지 오디오 URL 조회

    - 이미 생성된 오디오 URL 반환
    - 없으면 즉시 생성 후 반환
    """
    # H1/G9: 오디오 비활성 배포에서는 provider 해석 실패 500 대신 명시적 미지원으로 차단.
    require_audio_supported()

    # Fetch book
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", book_id)

    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)

    # Fetch page
    page_result = await db.execute(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise NotFoundError("Page", str(page_number))

    from src.services.tts import SUPPORTED_AUDIO_LANGUAGES

    if not isinstance(language, str):
        language = getattr(language, "default", "ko")
    language = language.lower().strip()
    book_language = str(getattr(book, "language", "") or "ko").lower().strip()

    # H3: 미지원 언어는 조용한 'ko' 강제(=한국어 보이스 오합성) 대신 명시 차단(fail-open 제거).
    if language not in SUPPORTED_AUDIO_LANGUAGES:
        raise ValidationError(
            f"오디오가 지원하지 않는 언어입니다: {language} "
            f"(지원: {', '.join(SUPPORTED_AUDIO_LANGUAGES)})"
        )

    audio_url_en = getattr(page, "audio_url_en", None)
    audio_url_ko = getattr(page, "audio_url_ko", None)
    audio_url_default = getattr(page, "audio_url", None)

    # 이미 생성된 오디오는 무료 플랜도 반환 — 글 못 읽는 아동에게 낭독은 유일한 소비
    # 경로라, 기존 오디오까지 결제벽으로 막지 않는다(비독자 접근성).
    if language == "en" and audio_url_en:
        return {"audio_url": audio_url_en}
    if language == "ko" and audio_url_ko:
        return {"audio_url": audio_url_ko}
    if language == "ko" and audio_url_default and book_language == "ko":
        return {"audio_url": audio_url_default}
    # H3/MA5: ja/zh/es는 책 언어와 일치할 때 기본 슬롯(audio_url)에서 캐시 반환.
    if language not in ("ko", "en") and language == book_language and audio_url_default:
        return {"audio_url": audio_url_default}

    # 신규 합성(비용 발생)은 유료 기능. 단, 비독자 저연령(3-5)은 오디오가 책을 소비하는
    # 유일한 수단이므로 무료 플랜에서도 허용한다. 그 외 연령은 결제 게이트.
    target_age = str(getattr(book, "target_age", "") or "").strip()
    if target_age != "3-5":
        await _enforce_free_plan_feature_access(db, user_key, "audio")

    # 없으면 즉시 생성
    try:
        if language == "en":
            source_text = getattr(page, "text_en", None) or page.text
        elif language == "ko":
            source_text = getattr(page, "text_ko", None) or page.text
        else:
            # H3: ja/zh/es는 책 본문(page.text)을 책 언어 보이스로 합성.
            source_text = page.text
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

        # DB 업데이트 — H3/MA5: 언어별 슬롯. 비 ko/en 책 언어는 기본 슬롯(audio_url)에만
        # 저장하고, ko companion은 책 언어가 ko일 때만 기본 슬롯을 덮어쓴다(교차 오염 방지).
        if language == "en":
            page.audio_url_en = audio_url
        elif language == "ko":
            page.audio_url_ko = audio_url
            if book_language == "ko":
                page.audio_url = audio_url
        else:
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
