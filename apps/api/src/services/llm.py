"""
LLM Service: 텍스트 생성 (스토리, 캐릭터 시트, 이미지 프롬프트)
"""

import json
import httpx
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import structlog

from src.core.config import settings
from src.core.errors import LLMError, ErrorCode
from src.core.i18n import SUPPORTED_LANGUAGES, language_display_name
from src.models.dto import (
    BookSpec,
    StoryDraft,
    CharacterSheet,
    ImagePrompts,
    ModerationResult,
    LearningAssets,
    Language,
    RetoldStory,
    RewriteResult,
)

logger = structlog.get_logger()

# Jinja2 environment for prompt templates
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
jinja_env = Environment(loader=FileSystemLoader(PROMPTS_DIR))


def render_prompt(template_name: str, **kwargs) -> str:
    """Render a prompt template with given variables"""
    template = jinja_env.get_template(template_name)
    return template.render(**kwargs)


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    temperature: float = 0.7,
) -> str:
    """
    Call LLM API and return response text

    Supports: OpenAI, Anthropic, Mock
    """
    if settings.llm_provider == "openai":
        return await _call_openai(system_prompt, user_prompt, max_tokens, temperature)
    elif settings.llm_provider == "anthropic":
        return await _call_anthropic(
            system_prompt, user_prompt, max_tokens, temperature
        )
    elif settings.llm_provider == "mock":
        return await _call_mock(system_prompt, user_prompt, max_tokens, temperature)
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


