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
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func, and_, or_, update, case
from sqlalchemy.orm import defer
from sqlalchemy.sql.elements import ColumnElement
from typing import Optional
import asyncio
import math
import uuid
import structlog

from src.core.audio_feature import require_audio_supported, require_narration_supported
from src.services.storage import media_url
from src.core.cost_budget import consume_daily_generation_budget
from src.core.database import get_db
from src.core.book_assets import build_generation_warnings, build_page_asset_status
from src.core.config import settings
from src.core.consent import require_consent_for_characters, require_photo_consent, require_parental_consent
from src.core.dependencies import get_profile_id, get_user_key, validate_profile_ownership
from src.models.dto import (
    ActiveBookGeneration,
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
from src.models.db import ChildProfile, Job, Book, Page, Character, CreditTransaction, StoryDraftDB
from src.models.dto import Style
from src.models.generation_options import GenerationOptionsResponse
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

# F2: 인페인트 마스크 업로드 상한(캐릭터 이미지와 동일 기준). 업로드 DoS 표면 축소.
_MAX_MASK_BYTES = 10 * 1024 * 1024

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


def _allowed_styles_for_plan(effective_plan: str) -> list[Style]:
    return [
        style for style in Style
        if not _is_free_plan_policy_enabled()
        or effective_plan != "free"
        or style.value in _FREE_PLAN_ALLOWED_STYLES
    ]


@router.get("/generation-options", response_model=GenerationOptionsResponse)
async def get_generation_options(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """Account-specific choices using the same policy enforced on creation."""
    from src.core.generation_access import generation_access_allowed

    effective_plan = await _resolve_effective_plan(db, user_key)
    access_allowed = generation_access_allowed(user_key)
    trial_available = (
        settings.free_plan_first_book_trial and effective_plan == "free"
        and access_allowed
        and await credits_service.first_book_trial_available(db, user_key)
    )
    return GenerationOptionsResponse(
        allowed_styles=_allowed_styles_for_plan(effective_plan),
        first_book_trial_available=trial_available,
        generation_access_allowed=access_allowed,
    )


def _is_book_generation_id(column):
    return or_(column.startswith("job_", autoescape=True), column.startswith("series_", autoescape=True))


@router.get("/active-generations", response_model=list[ActiveBookGeneration])
async def get_active_book_generations(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """Find unfinished books for the authenticated library scope after reopening the app."""
    profile_id = await validate_profile_ownership(db, user_key, profile_id)
    query = select(Job.id, Job.status, Job.progress).where(
        Job.user_key == user_key,
        Job.status.in_(["queued", "running"]),
        _is_book_generation_id(Job.id),
    )
    if profile_id is not None:
        query = query.where(or_(Job.profile_id == profile_id, Job.profile_id.is_(None)))
    rows = (await db.execute(query.order_by(Job.created_at.desc(), Job.id.desc()).limit(20))).all()
    return [
        ActiveBookGeneration(job_id=job_id, status=status, progress=progress or 0)
        for job_id, status, progress in rows
    ]


def _book_creation_quota_filter():
    # Count newly generated books consistently in the daily and monthly quotas.
    # Retells reuse an existing story; page edits/audio are ancillary operations.
    # Failed generations are refunded. All paid attempts still consume the
    # separate service-wide cost budget before provider work starts.
    return and_(
        Job.status.in_(["queued", "running", "done"]),
        _is_book_generation_id(Job.id),
    )


def _creation_ids_in_period(user_key: str, start, end):
    """Surviving jobs plus minimal billing records after child-content erasure."""
    live_jobs = select(Job.id.label("creation_id")).where(
        Job.user_key == user_key, Job.created_at >= start, Job.created_at < end,
        _book_creation_quota_filter(),
    )
    refunded = select(CreditTransaction.reference_id).where(
        CreditTransaction.user_key == user_key,
        CreditTransaction.transaction_type == "refund",
        CreditTransaction.reference_id.is_not(None),
    )
    charged = select(CreditTransaction.reference_id.label("creation_id")).where(
        CreditTransaction.user_key == user_key,
        CreditTransaction.transaction_type == "usage",
        CreditTransaction.created_at >= start, CreditTransaction.created_at < end,
        _is_book_generation_id(CreditTransaction.reference_id),
        CreditTransaction.reference_id.not_in(refunded),
    )
    return live_jobs.union(charged).subquery()


async def _count_monthly_book_creations(db: AsyncSession, user_key: str) -> int:
    month_start, month_end = local_month_bounds_utc()
    result = await db.execute(select(func.count()).select_from(
        _creation_ids_in_period(user_key, month_start, month_end)))
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
    if normalized_style not in {style.value for style in _allowed_styles_for_plan(effective_plan)}:
        raise PaymentRequiredError(
            "무료 플랜은 watercolor/cartoon 스타일만 지원합니다. 베이직 이상으로 업그레이드해주세요.",
            details={"reason": PaymentReason.FREE_PLAN_STYLE},
        )

    if settings.free_plan_first_book_trial:
        # One signup credit is the trial limit. Existing/purchased credits can
        # still be spent after the trial without a recurring monthly grant.
        return

    monthly_limit = max(1, int(getattr(settings, "free_plan_monthly_book_limit", 2) or 2))
    monthly_created = await _count_monthly_book_creations(db, user_key)
    if monthly_created >= monthly_limit:
        _, month_end = local_month_bounds_utc()
        raise PaymentRequiredError(
            f"무료 플랜은 월 {monthly_limit}권까지 생성할 수 있습니다. 베이직 이상으로 업그레이드해주세요.",
            details={
                "reason": PaymentReason.FREE_PLAN_MONTHLY_LIMIT,
                "monthly_limit": monthly_limit,
                "used": monthly_created,
                "resets_at": month_end.isoformat() + "Z",
                "retry_after": max(1, int((month_end - utcnow()).total_seconds())),
            },
        )


async def _enforce_free_plan_feature_access(
    db: AsyncSession,
    user_key: str,
    feature: str,
    *,
    narration_job_id: str | None = None,
) -> None:
    if not _is_free_plan_policy_enabled():
        return

    effective_plan = await _resolve_effective_plan(db, user_key)
    if effective_plan != "free":
        return

    if (
        settings.free_plan_first_book_trial
        and narration_job_id is not None
        and await credits_service.book_credit_spent(db, user_key, narration_job_id)
    ):
        return

    feature_name = _FREE_PLAN_BLOCKED_FEATURES.get(feature, "해당")
    raise PaymentRequiredError(
        f"무료 플랜에서는 {feature_name} 기능을 사용할 수 없습니다. 베이직 이상으로 업그레이드해주세요.",
        details={"reason": PaymentReason.FREE_PLAN_FEATURE, "feature": feature_name},
    )


def _build_page_dict(p) -> dict:
    """Build standardized page response dict from a Page model."""
    image_url = media_url(p.image_url)
    audio_url = media_url(p.audio_url)
    audio_url_ko = media_url(p.audio_url_ko)
    audio_url_en = media_url(p.audio_url_en)
    asset_status = build_page_asset_status(
        image_url, audio_urls=(audio_url, audio_url_ko, audio_url_en),
    )
    return {
        "page_number": p.page_number,
        "text": p.text,
        "image_url": image_url or "",
        "image_prompt": p.image_prompt,
        "audio_url": audio_url,
        "text_ko": p.text_ko,
        "text_en": p.text_en,
        "audio_url_ko": audio_url_ko,
        "audio_url_en": audio_url_en,
        "vocab": p.vocab,
        "comprehension_questions": p.comprehension,
        "quiz": p.quiz,
        "asset_status": asset_status,
    }


def _build_book_dict(book, pages, *, learning_assets: dict | None, include_job_id: bool = False) -> dict:
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
        "cover_image_url": media_url(book.cover_image_url) or "",
        "series_id": book.series_id,
        "series_index": book.series_index,
        "title_ko": book.title_ko,
        "title_en": book.title_en,
        "pages": [_build_page_dict(p) for p in pages],
        "learning_assets": learning_assets,
        "generation_warnings": generation_warnings,
        "created_at": book.created_at.isoformat(),
    }
    if include_job_id:
        result["job_id"] = book.job_id
        result["theme"] = book.theme
        result["character_id"] = book.character_id
        result["pdf_url"] = media_url(book.pdf_url)
        result["audio_url"] = media_url(book.audio_url)
    return result


def _build_book_result(book, pages, include_job_id: bool = False) -> BookResult:
    """Build a strongly typed BookResult to keep response serialization aligned."""
    return BookResult.model_validate(
        _build_book_dict(
            book, pages, learning_assets=book.learning_assets, include_job_id=include_job_id
        )
    )


def get_idempotency_key(
    x_idempotency_key: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract idempotency key from header"""
    return x_idempotency_key


async def _existing_creation_response(
    db: AsyncSession, user_key: str, idempotency_key: Optional[str],
    profile_id: Optional[str],
) -> Optional[CreateBookResponse]:
    if not idempotency_key:
        return None
    job = await db.scalar(
        select(Job).where(Job.user_key == user_key, Job.idempotency_key == idempotency_key)
        .execution_options(populate_existing=True)
    )
    if job is None:
        return None
    _assert_job_profile_scope(job, profile_id)
    return CreateBookResponse(
        job_id=job.id, status=JobState(job.status), estimated_time_seconds=120,
    )


async def _create_job_with_credit(
    *,
    db: AsyncSession,
    user_key: str,
    job_id: str,
    current_step: str,
    credit_description: str,
    idempotency_key: Optional[str] = None,
    profile_id: Optional[str] = None,
    validated_style: object = None,
    character_ids: Optional[list[str]] = None,
    budget_endpoint: str = "books.create",
) -> Optional[CreateBookResponse]:
    """
    Create a queued job with credit deduction, **atomically**.

    F3(감사 books.py:264): 차감과 잡 INSERT를 **한 트랜잭션·한 커밋**으로 묶는다. 예전에는
    use_credit 이 먼저 커밋하고 잡 생성이 별도 커밋이라, 그 사이 프로세스가 죽으면 크레딧만
    빠지고 잡은 없는 무성 유실이 났다(try/except 는 예외만 잡고 프로세스 사망은 못 잡는다).
    이제 크래시 창이 닫힌다 — 커밋 전이면 DB가 차감까지 함께 롤백, 커밋 후면 둘 다 영속.
    실패 시 롤백이 차감을 되돌리므로 **별도 환불 경로가 필요 없다**.
    """
    from src.services.photo_lifecycle import lock_photo_account

    await lock_photo_account(db, user_key)
    existing = await _existing_creation_response(db, user_key, idempotency_key, profile_id)
    if existing:
        return existing
    from src.services.photo_book_references import validate_photo_book_selection

    await require_parental_consent(db, user_key)
    await _validate_profile_ownership(db, user_key, profile_id)
    photo_character = await validate_photo_book_selection(db, user_key, character_ids or [])
    from src.services.provider_runtime import ensure_generation_available
    await ensure_generation_available()
    has_credits = await credits_service.has_credits(db, user_key, required=1)
    if not has_credits:
        await db.rollback()
        existing = await _existing_creation_response(db, user_key, idempotency_key, profile_id)
        if existing:
            return existing
        raise PaymentRequiredError(
            "크레딧이 부족합니다. 크레딧을 충전해주세요.",
            details={"reason": PaymentReason.INSUFFICIENT_CREDITS},
        )

    # commit=False: 차감을 커밋하지 않고 트랜잭션에 남겨 잡 INSERT 와 같은 커밋으로 원자화.
    credit_used = await credits_service.use_credit(
        db,
        user_key,
        amount=1,
        description=credit_description,
        reference_id=job_id,
        commit=False,
    )
    if not credit_used:
        # 동시 차감 등으로 조건부 UPDATE 가 0행이면(부족) 미커밋 상태를 폐기하고 거절.
        await db.rollback()
        existing = await _existing_creation_response(db, user_key, idempotency_key, profile_id)
        if existing:
            return existing
        raise PaymentRequiredError(
            "크레딧 차감에 실패했습니다.",
            details={"reason": PaymentReason.CREDIT_CHARGE_FAILED},
        )

    try:
        # A competing request can commit while this request waits for the credit
        # UPDATE. Return its job and discard this reservation before any limits.
        existing = await _existing_creation_response(db, user_key, idempotency_key, profile_id)
        if existing:
            await db.rollback()
            return existing
        # The credit UPDATE above holds this user's row lock until commit.
        # Recheck the count while serialized so simultaneous taps cannot all
        # pass a read-then-insert daily/pending limit.
        await check_guardrails(db, user_key)
        if validated_style is not None:
            await _enforce_free_plan_create_limits(db, user_key, validated_style)
        job = Job(
            id=job_id,
            status="queued",
            progress=0,
            current_step=current_step,
            user_key=user_key,
            profile_id=profile_id,
            idempotency_key=idempotency_key,
            photo_derived=photo_character is not None,
        )
        db.add(job)
        await db.flush()
        await consume_generation_budget(endpoint=budget_endpoint, user_key=user_key)
        await db.commit()  # 차감 + 잡 INSERT 를 함께 커밋(원자적).
    except APIError:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        # Recover only a committed job for this owner/key. Other constraint
        # failures still fail; never dispatch a second task or charge twice.
        existing = await _existing_creation_response(db, user_key, idempotency_key, profile_id)
        if existing:
            return existing
        raise InternalServerError(
            message="잡 생성에 실패했습니다. 크레딧은 차감되지 않았습니다."
        ) from e
    except Exception as e:
        # 롤백이 차감까지 되돌린다 — 환불 트랜잭션 없이 원상복구.
        logger.error(
            "Job creation failed; deduction rolled back atomically",
            job_id=job_id,
            error_type=type(e).__name__,
        )
        await db.rollback()
        raise InternalServerError(
            message="잡 생성에 실패했습니다. 크레딧은 차감되지 않았습니다."
        ) from e


async def _mark_job_failed_with_refund(
    *,
    db: AsyncSession,
    user_key: str,
    job_id: str,
    fail_message: str,
    refund_description: str,
) -> None:
    """Persist failure before refund; the monitor retries an interrupted refund."""
    result = await db.execute(
        update(Job).where(
            Job.id == job_id, Job.user_key == user_key,
            Job.status.in_(["queued", "running"]),
        ).values(status="failed", error_code=ErrorCode.QUEUE_FAILED.value,
                 error_message=fail_message[:300], updated_at=utcnow())
    )
    await db.commit()
    if result.rowcount != 1:
        return

    await credits_service.refund_for_job(
        db, user_key, job_id,
        description=refund_description,
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
    scope = getattr(book, "profile_id", None)
    # 배정되지 않은(프로필 도입 전에 만든) 책은 계정 공용 — 목록 필터와 같은 규칙.
    if scope is not None and scope != normalized:
        raise AuthorizationError("선택한 프로필의 책이 아닙니다.")


def _owned_book_pages(user_key: str, profile_id: Optional[str]):
    """Join page content only for the permitted book owner and profile."""
    conditions = [Page.book_id == Book.id, Book.user_key == user_key]
    if isinstance(profile_id, str) and (scope := profile_id.strip()):
        conditions.append(or_(Book.profile_id.is_(None), Book.profile_id == scope))
    return and_(*conditions)


async def _load_book_with_pages(
    db: AsyncSession, selector: ColumnElement[bool], user_key: str, profile_id: Optional[str],
) -> tuple[Book, list[Page], dict | None] | None:
    # Keep the book and its pages in one snapshot, with learning assets on one row.
    learning_assets = case(
        (func.row_number().over(order_by=Page.page_number) == 1, Book.learning_assets)
    )
    result = await db.execute(
        select(Book, Page, learning_assets)
        .options(defer(Book.learning_assets))
        .outerjoin(Page, _owned_book_pages(user_key, profile_id))
        .where(selector)
        .order_by(Page.page_number)
    )
    rows = result.all()
    if not rows:
        return None

    book, _, assets = rows[0]
    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)
    return book, [page for _, page, _ in rows if page is not None], assets


def _assert_job_profile_scope(
    job: Job,
    profile_id: Optional[str],
) -> None:
    if not isinstance(profile_id, str):
        return
    normalized = profile_id.strip()
    if not normalized:
        return
    scope = getattr(job, "profile_id", None)
    # 위와 같은 이유. 배정되지 않은 작업은 계정 공용이다.
    if scope is not None and scope != normalized:
        raise AuthorizationError("선택한 프로필의 작업이 아닙니다.")


async def enforce_book_spec_access(
    db: AsyncSession,
    user_key: str,
    spec: BookSpec,
) -> list[str]:
    """책 생성 요청의 **캐릭터 소유권 + 아동 사진 동의**를 강제한다. 반환: 정규화된 캐릭터 id.

    H7(2026-08-17 감사): 이 블록은 `create_book` 안에만 있었고 `/v1/streak/today/generate` 는
    같은 생성 파이프라인을 타면서 **둘 다 건너뛰었다** — 타인 캐릭터로 생성(IDOR) + 동의 없는
    아동 사진 캐릭터로 생성이 가능했다. 규칙이 두 벌이면 한 쪽이 샌다는 이 저장소의 반복
    결함이라, 헬퍼로 뽑아 두 경로가 **같은 코드**를 공유하게 한다.

    새로운 생성 진입점을 만들 때는 반드시 이 함수를 호출해야 한다
    (`test_security_wave_20260817.py` 의 구조 불변식 테스트가 전수를 강제한다).
    """
    await require_parental_consent(db, user_key)
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
        raise APIError(409, "CHARACTER_APPROVAL_REQUIRED", "사진으로 캐릭터를 만든 뒤 모습을 확인해주세요.")
    # 사진/그림 파생 캐릭터(아동 얼굴 데이터)를 재사용하면 동의를 강제(철회 후 차단)
    await require_consent_for_characters(db, user_key, char_ids)
    from src.services.photo_book_references import selected_character_ids, validate_photo_book_selection

    await validate_photo_book_selection(db, user_key, selected_character_ids(spec))
    return char_ids


async def consume_generation_budget(*, endpoint: str, user_key: str | None = None) -> None:
    """실비용(LLM/이미지) 발생 **직전**에 전역 일일 예산을 1 소비한다 (H4/H5/M10).

    두 가지 계약이 여기 있다.

    1. **전수 적용** (H5/R3-2): 예전에는 `create_book` 한 곳만 예산을 소비했다. retell·비전
       캐릭터·페이지 재생성·인페인트·오늘의 동화는 모두 실제 유료 LLM/이미지 호출을 하면서
       카운터를 통과하지 않아, 예산을 켜도 **무계량 청구 채널**로 남았다(X-User-Key는
       무제한 발급이라 볼륨도 무제한).
    2. **consume-after-validate** (M10/R3-3): 예산 소비는 요청검증·멱등·동의·소유권 검증을
       모두 통과한 뒤에 한다. 검증 **전**에 소비하면 비용 0인 무효 요청 스팸만으로 전역
       카운터가 소진되어, 가드레일 자체가 전 사용자 대상 DoS 벡터가 된다.

    호출부는 실제 비용이 나가는 지점에 최대한 가깝게 배치한다.
    """
    from src.core.generation_access import require_generation_access
    require_generation_access(user_key)
    if endpoint.startswith("books.") or endpoint == "streak.today_generate":
        from src.services.illustration_quality_pipeline import quality_enabled_for_operation

        quality_enabled_for_operation()
    from src.services.provider_runtime import ensure_generation_available
    await ensure_generation_available()
    budget_ok, budget_used = await consume_daily_generation_budget()
    if budget_ok:
        return
    # M2: 봉투 코드는 UPPER_SNAKE(다른 모든 코드와 동일 규약). 소문자면 클라이언트가
    # 코드 매칭에 실패해 전용 안내 대신 서버 원문(한국어)을 그대로 띄운다.
    raise APIError(
        status_code=429,
        error_code="SERVICE_BUDGET_EXCEEDED",
        message="오늘 생성 가능한 전체 한도에 도달했어요. 잠시 후 다시 시도해주세요.",
        details={
            "limit": settings.daily_generation_budget,
            "used": budget_used,
            "endpoint": endpoint,
            "retry_after": 3600,
        },
        headers={"Retry-After": "3600"},
    )


async def check_guardrails(db: AsyncSession, user_key: str):
    """
    Check system guardrails before creating a new job.
    Raises HTTPException if guardrails are violated.

    M10/R3-3: 전역 예산 소비는 여기서 하지 않는다 — 이 함수는 **선검증 단계**에서 호출되며,
    비용 0인 무효 요청(소유권 실패·동의 없음·멱등 재시도)도 여기를 지난다. 예산은
    `consume_generation_budget()` 으로 실제 비용 직전에 소비한다.
    """
    await require_parental_consent(db, user_key)
    # New-book quota, not every background task. Keep the same book/status
    # definition as the monthly quota and use the user's local day boundary.
    from src.services.streak import load_user_tz

    now = utcnow()
    tz = await load_user_tz(db, user_key)
    today_start, next_day_start = local_day_bounds_utc(now, tz=tz)
    daily_jobs_result = await db.execute(select(func.count()).select_from(
        _creation_ids_in_period(user_key, today_start, next_day_start)))
    daily_job_count = daily_jobs_result.scalar() or 0

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

    # M11/R3-4: per-user 큐 한도를 **먼저** 본다. 예전에는 전역 합산 카운터 하나뿐이라,
    # 공격자가 큐를 max_pending_jobs 만큼 채우면 **전 사용자**가 503을 맞았다(공유자원 고갈).
    # 개인 상한이 있으면 한 사용자가 전역 상한에 도달하는 것 자체가 불가능해진다.
    user_pending_result = await db.execute(
        select(func.count(Job.id)).where(
            Job.user_key == user_key,
            Job.status.in_(["queued", "running"]),
        )
    )
    user_pending_count = user_pending_result.scalar() or 0
    if user_pending_count >= settings.max_pending_jobs_per_user:
        raise APIError(
            status_code=429,
            error_code="TOO_MANY_PENDING_JOBS",
            message="처리 중인 요청이 많아요. 완료된 뒤 다시 시도해주세요.",
            details={
                "limit": settings.max_pending_jobs_per_user,
                "pending": user_pending_count,
                "retry_after": 60,
            },
            headers={"Retry-After": "60"},
        )

    # 전역 상한은 '시스템 과부하' 신호로만 남긴다(per-user 상한보다 훨씬 크게 설정).
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
            "작업 시작에 실패했습니다. 사용한 크레딧은 자동으로 환불 처리됩니다."
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
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    # Check idempotency
    if idempotency_key:
        # Serialize same-account retries on PostgreSQL before quota/budget checks.
        from src.services.photo_lifecycle import lock_photo_account

        await lock_photo_account(db, user_key)
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

    await check_guardrails(db, user_key)
    await _enforce_free_plan_create_limits(db, user_key, spec.style)
    await enforce_book_spec_access(db, user_key, spec)

    # Create new job
    job_id = f"job_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    existing = await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="queued",  # M32
        credit_description="책 생성",
        character_ids=spec.character_ids or ([spec.character_id] if spec.character_id else []),
        idempotency_key=idempotency_key,
        profile_id=scoped_profile_id,
        validated_style=spec.style,
    )
    if existing:
        return existing

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

    if job.status == "failed":
        transactions = (await db.execute(select(CreditTransaction.transaction_type).where(
            CreditTransaction.user_key == user_key,
            CreditTransaction.reference_id == job.id,
            CreditTransaction.transaction_type.in_(["usage", "refund"]),
        ))).scalars().all()
        response.credit_refund_status = (
            "refunded" if "refund" in transactions else
            "pending" if "usage" in transactions else "not_charged"
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
        completed = await _load_book_with_pages(
            db, Book.job_id == job_id, user_key, job.profile_id or profile_id,
        )
        if completed is not None:
            book, pages, assets = completed
            response.result = BookResult.model_validate(
                _build_book_dict(book, pages, learning_assets=assets)
            )

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
    completed = await _load_book_with_pages(db, Book.id == book_id, user_key, profile_id)
    if completed is None:
        raise NotFoundError("Book", book_id)

    book, pages, assets = completed
    detail = _build_book_dict(book, pages, learning_assets=assets, include_job_id=True)
    # Books created without a saved Character still have a named lead in their draft.
    cast = await db.scalar(select(StoryDraftDB.draft["characters"]).where(StoryDraftDB.job_id == book.job_id))
    if isinstance(cast, list):
        detail["protagonist_name"] = next((
            member["name"] for member in cast if isinstance(member, dict)
            and member.get("role") == "main" and isinstance(member.get("name"), str)
        ), None)
    return detail


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
    from src.services.photo_lifecycle import lock_photo_account

    await lock_photo_account(db, user_key)
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

    # H5/R3-2: 페이지 재생성은 LLM 재작성 + 이미지 재생성을 유발하는 실비용 경로다.
    # M10/R3-3: 소유권·상태·페이지 존재 검증을 모두 통과한 뒤 소비.
    from src.services.photo_book_references import existing_book_is_photo_derived, reference_for_existing_book

    photo_derived = await existing_book_is_photo_derived(db, book)
    if photo_derived:
        await reference_for_existing_book(job_id, user_key)
    await require_parental_consent(db, user_key)
    await consume_generation_budget(endpoint="books.regenerate", user_key=user_key)

    # Create regeneration task
    regen_job_id = f"regen_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    regen_job = Job(
        id=regen_job_id,
        status="queued",
        progress=0,
        current_step="페이지 재생성 대기 중",
        user_key=user_key,
        # 원본 잡의 프로필 범위를 그대로 물려받는다. 비워 두면 프로필을 쓰는 앱이
        # 자기가 만든 재생성 잡을 조회할 때 _assert_job_profile_scope 에서 403을 맞아
        # 결과를 영영 확인하지 못한다(범위를 넓히지도 좁히지도 않는다).
        profile_id=job.profile_id,
        photo_derived=photo_derived,
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

    from src.services.photo_lifecycle import lock_photo_account

    await lock_photo_account(db, user_key)
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

    # F2(감사 books.py:895): 마스크 업로드를 **예산 소비·스토리지 쓰기 전**에 검증한다.
    # content-type 이 명시됐고 image/* 가 아니면 거부한다(오업로드 차단). None/octet-stream 은
    # 관대하게 허용한다 — Dio MultipartFile 이 content-type 을 안 채우는 경우가 있어 엄격히
    # 거부하면 실 클라이언트를 깰 수 있고, 인페인트는 기본 GA 에서 409 로 게이트되며 마스크는
    # 사용자 본인 소유물이라 위해가 낮다. 제한보다 1바이트만 더 읽어 크기를 판별하고
    # 앱 메모리·스토리지 쓰기·예산 소비·provider 호출로의 확대를 막는다. multipart 파서의
    # 수신·임시 파일 자체는 별도 프록시 요청 크기 제한이 필요하다.
    if mask.content_type and not mask.content_type.lower().startswith("image/"):
        raise ValidationError("마스크는 이미지 파일이어야 합니다.")
    mask_bytes = await mask.read(_MAX_MASK_BYTES + 1)
    if not mask_bytes:
        raise ValidationError("마스크 이미지가 비어 있습니다.")
    if len(mask_bytes) > _MAX_MASK_BYTES:
        raise ValidationError("마스크 이미지가 너무 큽니다(최대 10MB).")

    # H5/R3-2: 인페인트도 유료 이미지 호출이다. M10/R3-3: 검증 통과 후, 업로드·생성 직전.
    from src.services.photo_book_references import existing_book_is_photo_derived, reference_for_existing_book

    photo_derived = await existing_book_is_photo_derived(db, book)
    if photo_derived:
        await reference_for_existing_book(job_id, user_key)
    await require_parental_consent(db, user_key)
    await consume_generation_budget(endpoint="books.inpaint", user_key=user_key)

    # 마스크 업로드 → S3
    mask_key = f"masks/{book.id}/{page_number}/{uuid.uuid4().hex}.png"

    inpaint_job_id = (
        f"inpaint_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )
    inpaint_job = Job(
        id=inpaint_job_id,
        status="queued",
        progress=0,
        current_step="부분 재생성 대기 중",
        user_key=user_key,
        # 재생성과 같은 이유로 원본 잡의 프로필 범위를 물려받는다(미설정 시 폴링이 403).
        profile_id=job.profile_id,
        photo_derived=photo_derived,
        # F2: 마스크 키를 잡에 기록 — 계정 삭제(전 잡 image_keys 수집)가 이 고아를 파기.
        image_keys=[mask_key],
    )
    from src.services.purge_queue import cancel_purge_task, enqueue_purge_keys
    from src.services.generation_consent import require_active_book_job

    mask_guard = enqueue_purge_keys(db, user_key=user_key, reason="inpaint_mask_upload", keys=[mask_key])[0]
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

    try:
        mask_url = await storage_service.upload_bytes(mask_bytes, mask_key, "image/png")
        await require_active_book_job(db, inpaint_job_id, user_key)
        if not await db.scalar(select(Book.id).where(Book.id == book.id, Book.user_key == user_key)):
            raise NotFoundError("Book", book.id)
        cancel_purge_task(mask_guard)
        await db.commit()
    except Exception:
        await db.rollback()
        await set_regen_job_status(inpaint_job_id, status="failed", progress=100,
                                  current_step="마스크 업로드 실패", error_code="IMAGE_FAILED")
        raise

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
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    # H18: 재시도(타임아웃 후 재탭) 이중 생성·이중 차감 방지 — 기존 잡 반환.
    if idempotency_key:
        from src.services.photo_lifecycle import lock_photo_account

        await lock_photo_account(db, user_key)
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

    await check_guardrails(db, user_key)
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
        from src.services.photo_book_references import validate_photo_book_selection

        await validate_photo_book_selection(db, user_key, [character.id])

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

    from src.services.series_ownership import owned_series

    series_id = request.series_id or (prev_book.series_id if prev_book else None)
    if series_id:
        await owned_series(db, series_id, user_key, allow_missing=True)

    # H19: style 미지정 시 원작(prev_book) 스타일을 상속해 무료플랜 한도 검사(무결성 유지).
    from src.models.dto import Style as _Style

    effective_style = request.style
    if effective_style is None and prev_book and prev_book.style in {s.value for s in _Style}:
        effective_style = _Style(prev_book.style)
    if effective_style is None:
        effective_style = _Style.watercolor
    await _enforce_free_plan_create_limits(db, user_key, effective_style)

    # Create new job for series
    job_id = f"series_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    existing = await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="시리즈 생성 대기 중",
        credit_description="시리즈 생성",
        budget_endpoint="books.series",
        character_ids=[request.character_id],
        idempotency_key=idempotency_key,
        profile_id=scoped_profile_id,
        validated_style=effective_style,
    )
    if existing:
        return existing

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


async def _copy_retell_image(
    source_url: Optional[str],
    new_book_id: str,
    label: str,
    copied_keys: list[str],
) -> Optional[str]:
    """리텔 책이 쓸 삽화 사본을 만들고 새 공개 URL을 반환한다 (H6).

    - 원본 URL이 없으면 None(삽화 없는 페이지 — 그대로 없음).
    - 우리 버킷이 아닌 외부 URL은 역산·복사가 불가능하다. 이 경우 **공유하지 않고** 링크를
      그대로 두되(파기 대상이 아니므로 404 위험도 없다) 복제 목록에는 넣지 않는다.
    - 복사 실패는 fail-closed: 공유 상태로 만들지 않고 명시 실패한다(멱등키로 재시도 가능).
    """
    if not source_url:
        return None

    from src.services.storage import copy_object_to_new_key, key_from_public_url

    source_key = key_from_public_url(source_url)
    if not source_key:
        # 우리 버킷 밖 — 삭제 경로의 역산 대상이 아니므로 공유 위험이 없다.
        return source_url

    ext = source_key.rsplit(".", 1)[-1] if "." in source_key.rsplit("/", 1)[-1] else "png"
    new_key = f"images/retell/{new_book_id}/{label}_{uuid.uuid4().hex[:8]}.{ext}"
    try:
        new_url = await copy_object_to_new_key(source_url, new_key)
    except Exception as e:
        logger.error(
            "retell image copy failed",
            source_key=source_key,
            new_key=new_key,
            error=str(e),
        )
        raise InternalServerError(
            "삽화를 복사하지 못했습니다. 잠시 후 다시 시도해주세요."
        ) from e
    if not new_url:
        return source_url
    copied_keys.append(new_key)
    return new_url


@router.post("/{book_id}/retell", response_model=RetellResponse)
async def retell_book(
    book_id: str,
    request: RetellRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    '아이와 함께 자라는' 리텔 — 같은 책을 다른 연령대 본문으로 다시 써서 새 책으로 저장한다.
    삽화(표지·페이지 이미지)는 그대로 재사용하므로 이미지 생성/크레딧 소모가 없다.
    """
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
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
            _assert_job_profile_scope(existing_job, scoped_profile_id)
            existing_book = (
                await db.execute(
                    select(Book).where(Book.job_id == existing_job.id)
                )
            ).scalar_one_or_none()
            if existing_book:
                _assert_book_profile_scope(existing_book, scoped_profile_id)
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
    _assert_book_profile_scope(source, scoped_profile_id)

    source_pages = (
        await db.execute(
            select(Page).where(Page.book_id == book_id).order_by(Page.page_number)
        )
    ).scalars().all()
    if not source_pages:
        raise NotFoundError("Pages", book_id)

    # H5/R3-2: retell은 유료 LLM 호출인데 예산·크레딧 어느 쪽도 계량하지 않았다 —
    # 예산을 켜도 우회되는 무계량 청구 채널이었다. M10/R3-3에 따라 소유권·멱등 검증을
    # 모두 통과한 뒤(=실비용 직전) 소비한다.
    from src.services.photo_book_references import existing_book_is_photo_derived, reference_for_existing_book

    photo_derived = await existing_book_is_photo_derived(db, source)
    character_reference = await reference_for_existing_book(source.job_id, user_key) if photo_derived else None
    source_job = await db.get(Job, source.job_id)
    await require_parental_consent(db, user_key)
    await consume_generation_budget(endpoint="books.retell", user_key=user_key)

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

    if getattr(settings, "illustration_quality_enabled", False):
        from src.services.illustration_quality_edits import publish_verified_retell

        new_book_id = await publish_verified_retell(
            source_book_id=book_id, user_key=user_key, retold=retold,
            target_age=request.target_age.value, idempotency_key=idempotency_key,
        )
        return RetellResponse(book_id=new_book_id, target_age=request.target_age)

    # 새 잡(크레딧 미소모) + 새 책 + 페이지
    new_job_id = f"retell_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    new_book_id = f"book_{uuid.uuid4().hex[:16]}"

    # H6: 삽화는 재생성하지 않지만 **URL을 그대로 복사하면 안 된다**. 예전에는 원본과 리텔이
    # 같은 S3 객체를 가리켰고, 삭제 경로(image_url 역산 파기)는 배타 소유를 가정하므로
    # 둘 중 하나만 지워도 남은 책의 표지·전 페이지가 404가 됐다. 서버측 copy로 리텔이 자기
    # 객체를 갖게 한다(다운로드/업로드 없음). 실패는 fail-closed — 공유 상태로 만들지 않는다.
    from src.services.purge_queue import enqueue_purge_prefix, cancel_purge_task

    copy_guard = enqueue_purge_prefix(db, user_key=user_key, reason="retell_copy_guard", prefix=f"images/retell/{new_book_id}/")
    await db.commit()
    copied_keys: list[str] = []
    new_character_reference = await _copy_retell_image(
        character_reference, new_book_id, "character-reference", copied_keys
    )
    new_cover_url = await _copy_retell_image(
        source.cover_image_url, new_book_id, "cover", copied_keys
    )
    new_page_urls: list[Optional[str]] = []
    for src_page in source_pages:
        new_page_urls.append(
            await _copy_retell_image(
                src_page.image_url, new_book_id, f"p{src_page.page_number}", copied_keys
            )
        )

    from src.services.photo_lifecycle import lock_photo_account

    await lock_photo_account(db, user_key)
    surviving_source = await db.scalar(select(Book.id).where(Book.id == book_id, Book.user_key == user_key))
    if surviving_source is None:
        raise NotFoundError("Book", book_id)
    if photo_derived:
        await require_photo_consent(db, user_key)
    cancel_purge_task(copy_guard)
    db.add(
        Job(
            id=new_job_id,
            status="done",
            user_key=user_key,
            profile_id=source.profile_id,
            idempotency_key=idempotency_key,  # H17/G19: 재시도 dedup 키
            photo_derived=photo_derived,
            character_reference_url=new_character_reference,
            character_reference_version=source_job.character_reference_version if source_job else None,
            # M12: 복제본 키를 잡에 기록 — 커밋 실패 시에도 파기가 도달할 수 있게.
            image_keys=copied_keys or None,
        )
    )
    await db.flush()

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
        cover_image_url=new_cover_url,
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
                image_url=new_page_urls[idx],
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
    (require_narration_supported if settings.audio_narration_only_enabled else require_audio_supported)()

    # Keep the source, current consent and admission in the same transaction
    # as withdrawal. The plan check below performs only a local database read.
    from src.services.photo_lifecycle import lock_photo_account
    from src.services.photo_book_references import existing_book_is_photo_derived

    await lock_photo_account(db, user_key)
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

    await require_parental_consent(db, user_key)
    # L5: fire-and-forget였던 배치 오디오를 audio_ Job 행으로 관측 가능하게 한다. 실패/타임아웃이
    # 잡 상태(done/failed)로 표면화되고 GET /v1/books/{job_id}로 폴링 가능(형제 regen/inpaint와 대칭).
    from src.core.generation_access import require_generation_access
    require_generation_access(user_key)
    photo_derived = await existing_book_is_photo_derived(db, book)
    if photo_derived:
        await require_photo_consent(db, user_key)
    audio_job_id = f"audio_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    audio_job = Job(
        id=audio_job_id,
        status="queued",
        progress=0,
        current_step="오디오 생성 대기 중",
        user_key=user_key,
        photo_derived=photo_derived,
        profile_id=book.profile_id,
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
    voice: str = Query(default="default", pattern="^(default|warm|deep)$"),
    style: str = Query(default="legacy", pattern="^(legacy|natural|animated|bedtime)$"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    특정 페이지 오디오 URL 조회

    - 이미 생성된 오디오 URL 반환
    - 없으면 즉시 생성 후 반환
    """
    return await _resolve_page_audio(book_id, page_number, language, voice, style, db, user_key, profile_id)


@router.get('/{book_id}/pages/{page_number}/audio/cached')
async def get_cached_page_audio(
    book_id: str,
    page_number: int,
    language: str = Query(default='ko', pattern='^(ko|en|ja|zh|es)$'),
    voice: str = Query(default='default', pattern='^(default|warm|deep)$'),
    style: str = Query(default='legacy', pattern='^(legacy|natural|animated|bedtime)$'),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
) -> dict[str, str | None]:
    """Look up existing narration without starting synthesis or spending credits."""
    return await _resolve_page_audio(book_id, page_number, language, voice, style, db, user_key, profile_id,
                                     cached_only=True)


async def _resolve_page_audio(book_id, page_number, language, voice, style, db, user_key, profile_id,
                              *, cached_only=False):
    # H1/G9: 오디오 비활성 배포에서는 provider 해석 실패 500 대신 명시적 미지원으로 차단.
    (require_narration_supported if settings.audio_narration_only_enabled else require_audio_supported)()

    # Keep the book row for existing 404/403 behavior without fetching a
    # different account or profile's page text into the request.
    result = await db.execute(
        select(Book, Page)
        .outerjoin(Page, and_(_owned_book_pages(user_key, profile_id), Page.page_number == page_number))
        .where(Book.id == book_id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Book", book_id)

    book, page = row
    if book.user_key != user_key:
        raise AuthorizationError()
    _assert_book_profile_scope(book, profile_id)
    if page is None:
        raise NotFoundError("Page", str(page_number))

    from src.services.tts import SUPPORTED_AUDIO_LANGUAGES

    if not isinstance(language, str):
        language = getattr(language, "default", "ko")
    if not isinstance(voice, str):
        voice = getattr(voice, "default", "default")
    if not isinstance(style, str):
        style = getattr(style, "default", "legacy")
    if style not in {"legacy", "natural", "animated", "bedtime"}:
        raise ValidationError("지원하지 않는 낭독 스타일입니다.")
    if voice not in {"default", "warm", "deep"}:
        raise ValidationError("지원하지 않는 낭독 목소리입니다.")
    language = language.lower().strip()
    book_language = str(getattr(book, "language", "") or "ko").lower().strip()

    # H3: 미지원 언어는 조용한 'ko' 강제(=한국어 보이스 오합성) 대신 명시 차단(fail-open 제거).
    if language not in SUPPORTED_AUDIO_LANGUAGES:
        raise ValidationError(
            f"오디오가 지원하지 않는 언어입니다: {language} "
            f"(지원: {', '.join(SUPPORTED_AUDIO_LANGUAGES)})"
        )

    from src.services.audio_text import audio_texts

    text_by_language = audio_texts(page.text, getattr(page, "text_ko", None),
                                   getattr(page, "text_en", None), book_language)
    if language not in text_by_language:
        raise ValidationError("요청한 언어의 본문이 아직 준비되지 않았습니다.")
    consent_id = await require_parental_consent(db, user_key)

    if voice != "default" or style != "legacy":
        from src.core.audio_feature import narration_voice_selection_supported, narration_style_selection_supported
        from src.services.audio_assets import variant_url
        if (voice != "default" and not narration_voice_selection_supported()) or (style != "legacy" and not narration_style_selection_supported()):
            raise ValidationError("이 환경에서는 낭독 목소리 선택을 지원하지 않습니다.")
        selected_url = await variant_url(db, page.id, language, voice, style, settings.tts_provider.strip().lower())
        if selected_url:
            return {"audio_url": media_url(selected_url)}

    # Existing narration remains readable without another synthesis charge.
    audio_url = None
    if voice == "default" and style == "legacy" and language == "en":
        audio_url = getattr(page, "audio_url_en", None)
    elif voice == "default" and style == "legacy" and language == "ko":
        audio_url = getattr(page, "audio_url_ko", None)
    if voice == "default" and style == "legacy" and language == book_language:
        audio_url = audio_url or getattr(page, "audio_url", None)
    if audio_url:
        return {"audio_url": media_url(audio_url)}
    if cached_only:
        return {"audio_url": None}

    # Preserve the 3–5 exception. Other ages can narrate books made with a spent credit.
    target_age = str(getattr(book, "target_age", "") or "").strip()
    if target_age != "3-5":
        await _enforce_free_plan_feature_access(
            db, user_key, "audio", narration_job_id=book.job_id,
        )

    # 없으면 즉시 생성
    try:
        from src.services.audio_assets import NarrationSource
        source = NarrationSource.from_page(book, page, consent_id=consent_id)
        source_text = text_by_language[language]
        from src.core.generation_access import require_generation_access
        require_generation_access(user_key)
        async def generate_audio():
            selected_provider = settings.tts_provider.strip().lower()
            voice_map = ({"warm": "Kore", "deep": "Puck"} if selected_provider == "google_gemini" else
                         {"warm": "coral", "deep": "cedar" if selected_provider == "openai_realtime" else "onyx"})
            voice_args = {} if voice == "default" else {"voice": voice_map[voice]}
            style_args = {} if style == "legacy" else {"style": style}
            from functools import partial
            from src.services.audio_assets import authorize_narration
            from src.services.generation_consent import provider_consent_scope

            authorize = partial(authorize_narration, source=source)
            with provider_consent_scope(authorize):
                audio_bytes = await tts_service.synthesize_page(
                    source_text, target_age=source.target_age, language=language, **voice_args, **style_args,
                )
            from src.services.audio_assets import publish_narration, publish_variant, store_narration
            url, guard = await store_narration(db, book_id, page_number, language, audio_bytes, user_key=user_key)
            if voice == "default" and style == "legacy":
                return await publish_narration(db, source, language, url, guard)
            return await publish_variant(db, source, language, voice, url, guard, style, settings.tts_provider.strip().lower())

        from src.services.audio_assets import narration_url, variant_singleflight, variant_url
        async with variant_singleflight(user_key, book_id, page_number, language, voice, style, settings.tts_provider.strip().lower()):
            # A request may have published or the page/consent may have changed
            # before this request acquired the shared lock.
            await require_parental_consent(db, user_key)
            current_page = await db.scalar(select(Page).where(
                Page.id == source.page_id, Page.book_id == book_id,
            ).execution_options(populate_existing=True))
            if not source.matches(current_page):
                raise ValidationError("페이지가 변경되었습니다. 다시 시도해 주세요.")
            if voice == "default" and style == "legacy":
                audio_url = narration_url(current_page, language, source.book_language)
            else:
                audio_url = await variant_url(db, page.id, language, voice, style, settings.tts_provider.strip().lower())
            if not audio_url:
                # The transport takes a fresh session when sending. Release this
                # read transaction before waiting for budget, network or model work.
                await db.commit()
                # Finish well before lock expiry; uncertain failures retain it.
                try:
                    audio_url = await asyncio.wait_for(generate_audio(), timeout=240)
                except asyncio.TimeoutError:
                    raise APIError(503, 'SERVICE_UNAVAILABLE', '음성 생성 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.') from None

        return {"audio_url": media_url(audio_url)}

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
        if isinstance(e, APIError):
            raise
        logger.error(
            "Audio generation failed", book_id=book_id, page_number=page_number, error=str(e)
        )
        raise InternalServerError(
            "오디오 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from e
