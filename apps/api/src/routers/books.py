from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional
import uuid
import structlog

from src.core.database import get_db
from src.core.config import settings
from src.core.dependencies import get_user_key
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
from src.models.db import Job, Book, Page
from src.services.orchestrator import start_book_generation, regenerate_page
from src.services.pdf import pdf_service
from src.services.tts import tts_service
from src.services.storage import storage_service
from src.services.credits import credits_service
from src.core.utils import utcnow
from src.core.exceptions import (
    AuthorizationError,
    NotFoundError,
    PaymentRequiredError,
)

logger = structlog.get_logger()

router = APIRouter()


def _build_page_dict(p) -> dict:
    """Build standardized page response dict from a Page model."""
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
    }


def _build_book_dict(book, pages, include_job_id: bool = False) -> dict:
    """Build standardized book response dict from Book + Pages models."""
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
        "created_at": book.created_at.isoformat(),
    }
    if include_job_id:
        result["job_id"] = book.job_id
        result["theme"] = book.theme
        result["character_id"] = book.character_id
        result["pdf_url"] = book.pdf_url
        result["audio_url"] = book.audio_url
    return result


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
        raise HTTPException(
            status_code=500,
            detail="잡 생성에 실패했습니다. 크레딧이 환불되었습니다.",
        ) from e


async def check_guardrails(db: AsyncSession, user_key: str):
    """
    Check system guardrails before creating a new job.
    Raises HTTPException if guardrails are violated.
    """
    # Check daily job limit per user
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_jobs_result = await db.execute(
        select(func.count(Job.id)).where(
            and_(Job.user_key == user_key, Job.created_at >= today_start)
        )
    )
    daily_job_count = daily_jobs_result.scalar() or 0

    if daily_job_count >= settings.daily_job_limit_per_user:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_limit_exceeded",
                "message": f"일일 생성 한도({settings.daily_job_limit_per_user}권)를 초과했습니다. 내일 다시 시도해주세요.",
                "limit": settings.daily_job_limit_per_user,
                "used": daily_job_count,
            },
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
        )


@router.post("", response_model=CreateBookResponse)
async def create_book(
    spec: BookSpec,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
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

    # Check idempotency
    if idempotency_key:
        result = await db.execute(
            select(Job).where(
                Job.idempotency_key == idempotency_key, Job.user_key == user_key
            )
        )
        existing_job = result.scalar_one_or_none()
        if existing_job:
            return CreateBookResponse(
                job_id=existing_job.id,
                status=JobState(existing_job.status),
                estimated_time_seconds=120,
            )

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
    )

    # Start background task (Celery or FastAPI BackgroundTasks)
    # 테스트 환경에서는 background_tasks 실행 스킵 (테스트 안정화)
    if settings.testing:
        logger.info(
            "Skipping book generation background task in testing mode", job_id=job_id
        )
    elif settings.use_celery:
        from src.services.tasks import generate_book_task

        generate_book_task.delay(job_id, spec.model_dump(), user_key)
    else:
        background_tasks.add_task(start_book_generation, job_id, spec, user_key)

    return CreateBookResponse(
        job_id=job_id, status=JobState.queued, estimated_time_seconds=120
    )


@router.get("/{job_id}", response_model=JobStatus)
async def get_book_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
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

        response.error = ErrorInfo(
            code=ErrorCode(job.error_code), message=job.error_message or "Unknown error"
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
            response.result = _build_book_dict(book, pages)

    return response


@router.get("/{book_id}/detail")
async def get_book_detail(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
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

    if job.status != "done":
        raise HTTPException(status_code=400, detail="Book generation not complete")

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

    background_tasks.add_task(
        regenerate_page,
        regen_job_id,
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
):
    """
    시리즈 다음 권 생성

    - 같은 캐릭터로 새로운 이야기 생성
    - previous_book_id가 있으면 연속성 유지, 없으면 topic 기반 생성
    """
    # Check guardrails (daily limit, system load)
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

    # Create new job for series
    job_id = f"series_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="시리즈 생성 대기 중",
        credit_description="시리즈 생성",
        refund_description="시리즈 잡 생성 실패 환불",
    )

    # Start background task for series generation
    # 테스트 환경에서는 background_tasks 실행 스킵 (테스트 안정화)
    from src.services.orchestrator import start_series_generation

    if settings.testing:
        logger.info("Skipping series background task in testing mode", job_id=job_id)
    else:
        background_tasks.add_task(
            start_series_generation, job_id, request, user_key, character, prev_book
        )

    return CreateBookResponse(
        job_id=job_id, status=JobState.queued, estimated_time_seconds=120
    )


@router.get("/{book_id}/pdf")
async def export_book_pdf(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
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
            )
            for p in pages
        ],
        created_at=book.created_at,
    )

    # Generate PDF
    try:
        pdf_bytes = await pdf_service.generate_pdf(book_data)
    except Exception as e:
        logger.error("PDF generation failed", book_id=book_id, error=str(e))
        raise HTTPException(
            status_code=500, detail="PDF 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        )

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
            {"page_number": p.page_number, "text": p.text, "page_id": p.id}
            for p in pages
        ],
    )

    return {"status": "processing", "message": "오디오 생성이 시작되었습니다."}


async def _generate_audio_for_book(book_id: str, pages: list[dict]):
    """책 오디오 생성 백그라운드 태스크 (5분 타임아웃)"""
    import asyncio

    try:
        await asyncio.wait_for(_generate_audio_pages(book_id, pages), timeout=300)
    except asyncio.TimeoutError:
        logger.error("Audio generation timed out", book_id=book_id, total_pages=len(pages))


async def _generate_audio_pages(book_id: str, pages: list[dict]):
    """실제 오디오 생성 로직 (페이지별 상태 추적)"""
    from src.core.database import AsyncSessionLocal

    succeeded = 0
    failed_pages = []

    async with AsyncSessionLocal() as db:
        for page_data in pages:
            try:
                audio_bytes = await tts_service.synthesize_page(page_data["text"])

                audio_key = f"books/{book_id}/audio/page_{page_data['page_number']}.mp3"
                audio_url = await storage_service.upload_bytes(
                    audio_bytes, audio_key, content_type="audio/mpeg"
                )

                page_result = await db.execute(
                    select(Page).where(Page.id == page_data["page_id"])
                )
                page = page_result.scalar_one_or_none()
                if page:
                    page.audio_url = audio_url
                    await db.commit()
                    succeeded += 1

            except Exception as e:
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
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
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

    # Fetch page
    page_result = await db.execute(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise NotFoundError("Page", str(page_number))

    # 이미 오디오가 있으면 반환
    if page.audio_url:
        return {"audio_url": page.audio_url}

    # 없으면 즉시 생성
    try:
        audio_bytes = await tts_service.synthesize_page(page.text)

        # S3에 업로드
        audio_key = f"books/{book_id}/audio/page_{page_number}.mp3"
        audio_url = await storage_service.upload_bytes(
            audio_bytes, audio_key, content_type="audio/mpeg"
        )

        # DB 업데이트
        page.audio_url = audio_url
        await db.commit()

        return {"audio_url": audio_url}

    except Exception as e:
        logger.error(
            "Audio generation failed", book_id=book_id, page_number=page_number, error=str(e)
        )
        raise HTTPException(
            status_code=500, detail="오디오 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        )
