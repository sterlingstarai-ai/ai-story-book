from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional
import uuid
from datetime import datetime, timedelta
import structlog

from src.core.database import get_db
from src.core.config import settings
from src.core.dependencies import get_user_key
from src.models.dto import (
    BookSpec, CreateBookResponse, JobStatus, JobState,
    RegeneratePageRequest, RegeneratePageResponse,
    SeriesNextRequest, BookResult, PageResult
)
from src.models.db import Job, Book, Page
from src.services.orchestrator import start_book_generation, regenerate_page
from src.services.pdf import pdf_service
from src.services.tts import tts_service
from src.services.storage import storage_service
from src.services.credits import credits_service

logger = structlog.get_logger()

router = APIRouter()


def get_idempotency_key(x_idempotency_key: Optional[str] = Header(None)) -> Optional[str]:
    """Extract idempotency key from header"""
    return x_idempotency_key


async def check_guardrails(db: AsyncSession, user_key: str):
    """
    Check system guardrails before creating a new job.
    Raises HTTPException if guardrails are violated.
    """
    # Check daily job limit per user
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_jobs_result = await db.execute(
        select(func.count(Job.id)).where(
            and_(
                Job.user_key == user_key,
                Job.created_at >= today_start
            )
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
                "used": daily_job_count
            }
        )

    # Check total pending jobs in system
    pending_jobs_result = await db.execute(
        select(func.count(Job.id)).where(
            Job.status.in_(["queued", "running"])
        )
    )
    pending_count = pending_jobs_result.scalar() or 0

    if pending_count >= settings.max_pending_jobs:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "system_overloaded",
                "message": "시스템이 현재 많은 요청을 처리 중입니다. 잠시 후 다시 시도해주세요.",
                "retry_after": 60
            }
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

    # Check credits
    has_credits = await credits_service.has_credits(db, user_key, required=1)
    if not has_credits:
        raise HTTPException(
            status_code=402,
            detail="크레딧이 부족합니다. 크레딧을 충전해주세요."
        )

    # Check idempotency
    if idempotency_key:
        result = await db.execute(
            select(Job).where(
                Job.idempotency_key == idempotency_key,
                Job.user_key == user_key
            )
        )
        existing_job = result.scalar_one_or_none()
        if existing_job:
            return CreateBookResponse(
                job_id=existing_job.id,
                status=JobState(existing_job.status),
                estimated_time_seconds=120
            )

    # Create new job
    job_id = f"job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    job = Job(
        id=job_id,
        status="queued",
        progress=0,
        current_step="대기 중",
        user_key=user_key,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    await db.commit()

    # Deduct credit
    credit_used = await credits_service.use_credit(
        db, user_key, amount=1,
        description="책 생성",
        reference_id=job_id
    )
    if not credit_used:
        # Rollback job if credit deduction fails
        await db.delete(job)
        await db.commit()
        raise HTTPException(
            status_code=402,
            detail="크레딧 차감에 실패했습니다."
        )

    # Start background task (Celery or FastAPI BackgroundTasks)
    if settings.use_celery:
        from src.services.tasks import generate_book_task
        generate_book_task.delay(job_id, spec.model_dump(), user_key)
    else:
        background_tasks.add_task(start_book_generation, job_id, spec, user_key)

    return CreateBookResponse(
        job_id=job_id,
        status=JobState.queued,
        estimated_time_seconds=120
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
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    # Build response
    response = JobStatus(
        job_id=job.id,
        status=JobState(job.status),
        progress=job.progress,
        current_step=job.current_step,
        error=None,
        result=None
    )

    # Add error info if failed
    if job.status == "failed" and job.error_code:
        from src.models.dto import ErrorInfo, ErrorCode
        response.error = ErrorInfo(
            code=ErrorCode(job.error_code),
            message=job.error_message or "Unknown error"
        )

    # Add result if done
    if job.status == "done":
        # Fetch book with pages
        book_result = await db.execute(
            select(Book).where(Book.job_id == job_id)
        )
        book = book_result.scalar_one_or_none()

        if book:
            # Build BookResult dict
            pages_result = await db.execute(
                select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
            )
            pages = pages_result.scalars().all()

            response.result = {
                "book_id": book.id,
                "title": book.title,
                "language": book.language,
                "target_age": book.target_age,
                "style": book.style,
                "cover_image_url": book.cover_image_url,
                "pages": [
                    {
                        "page_number": p.page_number,
                        "text": p.text,
                        "image_url": p.image_url,
                        "image_prompt": p.image_prompt,
                        "audio_url": p.audio_url
                    }
                    for p in pages
                ],
                "created_at": book.created_at.isoformat()
            }

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
    result = await db.execute(
        select(Book).where(Book.id == book_id)
    )
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch pages
    pages_result = await db.execute(
        select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
    )
    pages = pages_result.scalars().all()

    return {
        "book_id": book.id,
        "title": book.title,
        "language": book.language,
        "target_age": book.target_age,
        "style": book.style,
        "theme": book.theme,
        "character_id": book.character_id,
        "cover_image_url": book.cover_image_url or "",
        "pdf_url": book.pdf_url,
        "audio_url": book.audio_url,
        "pages": [
            {
                "page_number": p.page_number,
                "text": p.text,
                "image_url": p.image_url or "",
                "image_prompt": p.image_prompt,
                "audio_url": p.audio_url
            }
            for p in pages
        ],
        "created_at": book.created_at.isoformat()
    }


@router.post("/{job_id}/pages/{page_number}/regenerate", response_model=RegeneratePageResponse)
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
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    if job.status != "done":
        raise HTTPException(status_code=400, detail="Book generation not complete")

    # Verify page exists
    book_result = await db.execute(
        select(Book).where(Book.job_id == job_id)
    )
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    page_result = await db.execute(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise HTTPException(status_code=404, detail=f"Page {page_number} not found")

    # Create regeneration task
    regen_job_id = f"regen_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    background_tasks.add_task(
        regenerate_page,
        regen_job_id,
        book.id,
        page_number,
        request.mode,
        request.feedback
    )

    return RegeneratePageResponse(
        job_id=regen_job_id,
        status=JobState.queued
    )


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
    - previous_book_id의 요약을 참고하여 연속성 유지
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
        raise HTTPException(status_code=404, detail="Character not found")

    if character.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied to character")

    # Verify previous book exists
    book_result = await db.execute(
        select(Book).where(Book.id == request.previous_book_id)
    )
    prev_book = book_result.scalar_one_or_none()

    if not prev_book:
        raise HTTPException(status_code=404, detail="Previous book not found")

    # Check and deduct credits
    has_credits = await credits_service.has_credits(db, user_key, required=1)
    if not has_credits:
        raise HTTPException(
            status_code=402,
            detail="크레딧이 부족합니다. 크레딧을 충전해주세요."
        )

    # Create new job for series
    job_id = f"series_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    job = Job(
        id=job_id,
        status="queued",
        progress=0,
        current_step="시리즈 생성 대기 중",
        user_key=user_key,
    )
    db.add(job)
    await db.commit()

    # Deduct credit
    await credits_service.use_credit(
        db, user_key, amount=1,
        description="시리즈 생성",
        reference_id=job_id
    )

    # Start background task for series generation
    from src.services.orchestrator import start_series_generation
    background_tasks.add_task(
        start_series_generation,
        job_id,
        request,
        user_key,
        character,
        prev_book
    )

    return CreateBookResponse(
        job_id=job_id,
        status=JobState.queued,
        estimated_time_seconds=120
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
    book_result = await db.execute(
        select(Book).where(Book.id == book_id)
    )
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

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
                audio_url=p.audio_url
            )
            for p in pages
        ],
        created_at=book.created_at
    )

    # Generate PDF
    try:
        pdf_bytes = await pdf_service.generate_pdf(book_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    # Return PDF as response
    filename = f"{book.title.replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
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
    book_result = await db.execute(
        select(Book).where(Book.id == book_id)
    )
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch pages
    pages_result = await db.execute(
        select(Page).where(Page.book_id == book.id).order_by(Page.page_number)
    )
    pages = pages_result.scalars().all()

    if not pages:
        raise HTTPException(status_code=404, detail="No pages found")

    # Start background task for audio generation
    background_tasks.add_task(
        _generate_audio_for_book,
        book_id,
        [{"page_number": p.page_number, "text": p.text, "page_id": p.id} for p in pages],
    )

    return {"status": "processing", "message": "오디오 생성이 시작되었습니다."}


async def _generate_audio_for_book(book_id: str, pages: list[dict]):
    """책 오디오 생성 백그라운드 태스크"""
    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        for page_data in pages:
            try:
                # TTS 생성
                audio_bytes = await tts_service.synthesize_page(page_data["text"])

                # S3에 업로드
                audio_key = f"books/{book_id}/audio/page_{page_data['page_number']}.mp3"
                audio_url = await storage_service.upload_bytes(
                    audio_bytes,
                    audio_key,
                    content_type="audio/mpeg"
                )

                # DB 업데이트
                page_result = await db.execute(
                    select(Page).where(Page.id == page_data["page_id"])
                )
                page = page_result.scalar_one_or_none()
                if page:
                    page.audio_url = audio_url
                    await db.commit()

            except Exception as e:
                logger.warning(
                    "Audio generation failed for page",
                    page_number=page_data['page_number'],
                    error=str(e),
                )
                continue


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
    book_result = await db.execute(
        select(Book).where(Book.id == book_id)
    )
    book = book_result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch page
    page_result = await db.execute(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise HTTPException(status_code=404, detail=f"Page {page_number} not found")

    # 이미 오디오가 있으면 반환
    if page.audio_url:
        return {"audio_url": page.audio_url}

    # 없으면 즉시 생성
    try:
        audio_bytes = await tts_service.synthesize_page(page.text)

        # S3에 업로드
        audio_key = f"books/{book_id}/audio/page_{page_number}.mp3"
        audio_url = await storage_service.upload_bytes(
            audio_bytes,
            audio_key,
            content_type="audio/mpeg"
        )

        # DB 업데이트
        page.audio_url = audio_url
        await db.commit()

        return {"audio_url": audio_url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio generation failed: {str(e)}")
