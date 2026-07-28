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
import re
from typing import Optional, Callable, Awaitable, TypeVar
import uuid
import structlog

from src.core.config import settings
from src.core.book_assets import build_generation_warnings, build_page_asset_status
from src.core.errors import (
    StoryBookError,
    ErrorCode,
    TransientError,
    get_backoff,
    is_retryable,
)
from src.core.utils import utcnow
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
PLACEHOLDER_IMAGE_URL = "https://placeholder.invalid/image-unavailable.png"


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

        except StoryBookError as e:
            # 재시도 가능한 코드(LLM/이미지 타임아웃·JSON 불량·레이트리밋·스토리지 업로드)는
            # 재시도한다(H9 — is_retryable 데드코드 해소, CLAUDE.md 규범 재시도표 준수).
            # SAFETY_* 등 비재시도 코드는 즉시 중단.
            if is_retryable(e):
                last_exc = e
                logger.warning(
                    "Retryable step error",
                    job_id=job_id,
                    step=step_name,
                    attempt=attempt + 1,
                    error_code=getattr(e.code, "value", str(e.code)),
                )
            else:
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
            logger.info("Waiting before retry", wait_seconds=wait_time)
            await asyncio.sleep(wait_time)

    # 최종 실패 - preserve stack trace with 'from' for proper chaining
    if last_exc:
        # 최종 에러코드 보존(H9/M20-4): 소진된 StoryBookError의 code(LLM_TIMEOUT 등)를 유지해
        # UNKNOWN으로 뭉개지 않는다. 비-StoryBookError만 UNKNOWN으로.
        if isinstance(last_exc, StoryBookError):
            raise StoryBookError(
                code=last_exc.code,
                message=f"Step '{step_name}' failed after {retries + 1} attempts: {last_exc}",
            ) from last_exc
        raise StoryBookError(
            code=ErrorCode.UNKNOWN,
            message=f"Step '{step_name}' failed after {retries + 1} attempts: {last_exc}",
        ) from last_exc
    raise RuntimeError(f"Step {step_name} failed without exception")


# ==================== Database Helpers ====================


async def update_job_status(job_id: str, step: str, progress: int):
    """잡 상태(진행) 업데이트 — 이미 terminal(done/failed)이면 running으로 되돌리지 않는다(H10 fence)."""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Job
    from sqlalchemy import update

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(["queued", "running"]))
            .values(
                current_step=step,
                progress=progress,
                status="running",
                updated_at=utcnow(),
            )
        )
        await session.commit()