async def _call_openai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call OpenAI API"""
    if not settings.llm_api_key:
        raise LLMError(
            ErrorCode.UNKNOWN,
            "OpenAI API 키가 설정되지 않았습니다. LLM_API_KEY 환경 변수를 설정해주세요.",
        )

    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )

        if response.status_code != 200:
            status = response.status_code
            error_code = (
                ErrorCode.LLM_TIMEOUT
                if status in {408, 429, 500, 502, 503, 504}
                else ErrorCode.UNKNOWN
            )
            logger.error(
                "OpenAI API error",
                status=status,
                body_length=len(response.text or ""),
            )
            raise LLMError(
                error_code, f"OpenAI API error: {status}"
            )

        try:
            data = response.json()
        except Exception as e:
            logger.error(
                "OpenAI response JSON parse error",
                body_length=len(response.text or ""),
            )
            raise LLMError(
                ErrorCode.LLM_JSON_INVALID,
                f"OpenAI 응답 JSON 파싱 실패: {e}",
            ) from e
        return data["choices"][0]["message"]["content"]


async def _call_mock(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Mock LLM for testing"""
    import asyncio
    import random

    await asyncio.sleep(0.1)  # Simulate API latency

    # Detect prompt type and return appropriate mock response
    # Order matters: more specific checks first
    if "학습 자료" in system_prompt or "언어 학습" in system_prompt:
        # Learning assets generation
        return json.dumps(
            {
                "source_language": "ko",
                "target_language": "en",
                "title_translation": "The Brave Rabbit's Forest Adventure",
                "pages": [
                    {
                        "page": i,
                        "translated_text": f"Page {i}: The rabbit walked through the forest, starting a new adventure. "
                        + (
                            "The heart was pounding with excitement."
                            if i == 1
                            else f"This is the story of scene {i}."
                        ),
                        "vocab": [
                            {
                                "word": "토끼",
                                "meaning": "rabbit",
                                "example": "The rabbit hopped happily.",
                            },
                            {
                                "word": "숲",
                                "meaning": "forest",
                                "example": "The forest was full of trees.",
                            },
                            {
                                "word": "모험",
                                "meaning": "adventure",
                                "example": "What an exciting adventure!",
                            },
                        ],
                        "comprehension_questions": [
                            {
                                "question": "Where did the rabbit go?",
                                "answer": "The rabbit went to the forest.",
                            }
                        ],
                        "quiz": [
                            {
                                "question": "What does '토끼' mean in English?",
                                "options": ["cat", "rabbit", "dog", "bird"],
                                "answer_index": 1,
                                "explanation": "'토끼' means 'rabbit' in English.",
                            }
                        ]
                        if i == 8
                        else [],
                    }
                    for i in range(1, 9)
                ],
                "parent_guide": {
                    "summary": "This story teaches children about courage and friendship through the adventures of a brave rabbit.",
                    "discussion_prompts": [
                        "What made the rabbit brave?",
                        "Have you ever been scared but still did something?",
                    ],
                    "activities": [
                        "Draw your own rabbit character",
                        "Act out the story with family members",
                    ],
                },
            }
        )
    elif "moderation" in system_prompt.lower() or "안전성" in system_prompt:
        return json.dumps({"is_safe": True, "reasons": [], "suggestions": []})
    elif "positive_prompt" in system_prompt or "이미지 생성 AI" in system_prompt:
        # Image prompts generation
        # 텍스트 금지 정책: 모든 negative_prompt에 텍스트 관련 토큰 필수 포함
        text_prohibition = "text, letters, words, writing, caption, subtitle, title, watermark, logo, signature, label, number, alphabet, korean text, english text, any text"
        return json.dumps(
            {
                "style": "watercolor",
                "cover": {
                    "page": 0,
                    "positive_prompt": "A cute white rabbit wearing a blue vest, standing at the entrance of a magical forest, watercolor children book illustration style, soft pastel colors, warm sunlight filtering through trees, whimsical fairy tale atmosphere, no text, textless",
                    "negative_prompt": f"{text_prohibition}, realistic, photograph, dark, scary, violence, blurry, deformed",
                    "seed": random.randint(1, 2147483647),
                    "aspect_ratio": "3:4",
                },
                "pages": [
                    {
                        "page": i,
                        "positive_prompt": f"Scene {i}: A cute white rabbit in a blue vest exploring magical forest, watercolor children book illustration, soft pastel colors, warm lighting, whimsical storybook style, no text, textless",
                        "negative_prompt": f"{text_prohibition}, realistic, photograph, dark, scary, violence, blurry, deformed",
                        "seed": random.randint(1, 2147483647),
                        "aspect_ratio": "3:4",
                    }
                    for i in range(1, 9)
                ],
            }
        )
    elif "마스터 캐릭터 시트" in system_prompt or (
        "캐릭터" in system_prompt and "시트" in system_prompt
    ):
        return json.dumps(
            {
                "character_id": "rabbit_hero_001",
                "name": "토끼",
                "master_description": "파란 조끼를 입은 귀여운 하얀 토끼로, 분홍색 코와 긴 하얀 귀가 특징입니다. 항상 밝고 호기심 가득한 표정을 짓고 있습니다.",
                "appearance": {
                    "age_visual": "어린 토끼 (인간으로 치면 6-7세)",
                    "face": "동그란 얼굴에 분홍색 코, 반짝이는 큰 검은 눈",
                    "hair": "부드러운 하얀 털로 덮여 있음",
                    "skin": "하얀 털 아래 분홍빛 피부",
                    "body": "작고 통통한 체형, 귀여운 솜털 꼬리",
                },
                "clothing": {
                    "top": "밝은 파란색 조끼",
                    "bottom": "없음 (토끼 캐릭터)",
                    "shoes": "없음 (맨발)",
                    "accessories": "없음",
                },
                "personality_traits": ["용감함", "호기심", "친절함"],
                "visual_style_notes": "수채화 스타일로 부드럽게 표현, 따뜻한 파스텔 톤 사용",
            }
        )
    elif "스토리" in system_prompt or "동화" in system_prompt:
        # Story generation
        # 요청된 언어/연령을 user_prompt 에서 감지(mock 충실도). 프롬프트는
        # "- language: en" / "- target_age: 7-9" 형태로 spec 을 그대로 담고 있어
        # 골든 하니스가 spec→story 전파를 구조 단계에서 검증할 수 있게 한다.
        # M34: 하드코딩('en','ja','ko') 대신 i18n.SUPPORTED_LANGUAGES 단일출처 — zh/es 골든이
        # mock에서 ko로 폴백해 language_matches_spec이 실패하던 false-green 제거.
        _mock_language = "ko"
        for _cand in SUPPORTED_LANGUAGES:
            if f"language: {_cand}" in user_prompt:
                _mock_language = _cand
                break
        _mock_target_age = "5-7"
        for _cand in ("3-5", "5-7", "7-9", "adult"):
            if f"target_age: {_cand}" in user_prompt:
                _mock_target_age = _cand
                break
        return json.dumps(
            {
                "title": "용감한 토끼의 숲속 모험",
                "language": _mock_language,
                "target_age": _mock_target_age,
                "theme": "감정코칭",
                "moral": "용기를 내면 무엇이든 할 수 있어요. 두려움을 이겨내면 새로운 친구를 만날 수 있답니다.",
                "characters": [
                    {
                        "id": "rabbit_hero",
                        "name": "토끼",
                        "role": "main",
                        "brief": "숲속에 사는 용감하고 호기심 많은 하얀 토끼입니다.",
                    }
                ],
                "cover": {
                    "cover_text": "용감한 토끼의 숲속 모험",
                    "scene": "햇살이 비치는 숲속 입구에서 토끼가 모험을 시작하려고 서 있습니다.",
                    "mood": "희망찬",
                    "camera": "wide shot from slightly above",
                },
                "pages": [
                    {
                        "page": i,
                        "text": f"페이지 {i}: 토끼는 숲속을 걸으며 새로운 모험을 시작했어요. "
                        + (
                            "두근두근 설레는 마음이에요."
                            if i == 1
                            else f"장면 {i}의 이야기입니다."
                        ),
                        "scene": f"숲속 장면 {i}: 토끼가 나무들 사이를 걸어가고 있습니다.",
                        "mood": "평화로운",
                        "camera": "medium shot",
                        "characters_present": ["rabbit_hero"],
                        "learning_point": "용기를 내면 새로운 것을 발견할 수 있어요"
                        if i == 8
                        else None,
                        "series_hook": "다음에는 어떤 모험이 기다리고 있을까요?"
                        if i == 8
                        else None,
                    }
                    for i in range(1, 9)
                ],
                "continuity": {
                    "character_consistency_notes": "토끼는 항상 파란 조끼를 입고 있으며 분홍색 코와 긴 하얀 귀가 특징입니다.",
                    "style_notes_for_images": "수채화 스타일, 부드러운 파스텔 톤, 따뜻한 빛, 동화책 같은 분위기",
                },
            }
        )
    else:
        return json.dumps({"result": "mock response"})


