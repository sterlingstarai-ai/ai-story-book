"""
LLM Service: 텍스트 생성 (스토리, 캐릭터 시트, 이미지 프롬프트)
"""
import json
import httpx
from pathlib import Path
from typing import Optional
from jinja2 import Environment, FileSystemLoader
import structlog

from src.core.config import settings
from src.core.errors import LLMError, ErrorCode, SafetyError
from src.models.dto import (
    BookSpec, StoryDraft, CharacterSheet, ImagePrompts,
    ModerationResult, Language, TargetAge
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
        return await _call_anthropic(system_prompt, user_prompt, max_tokens, temperature)
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
            logger.error("OpenAI API error", status=response.status_code, body=response.text)
            raise LLMError(
                ErrorCode.LLM_TIMEOUT,
                f"OpenAI API error: {response.status_code}"
            )

        data = response.json()
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
    if "moderation" in system_prompt.lower() or "안전성" in system_prompt:
        return json.dumps({
            "is_safe": True,
            "reasons": [],
            "suggestions": []
        })
    elif "positive_prompt" in system_prompt or "이미지 생성 AI" in system_prompt:
        # Image prompts generation
        return json.dumps({
            "style": "watercolor",
            "cover": {
                "page": 0,
                "positive_prompt": "A cute white rabbit wearing a blue vest, standing at the entrance of a magical forest, watercolor children book illustration style, soft pastel colors, warm sunlight filtering through trees, whimsical fairy tale atmosphere",
                "negative_prompt": "text, watermark, logo, realistic, photograph, dark, scary, violence",
                "seed": random.randint(1, 2147483647),
                "aspect_ratio": "3:4"
            },
            "pages": [
                {
                    "page": i,
                    "positive_prompt": f"Scene {i}: A cute white rabbit in a blue vest exploring magical forest, watercolor children book illustration, soft pastel colors, warm lighting, whimsical storybook style",
                    "negative_prompt": "text, watermark, logo, realistic, photograph, dark, scary, violence",
                    "seed": random.randint(1, 2147483647),
                    "aspect_ratio": "3:4"
                }
                for i in range(1, 9)
            ]
        })
    elif "마스터 캐릭터 시트" in system_prompt or ("캐릭터" in system_prompt and "시트" in system_prompt):
        return json.dumps({
            "character_id": "rabbit_hero_001",
            "name": "토끼",
            "master_description": "파란 조끼를 입은 귀여운 하얀 토끼로, 분홍색 코와 긴 하얀 귀가 특징입니다. 항상 밝고 호기심 가득한 표정을 짓고 있습니다.",
            "appearance": {
                "age_visual": "어린 토끼 (인간으로 치면 6-7세)",
                "face": "동그란 얼굴에 분홍색 코, 반짝이는 큰 검은 눈",
                "hair": "부드러운 하얀 털로 덮여 있음",
                "skin": "하얀 털 아래 분홍빛 피부",
                "body": "작고 통통한 체형, 귀여운 솜털 꼬리"
            },
            "clothing": {
                "top": "밝은 파란색 조끼",
                "bottom": "없음 (토끼 캐릭터)",
                "shoes": "없음 (맨발)",
                "accessories": "없음"
            },
            "personality_traits": ["용감함", "호기심", "친절함"],
            "visual_style_notes": "수채화 스타일로 부드럽게 표현, 따뜻한 파스텔 톤 사용"
        })
    elif "스토리" in system_prompt or "동화" in system_prompt:
        # Story generation
        return json.dumps({
            "title": "용감한 토끼의 숲속 모험",
            "language": "ko",
            "target_age": "5-7",
            "theme": "감정코칭",
            "moral": "용기를 내면 무엇이든 할 수 있어요. 두려움을 이겨내면 새로운 친구를 만날 수 있답니다.",
            "characters": [
                {
                    "id": "rabbit_hero",
                    "name": "토끼",
                    "role": "main",
                    "brief": "숲속에 사는 용감하고 호기심 많은 하얀 토끼입니다."
                }
            ],
            "cover": {
                "cover_text": "용감한 토끼의 숲속 모험",
                "scene": "햇살이 비치는 숲속 입구에서 토끼가 모험을 시작하려고 서 있습니다.",
                "mood": "희망찬",
                "camera": "wide shot from slightly above"
            },
            "pages": [
                {
                    "page": i,
                    "text": f"페이지 {i}: 토끼는 숲속을 걸으며 새로운 모험을 시작했어요. " + ("두근두근 설레는 마음이에요." if i == 1 else f"장면 {i}의 이야기입니다."),
                    "scene": f"숲속 장면 {i}: 토끼가 나무들 사이를 걸어가고 있습니다.",
                    "mood": "평화로운",
                    "camera": "medium shot",
                    "characters_present": ["rabbit_hero"],
                    "learning_point": "용기를 내면 새로운 것을 발견할 수 있어요" if i == 8 else None,
                    "series_hook": "다음에는 어떤 모험이 기다리고 있을까요?" if i == 8 else None
                }
                for i in range(1, 9)
            ],
            "continuity": {
                "character_consistency_notes": "토끼는 항상 파란 조끼를 입고 있으며 분홍색 코와 긴 하얀 귀가 특징입니다.",
                "style_notes_for_images": "수채화 스타일, 부드러운 파스텔 톤, 따뜻한 빛, 동화책 같은 분위기"
            }
        })
    else:
        return json.dumps({"result": "mock response"})


async def _call_anthropic(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call Anthropic API"""
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
            logger.error("Anthropic API error", status=response.status_code, body=response.text)
            raise LLMError(
                ErrorCode.LLM_TIMEOUT,
                f"Anthropic API error: {response.status_code}"
            )

        data = response.json()
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
            raw_output=text[:500]
        )
    except Exception as e:
        logger.error("Validation error", error=str(e))
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            f"응답 검증 실패: {str(e)}",
            raw_output=text[:500]
        )


# ==================== Public API ====================

async def call_moderation(spec: BookSpec) -> ModerationResult:
    """입력 안전성 검사"""
    system_prompt = render_prompt("moderate_input.system.jinja2")
    user_prompt = render_prompt(
        "moderate_input.user.jinja2",
        topic=spec.topic,
        target_age=spec.target_age.value,
        theme=spec.theme.value if spec.theme else None,
        forbidden_elements=spec.forbidden_elements or [],
        character_spec=spec.character.model_dump() if spec.character else None,
    )

    response = await call_llm(system_prompt, user_prompt, max_tokens=500, temperature=0.3)
    return parse_json_response(response, ModerationResult)


async def call_story_generation(spec: BookSpec) -> StoryDraft:
    """스토리 생성"""
    system_prompt = render_prompt(
        "generate_story.system.jinja2",
        page_count=spec.page_count
    )
    user_prompt = render_prompt(
        "generate_story.user.jinja2",
        topic=spec.topic,
        language=spec.language.value,
        target_age=spec.target_age.value,
        theme=spec.theme.value if spec.theme else None,
        style=spec.style.value,
        page_count=spec.page_count,
        character_spec=spec.character.model_dump() if spec.character else None,
        forbidden_elements=spec.forbidden_elements or [],
    )

    response = await call_llm(system_prompt, user_prompt, max_tokens=4000, temperature=0.8)
    return parse_json_response(response, StoryDraft)


async def call_character_sheet_generation(
    spec: BookSpec,
    story: StoryDraft
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

    response = await call_llm(system_prompt, user_prompt, max_tokens=2000, temperature=0.7)
    return parse_json_response(response, CharacterSheet)


async def call_image_prompts_generation(
    spec: BookSpec,
    story: StoryDraft,
    character: CharacterSheet
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

    response = await call_llm(system_prompt, user_prompt, max_tokens=4000, temperature=0.7)
    return parse_json_response(response, ImagePrompts)


async def call_text_rewrite(
    spec: BookSpec,
    story: StoryDraft,
    page_number: int,
    feedback: str
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

    response = await call_llm(system_prompt, user_prompt, max_tokens=1000, temperature=0.7)
    return json.loads(response)
