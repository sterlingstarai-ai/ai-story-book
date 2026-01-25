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
from datetime import datetime, timezone
import uuid
import structlog

from src.core.config import settings


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


from src.core.errors import StoryBookError, ErrorCode, TransientError, get_backoff
from src.models.dto import (
    BookSpec,
    StoryDraft,
    CharacterSheet,
    ImagePrompts,
    ModerationResult,
    BookResult,
    SeriesNextRequest,
    LearningAssets,
    Language,
)

logger = structlog.get_logger()

T = TypeVar("T")


# ==================== Progress Constants ====================

PROGRESS_NORMALIZE = 5
PROGRESS_MODERATE_INPUT = 10
PROGRESS_STORY = 30
PROGRESS_CHARACTER = 40
PROGRESS_IMAGE_PROMPTS = 50
PROGRESS_IMAGES_START = 50
PROGRESS_IMAGES_END = 85
PROGRESS_LEARNING_ASSETS = 92
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
                "Step completed", job_id=job_id, step=step_name, attempt=attempt + 1
            )
            return result

        except asyncio.TimeoutError as e:
            last_exc = e
            logger.warning(
                "Step timeout",
                job_id=job_id,
                step=step_name,
                attempt=attempt + 1,
                timeout=timeout_sec,
            )

        except TransientError as e:
            last_exc = e
            logger.warning(
                "Transient error",
                job_id=job_id,
                step=step_name,
                attempt=attempt + 1,
                error=str(e),
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
                error=str(e),
            )

        # 재시도 대기
        if attempt < retries:
            wait_time = backoff[min(attempt, len(backoff) - 1)]
            logger.info(f"Waiting {wait_time}s before retry...")
            await asyncio.sleep(wait_time)

    # 최종 실패 - preserve stack trace with 'from' for proper chaining
    if last_exc:
        raise StoryBookError(
            code=ErrorCode.UNKNOWN,
            message=f"Step '{step_name}' failed after {retries + 1} attempts: {last_exc}",
        ) from last_exc
    raise RuntimeError(f"Step {step_name} failed without exception")


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
            job.updated_at = utcnow()
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
            job.updated_at = utcnow()
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
            job.updated_at = utcnow()
            await session.commit()

    logger.info("Job completed", job_id=job_id)


# ==================== Main Orchestrator ====================


async def start_book_generation(
    job_id: str,
    spec: BookSpec,
    user_key: str,
    series_id: Optional[str] = None,
    series_index: Optional[int] = None,
):
    """
    동화책 생성 메인 파이프라인

    비동기 백그라운드 태스크로 실행됨

    Args:
        job_id: 잡 ID
        spec: 책 생성 스펙
        user_key: 사용자 키
        series_id: 시리즈 ID (옵션)
        series_index: 시리즈 내 순서 (옵션)
    """
    try:
        logger.info(
            "Starting book generation",
            job_id=job_id,
            topic=spec.topic,
            series_id=series_id,
            series_index=series_index,
        )

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
                suggestions=moderation.suggestions,
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
            fn=lambda: generate_image_prompts(
                normalized_spec, story_draft, character_sheet
            ),
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
            progress=86,
            fn=lambda: moderate_output(story_draft, image_urls),
            retries=0,
            timeout_sec=10,
        )

        # G-2. 학습 자산 생성 (번역 + 어휘 + 질문)
        learning_assets = await run_step(
            job_id=job_id,
            step_name="학습 자료 만드는 중...",
            progress=PROGRESS_LEARNING_ASSETS,
            fn=lambda: generate_learning_assets(story_draft),
            retries=1,
            timeout_sec=settings.llm_timeout * 2,  # 더 긴 타임아웃
            backoff=[3, 8],
        )

        # H. 패키징 및 저장
        book_result = await run_step(
            job_id=job_id,
            step_name="마무리 중...",
            progress=98,
            fn=lambda: package_book(
                job_id,
                user_key,
                normalized_spec,
                story_draft,
                character_sheet,
                image_prompts,
                image_urls,
                learning_assets,
                series_id,
                series_index,
            ),
            retries=1,
            timeout_sec=30,
        )

        # 완료
        await mark_job_done(job_id)
        logger.info(
            "Book generation completed", job_id=job_id, book_id=book_result.book_id
        )

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
    spec: BookSpec, story: StoryDraft, character: CharacterSheet
) -> ImagePrompts:
    """E. 이미지 프롬프트 생성"""
    from src.services.llm import call_image_prompts_generation

    return await call_image_prompts_generation(spec, story, character)


