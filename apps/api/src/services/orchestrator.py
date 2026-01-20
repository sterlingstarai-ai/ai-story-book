"""
오케스트레이터: 동화책 생성 파이프라인 관리

파이프라인 단계:
A. 입력 정규화 (BookSpec 확정)
B. 입력 안전성 검사 (ModerationResult)
C. 스토리 생성 (LLM → StoryDraft)
D. 캐릭터 시트 생성 (LLM → CharacterSheet)
E. 이미지 프롬프트 생성 (LLM → ImagePrompts)
F. 이미지 생성 (cover + pages 병렬)
G. 출력 안전성 검사
H. 패키징 (BookResult 생성, 업로드, 저장)
"""

import asyncio
from typing import Optional, Callable, Awaitable, TypeVar
from datetime import datetime
import uuid
import structlog

from src.core.config import settings
from src.core.errors import (
    StoryBookError, ErrorCode, TransientError,
    get_backoff
)
from src.models.dto import (
    BookSpec, StoryDraft, CharacterSheet, ImagePrompts,
    ModerationResult, BookResult, SeriesNextRequest
)

logger = structlog.get_logger()

T = TypeVar("T")


# ==================== Progress Constants ====================

PROGRESS_NORMALIZE = 5
PROGRESS_MODERATE_INPUT = 10
PROGRESS_STORY = 30
PROGRESS_CHARACTER = 40
PROGRESS_IMAGE_PROMPTS = 55
PROGRESS_IMAGES_START = 55
PROGRESS_IMAGES_END = 95
PROGRESS_PACKAGE = 100


# ==================== Step Runner ====================

async def run_step(
    job_id: str,
    step_name: str,
    progress: int,
    fn: Callable[[], Awaitable[T]],
    retries: int = 0,
    timeout_sec: int = 30,
    backoff: list[int] = None,
) -> T:
    """
    단계 실행 + 재시도 래퍼

    Args:
        job_id: 잡 ID
        step_name: 단계 이름 (로깅/상태 업데이트용)
        progress: 현재 진행률
        fn: 실행할 비동기 함수
        retries: 재시도 횟수
        timeout_sec: 타임아웃 (초)
        backoff: 재시도 간격 리스트

    Returns:
        fn의 결과

    Raises:
        StoryBookError: 최종 실패 시
    """
    backoff = backoff or [2, 5, 12]

    await update_job_status(job_id, step_name, progress)

    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            result = await asyncio.wait_for(fn(), timeout=timeout_sec)
            logger.info(
                "Step completed",
                job_id=job_id,
                step=step_name,
                attempt=attempt + 1
            )
            return result

        except asyncio.TimeoutError as e:
            last_exc = e
            logger.warning(
                "Step timeout",
                job_id=job_id,
                step=step_name,
                attempt=attempt + 1,
                timeout=timeout_sec
            )

        except TransientError as e:
            last_exc = e
            logger.warning(
                "Transient error",
                job_id=job_id,
                step=step_name,
                attempt=attempt + 1,
                error=str(e)
            )

        except StoryBookError:
            # 비일시적 오류는 즉시 중단
            raise

        except Exception as e:
            last_exc = e
            logger.error(
                "Unexpected error",
                job_id=job_id,
                step=step_name,
                attempt=attempt + 1,
                error=str(e)
            )

        # 재시도 대기
        if attempt < retries:
            wait_time = backoff[min(attempt, len(backoff) - 1)]
            logger.info(f"Waiting {wait_time}s before retry...")
            await asyncio.sleep(wait_time)

    # 최종 실패
    raise last_exc if last_exc else RuntimeError(f"Step {step_name} failed")


# ==================== Database Helpers ====================

async def update_job_status(job_id: str, step: str, progress: int):
    """잡 상태 업데이트"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Job

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if job:
            job.current_step = step
            job.progress = progress
            job.status = "running"
            job.updated_at = datetime.utcnow()
            await session.commit()


async def mark_job_failed(job_id: str, error_code: ErrorCode, message: str):
    """잡 실패 처리"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Job

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if job:
            job.status = "failed"
            job.error_code = error_code.value
            job.error_message = message
            job.updated_at = datetime.utcnow()
            await session.commit()

    logger.error("Job failed", job_id=job_id, error_code=error_code, message=message)