async def _call_anthropic(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call Anthropic API"""
    if not settings.llm_api_key:
        raise LLMError(
            ErrorCode.UNKNOWN,
            "Anthropic API 키가 설정되지 않았습니다. LLM_API_KEY 환경 변수를 설정해주세요.",
        )

    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.llm_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )

        if response.status_code != 200:
            status = response.status_code
            error_code = (
                ErrorCode.LLM_TIMEOUT
                if status in {408, 429, 500, 502, 503, 504}
                else ErrorCode.UNKNOWN
            )
            logger.error(
                "Anthropic API error",
                status=status,
                body_length=len(response.text or ""),
            )
            raise LLMError(
                error_code, f"Anthropic API error: {status}"
            )

        try:
            data = response.json()
        except Exception as e:
            logger.error(
                "Anthropic response JSON parse error",
                body_length=len(response.text or ""),
            )
            raise LLMError(
                ErrorCode.LLM_JSON_INVALID,
                f"Anthropic 응답 JSON 파싱 실패: {e}",
            ) from e
        return data["content"][0]["text"]


def parse_json_response(text: str, expected_type: type):
    """Parse JSON response and validate against expected type"""
    try:
        # Clean up response (remove markdown code blocks if present)
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        return expected_type.model_validate(data)
    except json.JSONDecodeError as e:
        logger.error("JSON parse error", error=str(e), text=text[:500])
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            f"JSON 파싱 실패: {str(e)}",
            raw_output=text[:500],
        )
    except Exception as e:
        logger.error("Validation error", error=str(e))
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            f"응답 검증 실패: {str(e)}",
            raw_output=text[:500],
        )


# ==================== Public API ====================


async def call_moderation(spec: BookSpec) -> ModerationResult:
    """입력 안전성 검사"""
    # M29: 사용자 언어로 reasons/suggestions를 생성하도록 language_name 전달
    # (비한국어 사용자에게 한국어 차단 사유가 노출되던 문제 해소).
    system_prompt = render_prompt(
        "moderate_input.system.jinja2",
        language_name=language_display_name(spec.language.value),
    )
    user_prompt = render_prompt(
        "moderate_input.user.jinja2",
        topic=spec.topic,
        target_age=spec.target_age.value,
        theme=spec.theme.value if spec.theme else None,
        forbidden_elements=spec.forbidden_elements or [],
        character_spec=spec.character.model_dump() if spec.character else None,
    )

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=500, temperature=0.3
    )
    return parse_json_response(response, ModerationResult)


async def call_output_moderation(text: str, language: Language) -> ModerationResult:
    """출력(생성된 책 텍스트) 안전성 검사 — LLM 기반.

    H24: orchestrator의 ko/en 키워드망이 커버하지 못하는 언어(ja/zh/es)에서
    출력 안전 게이트가 fail-open하던 공백을 메우는 폴백. mock 프로바이더는
    안전 기본값(is_safe=True)을 반환해 테스트 결정성을 유지한다.
    """
    system_prompt = render_prompt(
        "moderate_output.system.jinja2",
        language_name=language_display_name(language.value),
    )
    user_prompt = render_prompt(
        "moderate_output.user.jinja2",
        text=text,
        language=language.value,
    )
    response = await call_llm(
        system_prompt, user_prompt, max_tokens=500, temperature=0.2
    )
    return parse_json_response(response, ModerationResult)


async def load_characters_from_db(character_ids: list[str]) -> list[dict]:
    """DB에서 캐릭터 목록 로드"""
    if not character_ids:
        return []

    from src.core.database import AsyncSessionLocal
    from src.models.db import Character
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Character).where(Character.id.in_(character_ids))
        )
        characters = result.scalars().all()

        return [
            {
                "name": c.name,
                "appearance": c.master_description,
                "personality": c.personality_traits,
                # 영속된 고유 특징 — 같은 캐릭터를 날짜·책을 넘어 동일하게 유지
                "distinctive_features": c.distinctive_features,
            }
            for c in characters
        ]


async def call_story_generation(spec: BookSpec) -> StoryDraft:
    """스토리 생성"""
    # 기존 캐릭터 로드 (character_ids 또는 character_id)
    character_ids = spec.character_ids or (
        [spec.character_id] if spec.character_id else []
    )
    loaded_characters = await load_characters_from_db(character_ids)

    # character_spec과 loaded_characters 병합
    all_character_specs = []
    if spec.character:
        all_character_specs.append(spec.character.model_dump())
    all_character_specs.extend(loaded_characters)

    system_prompt = render_prompt(
        "generate_story.system.jinja2",
        page_count=spec.page_count,
        language=spec.language.value,
        language_name=language_display_name(spec.language.value),
    )
    user_prompt = render_prompt(
        "generate_story.user.jinja2",
        topic=spec.topic,
        protagonist_name=spec.protagonist_name,
        language=spec.language.value,
        target_age=spec.target_age.value,
        theme=spec.theme.value if spec.theme else None,
        style=spec.style.value,
        page_count=spec.page_count,
        character_spec=all_character_specs[0]
        if len(all_character_specs) == 1
        else None,
        character_specs=all_character_specs if len(all_character_specs) > 1 else None,
        # 다중 캐릭터일 때만 관계 힌트를 전달(남매/친구 등 역학 반영)
        character_relationship=(
            spec.character_relationship
            if len(all_character_specs) > 1
            else None
        ),
        forbidden_elements=spec.forbidden_elements or [],
    )

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=4000, temperature=0.8
    )
    return parse_json_response(response, StoryDraft)


async def call_character_sheet_generation(
    spec: BookSpec, story: StoryDraft
) -> CharacterSheet:
    """캐릭터 시트 생성"""
    system_prompt = render_prompt("generate_character_sheet.system.jinja2")
    user_prompt = render_prompt(
        "generate_character_sheet.user.jinja2",
        title=story.title,
        target_age=spec.target_age.value,
        style=spec.style.value,
        character_spec=spec.character.model_dump() if spec.character else None,
        characters=[c.model_dump() for c in story.characters],
        continuity_notes=story.continuity.character_consistency_notes,
    )

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=2000, temperature=0.7
    )
    return parse_json_response(response, CharacterSheet)


async def call_image_prompts_generation(
    spec: BookSpec, story: StoryDraft, character: CharacterSheet
) -> ImagePrompts:
    """이미지 프롬프트 생성"""
    system_prompt = render_prompt("generate_image_prompts.system.jinja2")
    user_prompt = render_prompt(
        "generate_image_prompts.user.jinja2",
        target_age=spec.target_age.value,
        style=spec.style.value,
        character_sheet=character.model_dump(),
        cover=story.cover.model_dump(),
        pages=[p.model_dump() for p in story.pages],
    )

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=4000, temperature=0.7
    )
    return parse_json_response(response, ImagePrompts)


async def call_text_rewrite(
    spec: BookSpec, story: StoryDraft, page_number: int, feedback: str
) -> dict:
    """페이지 텍스트 리라이트"""
    page = next((p for p in story.pages if p.page == page_number), None)
    if not page:
        raise ValueError(f"Page {page_number} not found")

    system_prompt = render_prompt("rewrite_page_text.system.jinja2")
    user_prompt = f"""입력:
- target_age: {spec.target_age.value}
- forbidden_elements: {spec.forbidden_elements or []}
- page: {page_number}
- original_text: {page.text}
- page_scene: {page.scene}
- book_summary: {story.title} - {story.moral}
- feedback: {feedback}

요청:
피드백을 반영해 revised_text를 작성하라."""

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=1000, temperature=0.7
    )
    # M31: raw json.loads(펜스·검증 없음) 대신 parse_json_response로 마크다운 펜스 제거 +
    # RewriteResult 스키마 검증. revised_text 누락은 LLM_JSON_INVALID로 명시 실패(조용한 no-op 제거).
    return parse_json_response(response, RewriteResult)


async def call_story_retext(
    title: str,
    pages_text: list[str],
    target_age: str,
    language: str,
) -> RetoldStory:
    """같은 이야기를 다른 연령대 본문으로 다시 쓴다(장면·삽화 재사용, 텍스트만 변경)."""
    system_prompt = render_prompt(
        "rewrite_story_for_age.system.jinja2",
        language_name=language_display_name(language),
    )
    user_prompt = render_prompt(
        "rewrite_story_for_age.user.jinja2",
        target_age=target_age,
        language=language,
        title=title,
        pages=pages_text,
    )
    response = await call_llm(
        system_prompt, user_prompt, max_tokens=3000, temperature=0.7
    )
    return parse_json_response(response, RetoldStory)


async def call_learning_assets(
    story: StoryDraft,
    source_language: Language,
    target_language: Language,
) -> LearningAssets:
    """
    학습 자산 생성 (번역 + 단어 + 이해질문 + 퀴즈 + 부모 가이드)

    Args:
        story: 생성된 스토리
        source_language: 원본 언어 (예: ko)
        target_language: 번역 대상 언어 (예: en)

    Returns:
        LearningAssets: 학습 자산 (번역, 어휘, 질문, 퀴즈, 부모 가이드)
    """
    # 언어 표시명은 i18n 단일출처를 사용(중복 맵 제거, L16). zh/es도 中文/Español로 정상 표기.
    source_lang_name = language_display_name(source_language.value)
    target_lang_name = language_display_name(target_language.value)

    system_prompt = render_prompt(
        "generate_learning_assets.system.jinja2",
        target_language=target_lang_name,
        target_age=story.target_age.value,
    )

    user_prompt = render_prompt(
        "generate_learning_assets.user.jinja2",
        title=story.title,
        source_language=source_lang_name,
        target_language=target_lang_name,
        target_age=story.target_age.value,
        moral=story.moral,
        pages=[{"page": p.page, "text": p.text} for p in story.pages],
    )

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=6000, temperature=0.7
    )
    return parse_json_response(response, LearningAssets)
