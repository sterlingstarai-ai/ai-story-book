"""장기 실행 잡의 **정본 러너** — 페이지 재생성 / 인페인트 / 오디오 생성.

R1: 이 함수들은 원래 `routers/books.py`에 있었고 항상 FastAPI BackgroundTasks로만
실행됐다. `USE_CELERY=true`여도 API 프로세스가 직접 돌았다는 뜻이라, books.py:1114가
이미 경고한 문제("API 프로세스 in-process 실행 시 재시작 유실·API 지연")를 재생성·
인페인트·오디오가 그대로 안고 있었다.

여기로 옮긴 이유는 **로직 이중화 금지**다. 라우터 폴백 경로(BackgroundTasks)와 Celery
태스크가 동일한 함수를 import 한다. tasks.py가 routers를 import 하면 순환이 생기므로
서비스 계층이 정본의 자리다.

인자는 전부 원시 타입(str/int/list[dict])이라 Celery 직렬화가 가능하다 — ORM 객체를
넘기지 않는다(generate_series_task와 동일 원칙).
"""

from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from sqlalchemy import select

from src.core.errors import ErrorCode, StoryBookError, client_safe_message
from src.core.utils import utcnow
from src.models.db import Job, Page
from src.services.orchestrator import inpaint_page, regenerate_page
from src.services.storage import storage_service
from src.services.tts import tts_service

logger = structlog.get_logger()


async def set_regen_job_status(
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


async def run_regeneration_job(
    regen_job_id: str,
    original_job_id: str,
    book_id: str,
    page_number: int,
    mode: str,
    feedback: Optional[str],
) -> None:
    """Execute regeneration and persist status transitions for polling."""
    await set_regen_job_status(
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
        # M12: SafetyError 등 도메인 에러 코드(SAFETY_INPUT/OUTPUT)를 UNKNOWN으로 뭉개지 않는다.
        error_code = (
            e.code.value if isinstance(e, StoryBookError) else ErrorCode.UNKNOWN.value
        )
        await set_regen_job_status(
            regen_job_id,
            status="failed",
            progress=100,
            current_step="재생성 실패",
            error_code=error_code,
            error_message=client_safe_message(
                error_code, str(getattr(e, "message", e))
            )[:300],
        )
        logger.error(
            "Regeneration job failed",
            regen_job_id=regen_job_id,
            original_job_id=original_job_id,
            page_number=page_number,
            error=str(e),
        )
        return

    await set_regen_job_status(
        regen_job_id,
        status="done",
        progress=100,
        current_step="완료",
    )


async def run_inpaint_job(
    inpaint_job_id: str,
    original_job_id: str,
    book_id: str,
    page_number: int,
    mask_url: str,
    region_prompt: str,
) -> None:
    """인페인트(부분 재생성) 백그라운드 실행 + 폴링용 상태 전이."""
    await set_regen_job_status(
        inpaint_job_id,
        status="running",
        progress=20,
        current_step="부분 재생성 중...",
    )
    try:
        await inpaint_page(
            job_id=original_job_id,
            book_id=book_id,
            page_number=page_number,
            mask_url=mask_url,
            region_prompt=region_prompt,
        )
    except Exception as e:
        # M12: 도메인 에러 코드(SAFETY_INPUT 등)를 보존.
        error_code = (
            e.code.value if isinstance(e, StoryBookError) else ErrorCode.UNKNOWN.value
        )
        await set_regen_job_status(
            inpaint_job_id,
            status="failed",
            progress=100,
            current_step="부분 재생성 실패",
            error_code=error_code,
            error_message=client_safe_message(
                error_code, str(getattr(e, "message", e))
            )[:300],
        )
        logger.error(
            "Inpaint job failed",
            inpaint_job_id=inpaint_job_id,
            original_job_id=original_job_id,
            page_number=page_number,
            error=str(e),
        )
        return

    await set_regen_job_status(
        inpaint_job_id,
        status="done",
        progress=100,
        current_step="완료",
    )


async def run_audio_job(
    book_id: str,
    pages: list[dict],
    target_age: str,
    default_language: str,
    audio_job_id: Optional[str] = None,
):
    """책 오디오 생성 백그라운드 태스크 (5분 타임아웃).

    L5: 결과를 audio_ Job 상태로 표면화 — 타임아웃/전체 실패는 failed(에러코드 포함),
    부분/전체 성공은 done. audio_job_id가 없으면(구 호출 경로) 로그만 남긴다.
    """
    try:
        succeeded, failed_pages = await asyncio.wait_for(
            generate_audio_pages(
                book_id=book_id,
                pages=pages,
                target_age=target_age,
                default_language=default_language,
            ),
            timeout=300,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Audio generation timed out", book_id=book_id, total_pages=len(pages)
        )
        if audio_job_id:
            await set_regen_job_status(
                audio_job_id,
                status="failed",
                progress=100,
                current_step="오디오 생성 타임아웃",
                error_code="AUDIO_TIMEOUT",
                error_message="오디오 생성이 시간 내에 완료되지 않았습니다.",
            )
        return
    except Exception as e:
        logger.error("Audio generation failed", book_id=book_id, error=str(e))
        if audio_job_id:
            await set_regen_job_status(
                audio_job_id,
                status="failed",
                progress=100,
                current_step="오디오 생성 실패",
                error_code="AUDIO_FAILED",
                error_message=str(e),
            )
        return

    if not audio_job_id:
        return
    if succeeded == 0 and failed_pages:
        await set_regen_job_status(
            audio_job_id,
            status="failed",
            progress=100,
            current_step="오디오 생성 실패",
            error_code="AUDIO_FAILED",
            error_message=f"모든 페이지 오디오 생성 실패(pages={failed_pages})",
        )
    else:
        step = (
            "오디오 생성 완료"
            if not failed_pages
            else f"오디오 부분 생성(실패 페이지: {failed_pages})"
        )
        await set_regen_job_status(
            audio_job_id,
            status="done",
            progress=100,
            current_step=step,
        )


async def generate_audio_pages(
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
                # H3: 책 언어 기반 오디오 생성. ko/en 이중 텍스트는 각 슬롯에, 그 외
                # 스토리 언어(ja/zh/es)는 책 언어 보이스로 1건 생성해 기본 슬롯(audio_url)에
                # 저장한다(MA5: 한국어 슬롯 교차 오염·매 요청 재합성 방지).
                generated_urls = {}
                base_lang = (default_language or "ko").lower().strip()
                if base_lang in ("ko", "en"):
                    text_by_language = {
                        "ko": page_data.get("text_ko") or page_data.get("text"),
                        "en": page_data.get("text_en"),
                    }
                    languages = ("ko", "en")
                else:
                    text_by_language = {
                        base_lang: page_data.get("text") or page_data.get("text_ko"),
                    }
                    languages = (base_lang,)

                for language in languages:
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
                    # 기본 슬롯: 책 언어 오디오 우선(비 ko/en 언어는 여기에만 저장됨).
                    if base_lang in generated_urls:
                        page.audio_url = generated_urls[base_lang]
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

    # L5: 호출자(run_audio_job)가 잡 상태(done/failed)를 결정할 수 있도록 결과 반환.
    return succeeded, failed_pages