async def mark_job_done(job_id: str):
    """잡 완료 처리"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Job

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if job:
            job.status = "done"
            job.progress = 100
            job.current_step = "완료"
            job.updated_at = datetime.utcnow()
            await session.commit()

    logger.info("Job completed", job_id=job_id)


# ==================== Main Orchestrator ====================

async def start_book_generation(job_id: str, spec: BookSpec, user_key: str):
    """
    동화책 생성 메인 파이프라인

    비동기 백그라운드 태스크로 실행됨
    """
    try:
        logger.info("Starting book generation", job_id=job_id, topic=spec.topic)

        # A. 입력 정규화
        normalized_spec = await run_step(
            job_id=job_id,
            step_name="입력 확인 중...",
            progress=PROGRESS_NORMALIZE,
            fn=lambda: normalize_input(spec),
            retries=0,
            timeout_sec=5,
        )

        # B. 입력 안전성 검사
        moderation = await run_step(
            job_id=job_id,
            step_name="안전성 검사 중...",
            progress=PROGRESS_MODERATE_INPUT,
            fn=lambda: moderate_input(normalized_spec),
            retries=0,
            timeout_sec=settings.llm_timeout,
        )

        if not moderation.is_safe:
            from src.core.errors import SafetyError
            raise SafetyError(
                message=f"입력이 안전하지 않습니다: {', '.join(moderation.reasons)}",
                is_input=True,
                suggestions=moderation.suggestions
            )

        # C. 스토리 생성
        story_draft = await run_step(
            job_id=job_id,
            step_name="이야기 쓰는 중...",
            progress=PROGRESS_STORY,
            fn=lambda: generate_story(normalized_spec),
            retries=2,
            timeout_sec=settings.llm_timeout,
            backoff=[2, 5],
        )

        # 스토리 저장
        await save_story_draft(job_id, story_draft)

        # D. 캐릭터 시트 생성
        character_sheet = await run_step(
            job_id=job_id,
            step_name="캐릭터 만드는 중...",
            progress=PROGRESS_CHARACTER,
            fn=lambda: generate_character_sheet(normalized_spec, story_draft),
            retries=1,
            timeout_sec=settings.llm_timeout,
            backoff=[2],
        )

        # E. 이미지 프롬프트 생성
        image_prompts = await run_step(
            job_id=job_id,
            step_name="그림 준비 중...",
            progress=PROGRESS_IMAGE_PROMPTS,
            fn=lambda: generate_image_prompts(normalized_spec, story_draft, character_sheet),
            retries=1,
            timeout_sec=settings.llm_timeout,
            backoff=[2],
        )

        # 이미지 프롬프트 저장
        await save_image_prompts(job_id, image_prompts)

        # F. 이미지 생성 (cover + pages)
        total_images = len(image_prompts.pages) + 1  # +1 for cover
        image_urls = await generate_all_images(
            job_id=job_id,
            image_prompts=image_prompts,
            total_images=total_images,
        )

        # G. 출력 안전성 검사 (이미지)
        await run_step(
            job_id=job_id,
            step_name="결과 확인 중...",
            progress=95,
            fn=lambda: moderate_output(story_draft, image_urls),
            retries=0,
            timeout_sec=10,
        )

        # H. 패키징 및 저장
        book_result = await run_step(
            job_id=job_id,
            step_name="마무리 중...",
            progress=98,
            fn=lambda: package_book(
                job_id, user_key, normalized_spec, story_draft,
                character_sheet, image_prompts, image_urls
            ),
            retries=1,
            timeout_sec=30,
        )

        # 완료
        await mark_job_done(job_id)
        logger.info("Book generation completed", job_id=job_id, book_id=book_result.book_id)

    except StoryBookError as e:
        await mark_job_failed(job_id, e.code, e.message)

    except Exception as e:
        logger.exception("Unexpected error in book generation", job_id=job_id)
        await mark_job_failed(job_id, ErrorCode.UNKNOWN, str(e))


# ==================== Pipeline Steps (Stubs) ====================

async def normalize_input(spec: BookSpec) -> BookSpec:
    """A. 입력 정규화"""
    # 기본값 적용, 검증 등
    return spec


async def moderate_input(spec: BookSpec) -> ModerationResult:
    """B. 입력 안전성 검사"""
    from src.services.llm import call_moderation
    return await call_moderation(spec)


async def generate_story(spec: BookSpec) -> StoryDraft:
    """C. 스토리 생성"""
    from src.services.llm import call_story_generation
    return await call_story_generation(spec)


async def generate_character_sheet(spec: BookSpec, story: StoryDraft) -> CharacterSheet:
    """D. 캐릭터 시트 생성"""
    from src.services.llm import call_character_sheet_generation
    return await call_character_sheet_generation(spec, story)


async def generate_image_prompts(
    spec: BookSpec,
    story: StoryDraft,
    character: CharacterSheet
) -> ImagePrompts:
    """E. 이미지 프롬프트 생성"""
    from src.services.llm import call_image_prompts_generation
    return await call_image_prompts_generation(spec, story, character)


async def generate_all_images(
    job_id: str,
    image_prompts: ImagePrompts,
    total_images: int,
) -> dict[int, str]:
    """
    F. 이미지 생성 (cover + pages)

    Returns:
        dict mapping page number to image URL (0 = cover)
    """

    image_urls = {}

    # Cover (page 0)
    progress_per_image = (PROGRESS_IMAGES_END - PROGRESS_IMAGES_START) / total_images
    current_progress = PROGRESS_IMAGES_START

    # Generate cover
    await update_job_status(job_id, "표지 그리는 중...", int(current_progress))
    cover_url = await generate_image_with_retry(image_prompts.cover, job_id, 0)
    image_urls[0] = cover_url
    current_progress += progress_per_image

    # Generate pages (with concurrency limit)
    semaphore = asyncio.Semaphore(settings.image_max_concurrent)

    async def generate_with_semaphore(prompt, page_num):
        async with semaphore:
            await update_job_status(
                job_id,
                f"그림 그리는 중... ({page_num}/{len(image_prompts.pages)})",
                int(current_progress + (page_num * progress_per_image))
            )
            return await generate_image_with_retry(prompt, job_id, page_num)

    tasks = [
        generate_with_semaphore(prompt, prompt.page)
        for prompt in image_prompts.pages
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for prompt, result in zip(image_prompts.pages, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to generate image for page {prompt.page}", error=str(result))
            # Use placeholder
            image_urls[prompt.page] = "https://placeholder.com/failed.png"
        else:
            image_urls[prompt.page] = result

    return image_urls


async def generate_image_with_retry(prompt, job_id: str, page: int) -> str:
    """이미지 생성 (재시도 포함)"""
    from src.services.image import generate_image

    max_retries = settings.image_max_retries
    for attempt in range(max_retries):
        try:
            url = await asyncio.wait_for(
                generate_image(prompt),
                timeout=settings.image_timeout
            )
            return url

        except asyncio.TimeoutError:
            logger.warning(f"Image generation timeout for page {page}, attempt {attempt + 1}")
            if attempt < max_retries - 1:
                await asyncio.sleep(get_backoff(ErrorCode.IMAGE_TIMEOUT, attempt))

        except Exception as e:
            logger.warning(f"Image generation failed for page {page}: {e}, attempt {attempt + 1}")
            if attempt < max_retries - 1:
                await asyncio.sleep(get_backoff(ErrorCode.IMAGE_FAILED, attempt))

    # 실패 시 placeholder
    return "https://placeholder.com/failed.png"


async def moderate_output(story: StoryDraft, image_urls: dict) -> bool:
    """G. 출력 안전성 검사 - 생성된 콘텐츠 검증"""
    # 금지 키워드 목록 (아동 부적절 콘텐츠)
    forbidden_patterns = [
        "죽이", "살인", "폭력", "피", "술", "담배", "마약",
        "성인", "섹스", "야한", "총", "칼로 찔",
        "kill", "murder", "blood", "sex", "drug", "alcohol",
        "violence", "weapon", "gun", "knife",
    ]

    # 모든 페이지 텍스트 검사
    all_text = story.title.lower()
    for page in story.pages:
        all_text += " " + page.text.lower()

    for pattern in forbidden_patterns:
        if pattern.lower() in all_text:
            logger.warning(
                "Output moderation failed",
                pattern=pattern,
                title=story.title,
            )
            return False

    return True


async def package_book(
    job_id: str,
    user_key: str,
    spec: BookSpec,
    story: StoryDraft,
    character: CharacterSheet,
    image_prompts: ImagePrompts,
    image_urls: dict,
) -> BookResult:
    """H. 패키징 및 저장"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Page
    from datetime import datetime

    book_id = f"book_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as session:
        # Create book
        book = Book(
            id=book_id,
            job_id=job_id,
            title=story.title,
            language=story.language.value,
            target_age=story.target_age.value,
            style=spec.style.value,
            theme=story.theme,
            character_id=spec.character_id,
            cover_image_url=image_urls.get(0, ""),
            user_key=user_key,
        )
        session.add(book)

        # Create pages
        for page_data in story.pages:
            page = Page(
                book_id=book_id,
                page_number=page_data.page,
                text=page_data.text,
                image_url=image_urls.get(page_data.page, ""),
                image_prompt=next(
                    (p.positive_prompt for p in image_prompts.pages if p.page == page_data.page),
                    ""
                ),
            )
            session.add(page)

        await session.commit()

    return BookResult(
        book_id=book_id,
        title=story.title,
        language=story.language,
        target_age=story.target_age,
        style=spec.style.value,
        cover_image_url=image_urls.get(0, ""),
        pages=[
            {
                "page_number": p.page,
                "text": p.text,
                "image_url": image_urls.get(p.page, ""),
                "image_prompt": next(
                    (ip.positive_prompt for ip in image_prompts.pages if ip.page == p.page),
                    ""
                ),
                "audio_url": None
            }
            for p in story.pages
        ],
        character_sheet=character,
        created_at=datetime.utcnow()
    )