async def generate_learning_assets(story: StoryDraft) -> Optional[LearningAssets]:
    """G-2. 학습 자산 생성 (번역 + 어휘 + 질문 + 퀴즈)"""
    from src.services.llm import call_learning_assets

    # 원본 언어에서 영어로 번역 (ko -> en)
    # 영어 원본이면 한국어로 (en -> ko)
    source_lang = story.language
    if source_lang == Language.ko:
        target_lang = Language.en
    elif source_lang == Language.en:
        target_lang = Language.ko
    else:
        # 일본어 등 기타 언어는 영어로
        target_lang = Language.en

    try:
        return await call_learning_assets(story, source_lang, target_lang)
    except Exception as e:
        logger.warning(
            "Failed to generate learning assets, continuing without",
            error=str(e),
        )
        return None


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
                int(current_progress + (page_num * progress_per_image)),
            )
            return await generate_image_with_retry(prompt, job_id, page_num)

    tasks = [
        generate_with_semaphore(prompt, prompt.page) for prompt in image_prompts.pages
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for prompt, result in zip(image_prompts.pages, results):
        if isinstance(result, Exception):
            logger.error(
                f"Failed to generate image for page {prompt.page}", error=str(result)
            )
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
                generate_image(prompt), timeout=settings.image_timeout
            )
            return url

        except asyncio.TimeoutError:
            logger.warning(
                f"Image generation timeout for page {page}, attempt {attempt + 1}"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(get_backoff(ErrorCode.IMAGE_TIMEOUT, attempt))

        except Exception as e:
            logger.warning(
                f"Image generation failed for page {page}: {e}, attempt {attempt + 1}"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(get_backoff(ErrorCode.IMAGE_FAILED, attempt))

    # 실패 시 placeholder
    return "https://placeholder.com/failed.png"


async def moderate_output(story: StoryDraft, image_urls: dict) -> bool:
    """G. 출력 안전성 검사 - 생성된 콘텐츠 검증"""
    # 금지 키워드 목록 (아동 부적절 콘텐츠)
    forbidden_patterns = [
        "죽이",
        "살인",
        "폭력",
        "피",
        "술",
        "담배",
        "마약",
        "성인",
        "섹스",
        "야한",
        "총",
        "칼로 찔",
        "kill",
        "murder",
        "blood",
        "sex",
        "drug",
        "alcohol",
        "violence",
        "weapon",
        "gun",
        "knife",
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
    learning_assets: Optional[LearningAssets] = None,
    series_id: Optional[str] = None,
    series_index: Optional[int] = None,
) -> BookResult:
    """H. 패키징 및 저장"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Page
    from datetime import datetime

    book_id = (
        f"book_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )

    # 다국어 제목 처리
    title_ko = None
    title_en = None
    if story.language == Language.ko:
        title_ko = story.title
        if learning_assets:
            title_en = learning_assets.title_translation
    elif story.language == Language.en:
        title_en = story.title
        if learning_assets:
            title_ko = learning_assets.title_translation

    async with AsyncSessionLocal() as session:
        try:
            # Create book
            # character_id: 단일 캐릭터 (기존 호환성), character_ids: 다중 캐릭터
            primary_char_id = (
                spec.character_ids[0] if spec.character_ids else spec.character_id
            )
            book = Book(
                id=book_id,
                job_id=job_id,
                title=story.title,
                language=story.language.value,
                target_age=story.target_age.value,
                style=spec.style.value,
                theme=story.theme,
                character_id=primary_char_id,
                character_ids=spec.character_ids,
                cover_image_url=image_urls.get(0, ""),
                user_key=user_key,
                # 시리즈 관련
                series_id=series_id,
                series_index=series_index,
                # 다국어
                title_ko=title_ko,
                title_en=title_en,
                # 학습 자산
                learning_assets=learning_assets.model_dump()
                if learning_assets
                else None,
            )
            session.add(book)

            # 학습 자산을 페이지 번호로 매핑
            learning_by_page = {}
            if learning_assets:
                for lp in learning_assets.pages:
                    learning_by_page[lp.page] = lp

            # Create pages
            for page_data in story.pages:
                # 다국어 텍스트 처리
                text_ko = None
                text_en = None
                vocab = None
                comprehension = None
                quiz = None

                if story.language == Language.ko:
                    text_ko = page_data.text
                    lp = learning_by_page.get(page_data.page)
                    if lp:
                        text_en = lp.translated_text
                        vocab = [v.model_dump() for v in lp.vocab] if lp.vocab else None
                        comprehension = (
                            [q.model_dump() for q in lp.comprehension_questions]
                            if lp.comprehension_questions
                            else None
                        )
                        quiz = [q.model_dump() for q in lp.quiz] if lp.quiz else None
                elif story.language == Language.en:
                    text_en = page_data.text
                    lp = learning_by_page.get(page_data.page)
                    if lp:
                        text_ko = lp.translated_text
                        vocab = [v.model_dump() for v in lp.vocab] if lp.vocab else None
                        comprehension = (
                            [q.model_dump() for q in lp.comprehension_questions]
                            if lp.comprehension_questions
                            else None
                        )
                        quiz = [q.model_dump() for q in lp.quiz] if lp.quiz else None

                page = Page(
                    book_id=book_id,
                    page_number=page_data.page,
                    text=page_data.text,
                    image_url=image_urls.get(page_data.page, ""),
                    image_prompt=next(
                        (
                            p.positive_prompt
                            for p in image_prompts.pages
                            if p.page == page_data.page
                        ),
                        "",
                    ),
                    # 다국어
                    text_ko=text_ko,
                    text_en=text_en,
                    # 학습 자산
                    vocab=vocab,
                    comprehension=comprehension,
                    quiz=quiz,
                )
                session.add(page)

            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(
                "Failed to save book to database", book_id=book_id, error=str(e)
            )
            raise StoryBookError(
                code=ErrorCode.DB_WRITE_FAILED,
                message=f"책 저장 실패: {e}",
            ) from e

    # Build page results with learning data
    page_results = []
    for p in story.pages:
        lp = learning_by_page.get(p.page)
        page_result = {
            "page_number": p.page,
            "text": p.text,
            "image_url": image_urls.get(p.page, ""),
            "image_prompt": next(
                (ip.positive_prompt for ip in image_prompts.pages if ip.page == p.page),
                "",
            ),
            "audio_url": None,
        }
        # 다국어 텍스트 추가
        if story.language == Language.ko:
            page_result["text_ko"] = p.text
            if lp:
                page_result["text_en"] = lp.translated_text
                page_result["vocab"] = (
                    [v.model_dump() for v in lp.vocab] if lp.vocab else None
                )
                page_result["comprehension_questions"] = (
                    [q.model_dump() for q in lp.comprehension_questions]
                    if lp.comprehension_questions
                    else None
                )
                page_result["quiz"] = (
                    [q.model_dump() for q in lp.quiz] if lp.quiz else None
                )
        elif story.language == Language.en:
            page_result["text_en"] = p.text
            if lp:
                page_result["text_ko"] = lp.translated_text
                page_result["vocab"] = (
                    [v.model_dump() for v in lp.vocab] if lp.vocab else None
                )
                page_result["comprehension_questions"] = (
                    [q.model_dump() for q in lp.comprehension_questions]
                    if lp.comprehension_questions
                    else None
                )
                page_result["quiz"] = (
                    [q.model_dump() for q in lp.quiz] if lp.quiz else None
                )

        page_results.append(page_result)

    return BookResult(
        book_id=book_id,
        title=story.title,
        language=story.language,
        target_age=story.target_age,
        style=spec.style.value,
        cover_image_url=image_urls.get(0, ""),
        pages=page_results,
        character_sheet=character,
        created_at=utcnow(),
        # 시리즈 관련
        series_id=series_id,
        series_index=series_index,
        # 다국어
        title_ko=title_ko,
        title_en=title_en,
        # 학습 자산
        learning_assets=learning_assets.model_dump() if learning_assets else None,
    )


async def save_story_draft(job_id: str, story: StoryDraft):
    """스토리 초안 저장"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import StoryDraftDB

    async with AsyncSessionLocal() as session:
        draft = StoryDraftDB(job_id=job_id, draft=story.model_dump())
        session.add(draft)
        await session.commit()


async def save_image_prompts(job_id: str, prompts: ImagePrompts):
    """이미지 프롬프트 저장"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import ImagePromptsDB

    async with AsyncSessionLocal() as session:
        prompts_db = ImagePromptsDB(job_id=job_id, prompts=prompts.model_dump())
        session.add(prompts_db)
        await session.commit()


# ==================== Regeneration ====================


async def regenerate_page(
    job_id: str,
    book_id: str,
    page_number: int,
    mode: str,
    feedback: Optional[str] = None,
):
    """페이지 재생성"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Page, StoryDraftDB
    from src.services.llm import call_text_rewrite
    from src.services.image import generate_image
    from src.services.storage import storage_service
    from sqlalchemy import select

    logger.info(
        "Regenerating page", job_id=job_id, book_id=book_id, page=page_number, mode=mode
    )

    async with AsyncSessionLocal() as session:
        # Load book and page
        book_result = await session.execute(select(Book).where(Book.id == book_id))
        book = book_result.scalar_one_or_none()
        if not book:
            raise ValueError(f"Book {book_id} not found")

        page_result = await session.execute(
            select(Page).where(Page.book_id == book_id, Page.page_number == page_number)
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
                    style=book.style,
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
                    seed=None,  # New random seed
                )
                if image_data:
                    # Upload new image
                    image_url = await storage_service.upload_image(
                        image_data, f"{book_id}/page_{page_number}_v2.png"
                    )
                    page.image_url = image_url

        page.updated_at = utcnow()
        await session.commit()

    logger.info(
        "Page regeneration complete", book_id=book_id, page=page_number, mode=mode
    )


# ==================== Series Generation ====================


async def start_series_generation(
    job_id: str, request: SeriesNextRequest, user_key: str, character, prev_book
):
    """시리즈 다음 권 생성 - 기존 캐릭터로 새 이야기"""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Series, Book
    from src.models.dto import CharacterSpec
    from sqlalchemy import select, func

    logger.info(
        "Starting series generation",
        job_id=job_id,
        character_id=request.character_id,
        series_id=request.series_id,
        prev_book_id=request.previous_book_id,
    )

    # 시리즈 처리: 기존 시리즈 사용 또는 새로 생성
    series_id = request.series_id
    series_index = 1

    async with AsyncSessionLocal() as session:
        if series_id:
            # 기존 시리즈 조회 및 인덱스 계산
            series_result = await session.execute(
                select(Series).where(Series.id == series_id)
            )
            existing_series = series_result.scalar_one_or_none()

            if existing_series:
                # 시리즈 내 최대 인덱스 조회
                max_idx_result = await session.execute(
                    select(func.max(Book.series_index)).where(
                        Book.series_id == series_id
                    )
                )
                max_idx = max_idx_result.scalar() or 0
                series_index = max_idx + 1
            else:
                # series_id가 제공되었지만 존재하지 않으면 새로 생성
                series_id = None

        if not series_id:
            # 새 시리즈 생성
            series_id = f"series_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            series_title = request.series_title or f"{character.name}의 모험 시리즈"

            new_series = Series(
                id=series_id,
                title=series_title,
                language=request.language.value,
                target_age=request.target_age.value,
                style=request.style.value,
                theme=request.theme.value if request.theme else None,
                character_id=request.character_id,
                user_key=user_key,
            )
            session.add(new_series)
            await session.commit()
            series_index = 1

    # Build topic: request.topic 우선, 없으면 new_topic_hint, 없으면 기본값
    topic = request.topic or request.new_topic_hint or f"{character.name}의 새로운 모험"

    # appearance 요약 (CharacterSpec.appearance는 max_length=200)
    appearance_src = ""
    if isinstance(getattr(character, "appearance", None), dict):
        parts = []
        for k in ["face", "hair", "skin", "body"]:
            v = character.appearance.get(k)
            if v:
                parts.append(str(v))
        appearance_src = ", ".join(parts)
    if not appearance_src:
        appearance_src = character.master_description or ""
    appearance_src = appearance_src[:200]  # 200자 제한 준수

    # language: prev_book 있으면 사용, 없으면 request.language
    language = prev_book.language if prev_book else request.language

    # series_context: prev_book 있으면 후속편 명시
    series_context = (
        f"이전 책 '{prev_book.title}'의 후속편입니다. 시리즈 {series_index}권."
        if prev_book
        else "시리즈의 첫 번째 이야기입니다."
    )

    # Create BookSpec for series
    series_spec = BookSpec(
        topic=topic,
        language=language,
        target_age=request.target_age,
        style=request.style,
        page_count=request.page_count,
        theme=request.theme,
        character_id=request.character_id,
        character=CharacterSpec(
            name=character.name,
            appearance=appearance_src,
            # personality는 list 그대로 전달 (str join 금지)
            personality=character.personality_traits or None,
        ),
        forbidden_elements=request.forbidden_elements,
        series_context=series_context,
    )

    # Use existing book generation pipeline with series info
    await start_book_generation(
        job_id,
        series_spec,
        user_key,
        series_id=series_id,
        series_index=series_index,
    )