async def mark_job_failed(job_id: str, error_code: ErrorCode, message: str):
    """잡 실패 처리 — done 잡을 failed로 되돌리지 않는다(H10 fence). 전이 성공 시에만 환불."""
    from src.core.database import AsyncSessionLocal
    from src.models.db import Job
    from sqlalchemy import select, update

    async with AsyncSessionLocal() as session:
        # queued/running일 때만 failed 전이(done 뒤집기 방지). 실패 상태를 먼저 영속화(MA3).
        result = await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(["queued", "running"]))
            .values(
                status="failed",
                error_code=error_code.value,
                error_message=message,
                updated_at=utcnow(),
            )
        )
        transitioned = result.rowcount == 1
        await session.commit()

        if not transitioned:
            logger.warning(
                "mark_job_failed skipped (job already terminal)", job_id=job_id
            )
            return

        # 전이 성공 시에만 선차감 유료 크레딧 환불(멱등, G3). 환불 실패가 실패 마킹을 막지 않게.
        job = (
            await session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()
        if job is not None:
            try:
                from src.services.credits import credits_service

                await credits_service.refund_for_job(
                    session,
                    job.user_key,
                    job_id,
                    description="생성 실패 환불(자동)",
                    commit=True,
                )
            except Exception as refund_exc:  # noqa: BLE001
                logger.warning(
                    "failed-job refund error", job_id=job_id, error=str(refund_exc)
                )

    logger.error("Job failed", job_id=job_id, error_code=error_code, message=message)


async def mark_job_done(job_id: str):
    """잡 완료 처리 — running일 때만 done 전이(H10 fence). 책은 mark_job_done 이전에 커밋되므로,
    SLA로 환불된 잡이 뒤늦게 완주하면 '책+환불' 이중지급이 된다(MA2) → 환불이 존재하면 clawback."""
    from src.core.database import AsyncSessionLocal
    from src.models.db import CreditTransaction, Job
    from sqlalchemy import select, update

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                status="done",
                progress=100,
                current_step="done",
                updated_at=utcnow(),
            )
        )
        transitioned = result.rowcount == 1
        await session.commit()

        # rowcount 무관: 책이 배달된 상태에서 SLA 환불이 존재하면 '책+환불' 이중지급이므로
        # 환불을 clawback해 정합화(책 배달분 과금, 멱등). done으로 뒤집지 않아도 회수는 필요.
        job = (
            await session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()
        if job is not None:
            has_refund = (
                await session.execute(
                    select(CreditTransaction.id)
                    .where(
                        CreditTransaction.reference_id == job_id,
                        CreditTransaction.transaction_type == "refund",
                    )
                    .limit(1)
                )
            ).first() is not None
            if has_refund:
                from src.services.credits import credits_service

                await credits_service.clawback_credits(
                    session,
                    job.user_key,
                    amount=1,
                    reference_id=job_id,
                    description="완료 후 환불 회수",
                    commit=True,
                )

    if transitioned:
        logger.info("Job completed", job_id=job_id)
    else:
        logger.warning(
            "stale done write-back skipped (job already terminal)", job_id=job_id
        )


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
            step_name="normalize",
            progress=PROGRESS_NORMALIZE,
            fn=lambda: normalize_input(spec),
            retries=0,
            timeout_sec=5,
        )

        # B. 입력 안전성 검사
        moderation = await run_step(
            job_id=job_id,
            step_name="moderate_input",
            progress=PROGRESS_MODERATE_INPUT,
            fn=lambda: moderate_input(normalized_spec),
            retries=0,
            timeout_sec=settings.llm_timeout,
        )

        if not moderation.is_safe:
            from src.core.errors import SafetyError

            # M29: 한국어 접두어를 하드코딩하지 않는다 — 접두어는 클라이언트가
            # 에러 코드(SAFETY_INPUT) 기반 l10n으로 붙이고, 서버는 사용자 언어로
            # 생성된 reasons 원문만 담는다.
            raise SafetyError(
                message=", ".join(moderation.reasons),
                is_input=True,
                suggestions=moderation.suggestions,
            )

        # C. 스토리 생성 + 출력 안전성 재시도(G16/M20: SAFETY_OUTPUT 시 최대 2회 재생성).
        # 출력 텍스트 안전검사를 이미지 비용 '전'으로 옮겨, unsafe면 값싸게 재생성한다
        # (이미지·캐릭터 재생성 없이). 2회 재생성 후에도 unsafe면 SAFETY_OUTPUT 실패.
        story_draft = None
        for _safety_attempt in range(3):  # 1 initial + 2 retries
            story_draft = await run_step(
                job_id=job_id,
                step_name="generate_story",
                progress=PROGRESS_STORY,
                fn=lambda: generate_story(normalized_spec),
                retries=2,
                timeout_sec=settings.llm_timeout,
                backoff=[2, 5],
            )
            if await moderate_output(story_draft, {}):
                break
            logger.warning(
                "Output text failed moderation, regenerating story",
                job_id=job_id,
                attempt=_safety_attempt + 1,
            )
        else:
            from src.core.errors import SafetyError

            raise SafetyError(
                message="생성된 이야기가 안전 기준을 통과하지 못했습니다",
                is_input=False,
            )

        # 스토리 저장
        await save_story_draft(job_id, story_draft)

        # D. 캐릭터 시트 생성
        character_sheet = await run_step(
            job_id=job_id,
            step_name="generate_character_sheet",
            progress=PROGRESS_CHARACTER,
            fn=lambda: generate_character_sheet(normalized_spec, story_draft),
            retries=1,
            timeout_sec=settings.llm_timeout,
            backoff=[2],
        )

        # E. 이미지 프롬프트 생성
        image_prompts = await run_step(
            job_id=job_id,
            step_name="generate_image_prompts",
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
        face_reference_url = await _resolve_face_reference(normalized_spec, user_key)
        image_urls = await generate_all_images(
            job_id=job_id,
            image_prompts=image_prompts,
            total_images=total_images,
            reference_image_url=face_reference_url,
        )

        # G. 출력 안전성 검사(텍스트)는 스토리 생성 직후(C)에서 재시도와 함께 이미 수행했다
        # (G16/M20: 이미지 비용 전에 검사·재생성). 이미지 콘텐츠 안전검사(vision 모더레이션)는
        # provider safety 신호 부재로 별도 스코프(H24/M20 잔여) — 여기서 안전연극 훅을 두지 않는다.
        await update_job_status(job_id, "moderate_output", 86)

        # G-2. 학습 자산 생성 (번역 + 어휘 + 질문)
        learning_assets = await run_step(
            job_id=job_id,
            step_name="learning_assets",
            progress=PROGRESS_LEARNING_ASSETS,
            fn=lambda: generate_learning_assets(story_draft),
            retries=1,
            timeout_sec=settings.llm_timeout * 2,  # 더 긴 타임아웃
            backoff=[3, 8],
        )

        # H. 패키징 및 저장
        book_result = await run_step(
            job_id=job_id,
            step_name="package",
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


def _is_gradeable_quiz(quiz_item) -> bool:
    """퀴즈가 채점 가능한지 — 정답 인덱스가 보기 범위 내·보기 중복 없음·정답 보기 비어있지 않음."""
    options = quiz_item.options or []
    if not (0 <= quiz_item.answer_index < len(options)):
        return False
    if len(set(options)) < len(options):  # 중복 보기 → 정답 모호
        return False
    if not (options[quiz_item.answer_index] or "").strip():  # 빈 정답 보기
        return False
    return True


def _grounding_corpus(assets: LearningAssets, story_text: str) -> str:
    """grounding 대조 코퍼스 — 원문 + 번역문 + 어휘(원어/뜻) + 이해질문 답.

    학습 퀴즈는 번역언어(target)로 생성되므로(예: ko 동화 → 'rabbit' 정답) 원문만으로는
    정상 퀴즈도 환각으로 오판된다. 학습자산이 실제 쓰는 언어 코퍼스 전체에 대조한다.
    """
    parts = [story_text]
    for p in (assets.pages or []):
        if getattr(p, "translated_text", None):
            parts.append(p.translated_text)
        for v in (p.vocab or []):
            parts.append(getattr(v, "word", "") or "")
            parts.append(getattr(v, "meaning", "") or "")
        for q in (p.comprehension_questions or []):
            parts.append(getattr(q, "answer", "") or "")
    return " ".join(parts)


def _quiz_answer_grounded(quiz_item, corpus: str) -> bool:
    """정답이 학습 코퍼스(원문·번역·어휘·이해답)에 근거하는지 — 완전 환각만 드롭.

    의미 토큰(2자+) 중 하나라도 코퍼스에 있으면 통과(보수적 = 정상 콘텐츠 과드롭 방지).
    구두점은 정규화해 분리한다. 1자/숫자 등 짧은 답은 통과(과드롭 방지).
    """
    options = quiz_item.options or []
    if not (0 <= quiz_item.answer_index < len(options)):
        return False
    answer = (options[quiz_item.answer_index] or "").strip()
    if not answer:
        return False
    norm = re.sub(r"[^\w가-힣ぁ-んァ-ン一-鿿]+", " ", answer)
    tokens = [t for t in norm.split() if len(t) >= 2]
    if not tokens:
        return True
    return any(tok in corpus for tok in tokens)


def _assess_and_clean_learning_quality(
    assets: LearningAssets, story_text: str = ""
) -> list[str]:
    """학습 자산 품질 점검 + 채점 불가/환각 퀴즈 제거. 미달/조치 항목 목록 반환(빈 목록=양호).

    LLM(gpt-4o-mini)이 생성한 어휘/퀴즈를 부모에게 '교육 증거'로 노출하기 전,
    최소 품질을 점검하고 채점 불가·코퍼스 미근거(환각) 퀴즈를 걸러낸다.
    """
    issues: list[str] = []
    pages = assets.pages or []
    corpus = _grounding_corpus(assets, story_text)
    dropped = 0
    ungrounded = 0
    for page in pages:
        if page.quiz:
            valid = []
            for q in page.quiz:
                if not _is_gradeable_quiz(q):
                    dropped += 1
                    continue
                if corpus.strip() and not _quiz_answer_grounded(q, corpus):
                    ungrounded += 1
                    continue
                valid.append(q)
            page.quiz = valid
    if dropped:
        issues.append(f"채점 불가 퀴즈 {dropped}개 제거")
    if ungrounded:
        issues.append(f"본문 미근거(환각 의심) 퀴즈 {ungrounded}개 제거")
    if sum(len(p.vocab or []) for p in pages) == 0:
        issues.append("어휘 0개")
    if sum(len(p.quiz or []) for p in pages) == 0:
        issues.append("퀴즈 0개")
    return issues


async def generate_learning_assets(story: StoryDraft) -> Optional[LearningAssets]:
    """G-2. 학습 자산 생성 (번역 + 어휘 + 질문 + 퀴즈) + 품질 게이트"""
    from src.services.llm import call_learning_assets

    # translated_text(이중언어 읽기용)는 원본→타깃 번역(ko→en, en→ko). 단, vocab의
    # meaning은 프롬프트에서 원어(source_language) 뜻풀이로 생성된다 — '한국어 읽기성장'
    # 제품의 어휘 게임이 영어 번역 시험이 아니라 모국어 어휘 실력을 측정하게 하기 위함.
    source_lang = story.language
    if source_lang == Language.ko:
        target_lang = Language.en
    elif source_lang == Language.en:
        target_lang = Language.ko
    else:
        # 일본어 등 기타 언어는 영어로
        target_lang = Language.en

    try:
        assets = await call_learning_assets(story, source_lang, target_lang)
    except Exception as e:
        logger.warning(
            "Failed to generate learning assets, continuing without",
            error=str(e),
        )
        return None

    if assets is None:
        return None

    story_text = " ".join((p.text or "") for p in (story.pages or []))
    issues = _assess_and_clean_learning_quality(assets, story_text)
    if issues:
        logger.warning(
            "Learning assets quality gate", issues=issues, title=story.title
        )

    # 어휘·퀴즈가 모두 비면 '교육 증거'로 노출하지 않는다(무자산이 오히려 안전).
    has_vocab = any((p.vocab or []) for p in (assets.pages or []))
    has_quiz = any((p.quiz or []) for p in (assets.pages or []))
    if not has_vocab and not has_quiz:
        logger.warning(
            "Learning assets empty after quality gate; dropping", title=story.title
        )
        return None

    return assets


async def _resolve_face_reference(spec, user_key: str) -> Optional[str]:
    """주인공이 사진 파생(from_photo) 캐릭터면 그 원본 사진 URL을 얼굴 레퍼런스로 반환.

    - 얼굴 보존 provider(gemini)에서만 사용.
    - **반드시 user_key로 스코프**(타 유저 아동 사진 도용 IDOR 차단).
    - 스토리 생성과 동일한 '택일' 의미(character_ids 우선) + 주인공(char_ids[0]) 우선의 결정적 선택.
    """
    if settings.image_provider != "gemini":
        return None
    cids = getattr(spec, "character_ids", None)
    char_ids = (
        list(cids)
        if cids
        else ([spec.character_id] if getattr(spec, "character_id", None) else [])
    )
    char_ids = [c for c in char_ids if c]
    if not char_ids:
        return None
    try:
        from sqlalchemy import select

        from src.core.database import AsyncSessionLocal
        from src.models.db import Character

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Character.id, Character.source_image_url).where(
                    Character.id.in_(char_ids),
                    Character.user_key == user_key,
                    Character.from_photo.is_(True),
                    Character.source_image_url.isnot(None),
                )
            )
            by_id = {row[0]: row[1] for row in result.all()}
        # 주인공(char_ids[0])부터 순서대로 첫 매칭 — DB plan 무관 결정적 선택
        for cid in char_ids:
            if cid in by_id:
                return by_id[cid]
        return None
    except Exception as e:  # pragma: no cover - 방어적
        logger.warning("face reference resolve failed", error=str(e))
        return None