async def save_story_draft(job_id: str, story: StoryDraft):
    """스토리 초안 저장"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import StoryDraftDB

    async with AsyncSessionLocal() as session:
        draft = StoryDraftDB(
            job_id=job_id,
            draft=story.model_dump()
        )
        session.add(draft)
        await session.commit()


async def save_image_prompts(job_id: str, prompts: ImagePrompts):
    """이미지 프롬프트 저장"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import ImagePromptsDB

    async with AsyncSessionLocal() as session:
        prompts_db = ImagePromptsDB(
            job_id=job_id,
            prompts=prompts.model_dump()
        )
        session.add(prompts_db)
        await session.commit()


# ==================== Regeneration ====================

async def regenerate_page(
    job_id: str,
    book_id: str,
    page_number: int,
    mode: str,
    feedback: Optional[str] = None
):
    """페이지 재생성"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Page, StoryDraftDB
    from src.services.llm import call_text_rewrite
    from src.services.image import generate_image
    from src.services.storage import storage_service
    from sqlalchemy import select

    logger.info(
        "Regenerating page",
        job_id=job_id,
        book_id=book_id,
        page=page_number,
        mode=mode
    )

    async with AsyncSessionLocal() as session:
        # Load book and page
        book_result = await session.execute(
            select(Book).where(Book.id == book_id)
        )
        book = book_result.scalar_one_or_none()
        if not book:
            raise ValueError(f"Book {book_id} not found")

        page_result = await session.execute(
            select(Page).where(
                Page.book_id == book_id,
                Page.page_number == page_number
            )
        )
        page = page_result.scalar_one_or_none()
        if not page:
            raise ValueError(f"Page {page_number} not found")

        # Regenerate based on mode
        if mode in ["text", "both"]:
            # Load story draft for context
            draft_result = await session.execute(
                select(StoryDraftDB).where(StoryDraftDB.job_id == job_id)
            )
            draft_db = draft_result.scalar_one_or_none()

            if draft_db and feedback:
                from src.models.dto import BookSpec, StoryDraft
                spec = BookSpec(
                    topic=book.title,
                    language=book.language,
                    target_age=book.target_age,
                    style=book.style
                )
                story = StoryDraft.model_validate(draft_db.draft)

                # Rewrite text with feedback
                rewrite_result = await call_text_rewrite(
                    spec, story, page_number, feedback
                )
                page.text = rewrite_result.get("revised_text", page.text)

        if mode in ["image", "both"]:
            # Generate new image
            if page.image_prompt:
                image_data = await generate_image(
                    page.image_prompt,
                    seed=None  # New random seed
                )
                if image_data:
                    # Upload new image
                    image_url = await storage_service.upload_image(
                        image_data,
                        f"{book_id}/page_{page_number}_v2.png"
                    )
                    page.image_url = image_url

        page.updated_at = datetime.utcnow()
        await session.commit()

    logger.info(
        "Page regeneration complete",
        book_id=book_id,
        page=page_number,
        mode=mode
    )


# ==================== Series Generation ====================

async def start_series_generation(
    job_id: str,
    request: SeriesNextRequest,
    user_key: str,
    character,
    prev_book
):
    """시리즈 다음 권 생성 - 기존 캐릭터로 새 이야기"""
    from src.models.dto import CharacterSpec

    logger.info(
        "Starting series generation",
        job_id=job_id,
        character_id=request.character_id,
        prev_book_id=request.previous_book_id
    )

    # Build topic from previous book and hint
    topic = request.new_topic_hint or f"{character.name}의 새로운 모험"

    # Create BookSpec for series
    series_spec = BookSpec(
        topic=topic,
        language=prev_book.language,
        target_age=request.target_age,
        style=request.style,
        page_count=request.page_count,
        theme=request.theme,
        character_id=request.character_id,
        character=CharacterSpec(
            name=character.name,
            appearance=character.master_description,
            personality=", ".join(character.personality_traits) if character.personality_traits else None
        ),
        forbidden_elements=request.forbidden_elements,
        series_context=f"이전 책 '{prev_book.title}'의 후속편입니다."
    )

    # Use existing book generation pipeline
    await start_book_generation(job_id, series_spec, user_key)