async def generate_all_images(
    job_id: str,
    image_prompts: ImagePrompts,
    total_images: int,
    reference_image_url: Optional[str] = None,
) -> dict[int, str]:
    """
    F. 이미지 생성 (cover + pages)

    reference_image_url: 주인공 아이 얼굴 사진 — 얼굴 보존 provider(gemini)에서
    표지·모든 페이지에 같은 아이 얼굴을 동화체로 일관 반영하는 데 쓰인다.

    Returns:
        dict mapping page number to image URL (0 = cover)
    """

    image_urls = {}

    # Cover (page 0)
    progress_per_image = (PROGRESS_IMAGES_END - PROGRESS_IMAGES_START) / total_images
    current_progress = PROGRESS_IMAGES_START

    # Generate cover
    await update_job_status(job_id, "generate_images", int(current_progress))
    cover_url = await generate_image_with_retry(
        image_prompts.cover, job_id, 0, reference_image_url=reference_image_url
    )
    image_urls[0] = cover_url
    current_progress += progress_per_image

    # Generate pages (with concurrency limit)
    semaphore = asyncio.Semaphore(settings.image_max_concurrent)

    async def generate_with_semaphore(prompt, page_num):
        async with semaphore:
            # M32: 안정 키로 통일(페이지 카운트는 progress 필드가 표현). 클라이언트가 l10n 매핑.
            await update_job_status(
                job_id,
                "generate_images",
                int(current_progress + (page_num * progress_per_image)),
            )
            return await generate_image_with_retry(
                prompt, job_id, page_num, reference_image_url=reference_image_url
            )

    tasks = [
        generate_with_semaphore(prompt, prompt.page) for prompt in image_prompts.pages
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    failed_pages = []
    for prompt, result in zip(image_prompts.pages, results):
        if isinstance(result, Exception):
            logger.error(
                "Failed to generate image for page",
                page=prompt.page,
                error=str(result),
            )
            failed_pages.append(prompt.page)
            image_urls[prompt.page] = ""
        elif _is_placeholder_image_url(result):
            logger.warning(
                "Image generation fell back to placeholder",
                page=prompt.page,
                url=result,
            )
            failed_pages.append(prompt.page)
            image_urls[prompt.page] = result
        else:
            image_urls[prompt.page] = result

    # 25% 이상 실패 시 전체 실패 처리 (8페이지 기준 2페이지 이상 실패)
    max_failures = max(1, len(image_prompts.pages) // 4)
    if len(failed_pages) > max_failures:
        raise StoryBookError(
            code=ErrorCode.IMAGE_FAILED,
            message=f"이미지 생성 실패가 너무 많습니다 ({len(failed_pages)}/{len(image_prompts.pages)}): 페이지 {failed_pages}",
        )

    return image_urls


async def generate_image(prompt, reference_image_url: Optional[str] = None) -> str:
    """Thin wrapper for easier testing/patching."""
    from src.services.image import generate_image as image_generate

    return await image_generate(prompt, reference_image_url=reference_image_url)


def _is_placeholder_image_url(url: str) -> bool:
    return isinstance(url, str) and "placeholder" in url


async def generate_image_with_retry(
    prompt, job_id: str, page: int, reference_image_url: Optional[str] = None
) -> str:
    """이미지 생성 (재시도 포함)"""
    max_retries = max(1, int(settings.image_max_retries))
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            url = await asyncio.wait_for(
                generate_image(prompt, reference_image_url=reference_image_url),
                timeout=settings.image_timeout,
            )
            return url

        except asyncio.TimeoutError as e:
            last_error = e
            logger.warning(
                "Image generation timeout",
                page=page,
                attempt=attempt + 1,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(get_backoff(ErrorCode.IMAGE_TIMEOUT, attempt))

        except Exception as e:
            last_error = e
            logger.warning(
                "Image generation failed",
                page=page,
                error=str(e),
                attempt=attempt + 1,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(get_backoff(ErrorCode.IMAGE_FAILED, attempt))

    # 모든 재시도 실패: 서비스 레벨 ImageError는 placeholder로 강등
    if isinstance(last_error, StoryBookError):
        placeholder = f"{PLACEHOLDER_IMAGE_URL}?page={page}"
        logger.warning(
            "Image generation exhausted retries, returning placeholder",
            page=page,
            error_code=last_error.code.value,
            placeholder=placeholder,
        )
        return placeholder

    raise StoryBookError(
        code=ErrorCode.IMAGE_FAILED,
        message=f"페이지 {page} 이미지 생성이 {max_retries}회 시도 후 실패했습니다",
    ) from last_error


# 출력 모더레이션 금칙 패턴
# - 영어: 단어 경계(\b)로 검사 → "begun"의 "gun", "assassin"의 "sin" 같은 오탐 방지.
# - 한국어: 구체적 표현으로 검사 → 단음절 광범위 패턴('피/술/총/죽이')은 정상 단어
#   (피자·커피·예술·기술·총총·반죽 등)을 silent-fail시켜 churn을 유발하므로 사용하지 않음.
_MOD_FORBIDDEN_EN = [
    "kill", "murder", "blood", "sex", "drug", "alcohol", "violence",
    "weapon", "gun", "knife", "porn", "suicide", "rape",
]
_MOD_FORBIDDEN_EN_RE = [
    re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in _MOD_FORBIDDEN_EN
]
_MOD_FORBIDDEN_KO = [
    # 살해·폭력
    "죽여", "죽이는", "죽이고", "죽이려", "죽인다", "살해", "살인", "폭력",
    "때려 죽", "패 죽", "목 졸", "목졸",
    # 무기
    "권총", "총격", "총살", "총을 쏘", "총을 쐈", "총으로", "총구", "기관총",
    "엽총", "칼로 찌", "칼로 찔", "칼로 베", "흉기",
    # 유혈·잔혹
    "피범벅", "피투성", "유혈", "잔혹", "참수", "토막",
    # 약물·음주·흡연
    "마약", "담배", "흡연", "음주", "술에 취", "술을 마", "술주정",
    "소주", "맥주", "막걸리",
    # 성인
    "섹스", "성행위", "음란", "포르노", "야한", "자살",
]


# H24: 아래 KO/EN 키워드망이 실제로 커버하는 언어. 이 밖의 스토리 언어(ja/zh/es)는
# 키워드망이 비어 있어 fail-open(항상 True)하던 아동 안전 공백 → LLM 폴백으로 커버.
_KEYWORD_COVERED_LANGUAGES = {Language.ko, Language.en}


def _moderate_text(text: str) -> bool:
    """텍스트 금칙어 검사(순수 헬퍼). 안전하면 True.

    M12: 최초 생성 파이프라인의 출력 안전검사(KO 구체표현·EN 단어경계)를
    재생성 feedback·인페인트 region_prompt·retell/재생성 출력에서 재사용한다.
    B/G 안전 게이트가 최초 생성에만 있어 재생성·리텔·인페인트가 우회하던 공백을 메운다.
    """
    if not isinstance(text, str):
        return True
    for pattern in _MOD_FORBIDDEN_KO:
        if pattern in text:
            return False
    for rx in _MOD_FORBIDDEN_EN_RE:
        if rx.search(text):
            return False
    return True


async def moderate_text_localized(text: str, language) -> bool:
    """키워드망(ko/en) 검사 후, 망 밖 언어(ja/zh/es)는 LLM 출력 모더레이션으로 폴백한다.

    M12가 배선한 재생성·리텔·인페인트 게이트는 _moderate_text(ko/en 키워드)만 사용해
    ja/zh/es 텍스트가 입력·출력 모두 무조건 통과했다 — H24가 메인 파이프라인에서 확립한
    '키워드망 밖 언어 = fail-open 금지' 불변식과 정면 모순(출시 5개 언어 중 3종에서 아동
    안전망 우회). 그 폴백을 동일하게 재사용해 파리티를 맞춘다.
    """
    if not _moderate_text(text):
        return False

    try:
        lang = language if isinstance(language, Language) else Language(language)
    except ValueError:
        # 알 수 없는 언어 코드는 키워드망만으로 판정(폴백 대상 불명).
        return True

    if lang in _KEYWORD_COVERED_LANGUAGES:
        return True

    from src.services.llm import call_output_moderation

    result = await call_output_moderation(text, lang)
    if not result.is_safe:
        logger.warning(
            "Moderation failed (LLM fallback)",
            language=lang.value,
            reasons=result.reasons,
        )
    return result.is_safe


async def moderate_output(story: StoryDraft, image_urls: dict) -> bool:
    """G. 출력 안전성 검사 - 생성된 콘텐츠 검증.

    영어 금칙어는 단어 경계로, 한국어 금칙어는 구체적 표현으로 검사하여
    '피자/예술/총총' 등 정상 단어의 오탐(=정상 동화의 silent generation failure)을 방지한다.

    ko/en 키워드망 밖 언어(ja/zh/es)는 키워드가 없어 무조건 통과하던 fail-open을
    제거하고, LLM 기반 출력 모더레이션(call_output_moderation)으로 폴백한다(H24, G17).

    NOTE(H24/G17): image_urls 인자의 이미지 콘텐츠 안전검사는 여기서 배선하지 않는다.
    현 아키텍처에는 생성된 이미지에 대한 safety 신호가 provider 요청 파라미터
    (fal enable_safety_checker 등) 외에 반환 경로로 없어, Python 측에서 always-safe
    훅을 두면 '검사한 척'하는 안전 연극이 된다. 실질 배선(vision 모더레이션 또는
    provider nsfw 플래그 패스스루)은 이미지 생성 반환 타입 변경을 수반하는 별도
    스코프 — CTO 재확인 대상으로 보고한다.
    """
    text = story.title
    for page in story.pages:
        text += " " + page.text

    if not _moderate_text(text):
        logger.warning("Output moderation failed (keyword)", title=story.title)
        return False

    # H24: 키워드망 밖 언어는 fail-open 대신 LLM 출력 모더레이션 폴백.
    if story.language not in _KEYWORD_COVERED_LANGUAGES:
        from src.services.llm import call_output_moderation

        result = await call_output_moderation(text, story.language)
        if not result.is_safe:
            logger.warning(
                "Output moderation failed (LLM fallback)",
                language=story.language.value,
                reasons=result.reasons,
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
    from src.models.db import Book, Job, Page
    from sqlalchemy import select

    book_id = f"book_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

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
            job_result = await session.execute(select(Job).where(Job.id == job_id))
            job = job_result.scalar_one_or_none()
            profile_id = job.profile_id if job else None

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
                profile_id=profile_id,
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

                lp = learning_by_page.get(page_data.page)
                # 이중언어(ko↔en) 표시 텍스트 매핑. 그 외 언어(ja 등)는 네이티브 텍스트가
                # 아래 page.text 컬럼에 그대로 저장된다.
                if story.language == Language.ko:
                    text_ko = page_data.text
                    if lp:
                        text_en = lp.translated_text
                elif story.language == Language.en:
                    text_en = page_data.text
                    if lp:
                        text_ko = lp.translated_text
                # 학습 자산(어휘/독해/퀴즈)은 콘텐츠 언어와 무관하게 항상 부착한다.
                # (예전엔 ko/en 분기 안에만 있어 ja 등에서 통째로 누락됐다.)
                if lp:
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
            "asset_status": build_page_asset_status(
                image_urls.get(p.page, ""),
                audio_urls=[None],
            ),
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

    generation_warnings = build_generation_warnings(
        cover_image_url=image_urls.get(0, ""),
        page_images=[(p.page, image_urls.get(p.page, "")) for p in story.pages],
    )
    if generation_warnings:
        logger.warning(
            "Book packaged with degraded assets",
            job_id=job_id,
            warning_count=len(generation_warnings),
        )

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
        generation_warnings=generation_warnings,
    )


async def save_story_draft(job_id: str, story: StoryDraft):
    """스토리 초안 저장 — job_id 기준 멱등(M23).

    Celery 재전달(acks_late)로 파이프라인이 중간부터 다시 도는 경우 plain INSERT는
    unique(job_id) 충돌을 내고, 그 IntegrityError는 start_book_generation의 전역
    except가 먼저 잡아 UNKNOWN 실패 + 환불로 확정시킨다(복구 가능한 재전달이 영구
    실패가 됨). 있으면 갱신해 재실행이 이어서 진행되게 한다.
    """
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal
    from src.models.db import StoryDraftDB

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(StoryDraftDB).where(StoryDraftDB.job_id == job_id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.draft = story.model_dump()
        else:
            session.add(StoryDraftDB(job_id=job_id, draft=story.model_dump()))
        await session.commit()


async def save_image_prompts(job_id: str, prompts: ImagePrompts):
    """이미지 프롬프트 저장 — job_id 기준 멱등(M23, save_story_draft와 동일 이유)."""
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal
    from src.models.db import ImagePromptsDB

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(ImagePromptsDB).where(ImagePromptsDB.job_id == job_id)
            )
        ).scalar_one_or_none()
        if existing:
            existing.prompts = prompts.model_dump()
        else:
            session.add(ImagePromptsDB(job_id=job_id, prompts=prompts.model_dump()))
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
            from src.core.errors import SafetyError

            # M12: feedback 입력 모더레이션 — 최초 생성 B 게이트 파리티. 부적절 요청은
            # LLM에 전달하기 전에 SAFETY_INPUT으로 차단(page.text 불변).
            if feedback and not await moderate_text_localized(feedback, book.language):
                raise SafetyError(
                    message="부적절한 재생성 요청입니다", is_input=True
                )

            # Load story draft for context
            draft_result = await session.execute(
                select(StoryDraftDB).where(StoryDraftDB.job_id == job_id)
            )
            draft_db = draft_result.scalar_one_or_none()

            # M12: draft 부재(retell 책 등)면 조용한 no-op(done 위장) 대신 명시 실패.
            if not draft_db:
                raise StoryBookError(
                    code=ErrorCode.LLM_JSON_INVALID,
                    message=(
                        "이 책은 텍스트 재생성을 위한 스토리 원안이 없습니다"
                        "(연령 리텔·이미지 전용 책은 텍스트 재생성 불가)."
                    ),
                )

            from src.models.dto import BookSpec, StoryDraft

            spec = BookSpec(
                topic=book.title,
                language=book.language,
                target_age=book.target_age,
                style=book.style,
            )
            story = StoryDraft.model_validate(draft_db.draft)

            # Rewrite text with feedback. M31: RewriteResult(검증됨) — revised_text 필수라
            # 누락은 이미 call_text_rewrite에서 LLM_JSON_INVALID로 실패(조용한 no-op 제거).
            rewrite_result = await call_text_rewrite(
                spec, story, page_number, feedback
            )
            revised = rewrite_result.revised_text
            # M12: 빈/공백 revised_text 가드 — 원문 유지 대신 명시 실패.
            if not revised or not revised.strip():
                raise StoryBookError(
                    code=ErrorCode.LLM_JSON_INVALID,
                    message="재생성 텍스트가 비어 있습니다",
                )
            # M12: 재생성 출력 모더레이션 — 최초 생성 G 게이트 파리티.
            if not await moderate_text_localized(revised, book.language):
                raise SafetyError(
                    message="재생성된 내용이 안전 기준을 통과하지 못했습니다",
                    is_input=False,
                )
            page.text = revised

            # H23/G18: 이중언어 컬럼·오디오를 본문과 정합 유지. 책 언어 컬럼은 갱신하고,
            # 반대 언어 컬럼(text_en/ko)과 기존 오디오는 stale이 되므로 무효화(None)만 한다
            # (즉시 재번역·재TTS는 하지 않음 — 최소안).
            book_lang = str(getattr(book, "language", "") or "").lower()
            if book_lang == "ko":
                page.text_ko = revised
                page.text_en = None
            elif book_lang == "en":
                page.text_en = revised
                page.text_ko = None
            else:
                # ja/zh/es: 이중언어 컬럼 미사용 — 기본 본문만 갱신.
                page.text_ko = None
                page.text_en = None
            # 본문이 바뀌었으므로 모든 언어 오디오 캐시를 무효화(어긋난 낭독 방지).
            page.audio_url = None
            if hasattr(page, "audio_url_ko"):
                page.audio_url_ko = None
            if hasattr(page, "audio_url_en"):
                page.audio_url_en = None

        # N1/#10: 교체된 구버전 이미지 키를 커밋 후 파기하기 위해 캡처.
        replaced_image_url = None
        new_image_url = None

        if mode in ["image", "both"]:
            # Generate new image
            if page.image_prompt:
                import random

                from src.models.dto import ImagePrompt

                regen_prompt = ImagePrompt(
                    page=page_number,
                    positive_prompt=page.image_prompt,
                    negative_prompt="text, letters, words, watermark, blurry, deformed",
                    seed=random.randint(1, 2147483647),
                    aspect_ratio="3:4",
                )
                image_url = await generate_image(regen_prompt)
                if image_url:
                    replaced_image_url = page.image_url
                    new_image_url = image_url
                    page.image_url = image_url

        page.updated_at = utcnow()
        await session.commit()

    # N1/#10: 커밋 성공 후에만 구버전 키 파기(커밋 실패 시 살아있는 이미지를 지우지 않도록).
    await _purge_replaced_image(replaced_image_url, new_image_url)

    logger.info(
        "Page regeneration complete", book_id=book_id, page=page_number, mode=mode
    )


async def _purge_replaced_image(previous_url, new_url) -> None:
    """이미지 교체 커밋 후 이전 버전의 스토리지 키를 파기한다(N1/#10).

    교체만 하고 이전 키를 지우지 않으면, 삭제 경로(계정/책/동의철회)의 역산은 '현재
    image_url'만 커버하므로 구버전 일러스트(아동 사진 파생 가능)가 어떤 파기 경로로도
    지워지지 않는 영구 고아가 된다. 파기 실패는 warning으로만 남긴다(교체 자체는 성공).
    """
    if not previous_url or previous_url == new_url:
        return
    try:
        from src.services.storage import delete_keys, key_from_public_url

        key = key_from_public_url(previous_url)
        if not key:
            return
        failed = await delete_keys([key])
        if failed:
            logger.warning("replaced image delete failures", failed_keys=failed)
    except Exception as exc:  # pragma: no cover - 방어적
        logger.warning("replaced image delete failed", error=str(exc))


async def inpaint_page(
    job_id: str,
    book_id: str,
    page_number: int,
    mask_url: str,
    region_prompt: str,
):
    """페이지 부분 재생성(인페인트) — 마스크 영역만 region_prompt로 다시 그리고
    나머지는 기존 이미지를 유지한다. (image_provider가 replicate/fal일 때만 동작.)"""
    import random

    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Page
    from src.models.dto import ImagePrompt
    from src.services.image import generate_image
    from sqlalchemy import select

    logger.info("Inpainting page", job_id=job_id, book_id=book_id, page=page_number)

    async with AsyncSessionLocal() as session:
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
        if not page.image_url:
            raise ValueError(f"Page {page_number} has no base image to inpaint")

        # M12: region_prompt 입력 모더레이션 — 무검사 결합 전에 SAFETY_INPUT으로 차단.
        from src.core.errors import SafetyError

        if not await moderate_text_localized(region_prompt, book.language):
            raise SafetyError(
                message="부적절한 부분 재생성 요청입니다", is_input=True
            )

        # region 지시 + 기존 페이지 프롬프트(스타일·캐릭터 일관성)를 결합(최대 1200자)
        positive = (region_prompt.strip() + ". " + (page.image_prompt or "")).strip()
        positive = positive[:1200]
        if len(positive) < 10:
            positive = (region_prompt + " soft children's book illustration")[:1200]

        inpaint_prompt = ImagePrompt(
            page=page_number,
            positive_prompt=positive,
            negative_prompt="text, letters, words, watermark, blurry, deformed",
            seed=random.randint(1, 2147483647),
            aspect_ratio="3:4",
            base_image_url=page.image_url,
            mask_url=mask_url,
        )
        image_url = await generate_image(inpaint_prompt)
        replaced_image_url = None
        if image_url:
            replaced_image_url = page.image_url
            page.image_url = image_url

        page.updated_at = utcnow()
        await session.commit()

    # N1/#10: 인페인트도 새 키에 저장되므로 이전 버전이 고아가 된다 — 커밋 후 파기.
    await _purge_replaced_image(replaced_image_url, image_url)

    logger.info("Page inpaint complete", book_id=book_id, page=page_number)


# ==================== Series Generation ====================


async def start_series_generation(
    job_id: str, request: SeriesNextRequest, user_key: str, character, prev_book
):
    """시리즈 다음 권 생성 - 기존 캐릭터로 새 이야기"""
    from sqlalchemy import func, select

    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Series
    from src.models.dto import CharacterSpec, Language

    logger.info(
        "Starting series generation",
        job_id=job_id,
        character_id=request.character_id,
        series_id=request.series_id,
        prev_book_id=request.previous_book_id,
    )

    from src.models.dto import Style, TargetAge

    # H19/G22: '다음 권'이 원작 스타일·연령대를 버리고 watercolor/5-7로 나오던 문제 —
    # 명시값 우선, 없으면 prev_book 값 상속, 둘 다 없으면 기본값.
    effective_style = request.style
    if effective_style is None:
        if prev_book and prev_book.style in {s.value for s in Style}:
            effective_style = Style(prev_book.style)
        else:
            effective_style = Style.watercolor
    effective_target_age = request.target_age
    if effective_target_age is None:
        if prev_book and prev_book.target_age in {t.value for t in TargetAge}:
            effective_target_age = TargetAge(prev_book.target_age)
        else:
            effective_target_age = TargetAge.a5_7

    # 시리즈 ID 결정 우선순위:
    # 1) request.series_id
    # 2) previous_book_id로 조회한 책의 series_id
    # 3) 신규 시리즈 생성
    series_id = request.series_id or (prev_book.series_id if prev_book else None)
    series_index = 1

    async with AsyncSessionLocal() as session:
        if series_id:
            series_result = await session.execute(select(Series).where(Series.id == series_id))
            existing_series = series_result.scalar_one_or_none()
            if existing_series:
                max_idx_result = await session.execute(
                    select(func.max(Book.series_index)).where(Book.series_id == series_id)
                )
                max_idx = max_idx_result.scalar() or 0
                series_index = max_idx + 1
            else:
                # 외부에서 전달된 series_id가 유효하지 않으면 신규 시리즈로 대체
                series_id = None

        if not series_id:
            series_id = (
                f"series_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            )
            series_title = request.series_title or f"{character.name}의 모험 시리즈"
            new_series = Series(
                id=series_id,
                title=series_title,
                language=request.language.value,
                target_age=effective_target_age.value,
                style=effective_style.value,
                theme=request.theme.value if request.theme else None,
                character_id=request.character_id,
                user_key=user_key,
            )
            session.add(new_series)
            await session.commit()
            series_index = 1

    topic = request.topic or request.new_topic_hint or f"{character.name}의 새로운 모험"

    appearance_src = ""
    if isinstance(getattr(character, "appearance", None), dict):
        parts: list[str] = []
        for k in ["face", "hair", "skin", "body"]:
            v = character.appearance.get(k)
            if v:
                parts.append(str(v))
        appearance_src = ", ".join(parts)
    if not appearance_src:
        appearance_src = character.master_description or ""
    appearance_src = appearance_src[:200]

    language = request.language
    if prev_book and prev_book.language in {lang.value for lang in Language}:
        language = Language(prev_book.language)

    series_context = (
        f"이전 책 '{prev_book.title}'의 후속편입니다. 시리즈 {series_index}권."
        if prev_book
        else "시리즈의 첫 번째 이야기입니다."
    )

    # Create BookSpec for series — H19: 원작 상속된 effective 값 사용(watercolor/5-7 기본 탈락).
    series_spec = BookSpec(
        topic=topic,
        language=language,
        target_age=effective_target_age,
        style=effective_style,
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
