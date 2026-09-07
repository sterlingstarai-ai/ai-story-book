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
from src.services.anthropic_contract import (
    anthropic_generation_options,
    anthropic_response_text,
)
from src.services.story_integrity import (
    validate_generated_text_unicode,
    validate_story_integrity,
)
from src.services.structured_output import (
    ANTHROPIC_SCHEMA_MODELS,
    provider_output_schema,
)
from src.services.openai_contract import request_openai_json
from src.services.provider_runtime import begin_provider_request, observe_provider_response
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
# JSON is provider input, not ASCII-only transport. Unicode escapes substantially
# inflate Korean/Japanese story prompts without adding information.
jinja_env.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}


def render_prompt(template_name: str, **kwargs) -> str:
    """Render a prompt template with given variables"""
    template = jinja_env.get_template(template_name)
    return template.render(**kwargs)


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4000,
    temperature: float = 0.7,
    *,
    response_schema: dict | None = None,
) -> str:
    """
    Call LLM API and return response text

    Supports: OpenAI, Anthropic, Gemini, Mock
    """
    if settings.llm_provider == "openai":
        return await _call_openai(
            system_prompt, user_prompt, max_tokens, temperature,
            response_schema=response_schema,
        )
    elif settings.llm_provider == "anthropic":
        return await _call_anthropic(
            system_prompt, user_prompt, max_tokens, temperature,
            response_schema=response_schema,
        )
    elif settings.llm_provider == "gemini":
        return await _call_gemini(system_prompt, user_prompt, max_tokens, temperature)
    elif settings.llm_provider == "mock":
        return await _call_mock(system_prompt, user_prompt, max_tokens, temperature)
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


async def _call_openai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    *,
    response_schema: dict | None = None,
) -> str:
    """Call the shared stateless OpenAI JSON adapter."""
    return await request_openai_json(
        model=settings.llm_model, api_key=settings.llm_api_key,
        timeout=settings.llm_timeout, system_prompt=system_prompt,
        user_prompt=user_prompt, max_tokens=max_tokens, temperature=temperature,
        response_schema=response_schema,
    )


async def _call_mock(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Mock LLM for testing"""
    import asyncio
    import random
    import re

    await asyncio.sleep(0.1)  # Simulate API latency

    # Exercise the requested length through story, illustration, and learning
    # stages. A fixed eight-page mock hid truncated twelve-page books in QA.
    mock_page_count = 8
    count_match = re.search(r"^- page_count: (\d+)\s*$", user_prompt, re.MULTILINE)
    pages_match = re.search(r"^- story_pages: (\[.*\])$", user_prompt, re.MULTILINE)
    learning_pages = re.findall(r"^### 페이지 (\d+)\s*$", user_prompt, re.MULTILINE)
    if count_match:
        mock_page_count = int(count_match.group(1))
    elif pages_match:
        mock_page_count = len(json.loads(pages_match.group(1)))
    elif learning_pages:
        mock_page_count = len(learning_pages)

    # Detect prompt type and return appropriate mock response
    # Order matters: more specific checks first
    if '"title_translation"' in system_prompt and '"translated_text"' in system_prompt:
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
                        if i == mock_page_count
                        else [],
                    }
                    for i in range(1, mock_page_count + 1)
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
                    for i in range(1, mock_page_count + 1)
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
    elif "revised_text" in system_prompt and "original_text" in user_prompt:
        # 페이지 텍스트 재작성(rewrite_page_text). 이 분기가 없으면 '스토리' 분기에 걸려
        # StoryDraft 모양이 나오고 RewriteResult 검증이 실패한다 — 그런데 엔드포인트는
        # 잡 등록 200 만 돌려주므로 **조용히 실패**한다(S1: 중간 E2E 매트릭스 #12/#22 가
        # 두 라운드 연속 false-pass 였던 이유). 페이지 번호는 반드시 보존한다.
        import re as _re

        _page_match = _re.search(r"- page:\s*(\d+)", user_prompt)
        _page_no = int(_page_match.group(1)) if _page_match else 1
        _original_match = _re.search(r"- original_text:\s*(.*)", user_prompt)
        _original = (
            _original_match.group(1).strip() if _original_match else "원본 문장"
        )
        _feedback_match = _re.search(r"- feedback:\s*(.*)", user_prompt)
        _feedback = (
            _feedback_match.group(1).strip() if _feedback_match else ""
        )
        # 재작성이 실제로 일어났는지 호출자가 확인할 수 있도록 원문과 **다른** 텍스트를 낸다.
        _revised = f"[다시 씀] {_original}"
        if _feedback and _feedback.lower() not in ("none", "null"):
            _revised = f"{_revised} ({_feedback})"
        return json.dumps(
            {
                "page": _page_no,
                "revised_text": _revised[:600],
                "notes": "mock rewrite",
            },
            ensure_ascii=False,
        )

    elif "original_pages" in user_prompt or "연령대(target_age)" in system_prompt:
        # 연령 리텔링(rewrite_story_for_age). 이 분기가 없으면 아래 fallback
        # {"result": "mock response"} 로 떨어져 RetoldStory 검증이 실패하고, retell 이
        # mock 구성에서 **항상 500** 이 된다(M3). 페이지 수는 원본과 정확히 같아야 한다
        # (같은 삽화를 재사용하는 계약).
        import re as _re

        title_match = _re.search(r"- original_title:\s*(.+)", user_prompt)
        pages_match = _re.search(
            r"- original_pages:\s*(\[.*?\])\s*(?:\n\S|\n\n|$)", user_prompt, _re.S
        )
        original_pages: list = []
        if pages_match:
            try:
                original_pages = json.loads(pages_match.group(1))
            except Exception:
                original_pages = []
        if not original_pages:
            original_pages = ["페이지 1"]

        _retell_age = "5-7"
        for _cand in ("3-5", "5-7", "7-9", "adult"):
            if f"target_age: {_cand}" in user_prompt:
                _retell_age = _cand
                break

        _base_title = (
            title_match.group(1).strip() if title_match else "다시 쓴 이야기"
        )
        _suffix = f" ({_retell_age})"
        _title = (_base_title[: 80 - len(_suffix)] + _suffix)[:80]
        return json.dumps(
            {
                "title": _title,
                "pages": [
                    f"[{_retell_age}] {str(page).strip()}"[:600]
                    for page in original_pages
                ],
            },
            ensure_ascii=False,
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
                        if i == mock_page_count
                        else None,
                        "series_hook": "다음에는 어떤 모험이 기다리고 있을까요?"
                        if i == mock_page_count
                        else None,
                    }
                    for i in range(1, mock_page_count + 1)
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
    *,
    response_schema: dict | None = None,
) -> str:
    """Call Anthropic API"""
    if not settings.llm_api_key:
        raise LLMError(
            ErrorCode.UNKNOWN,
            "Anthropic API 키가 설정되지 않았습니다. LLM_API_KEY 환경 변수를 설정해주세요.",
        )

    output_options = {}
    if response_schema is not None and settings.llm_model in ANTHROPIC_SCHEMA_MODELS:
        output_options = {"output_config": {"format": {
            "type": "json_schema",
            "schema": provider_output_schema(response_schema, provider="anthropic"),
        }}}

    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        attempt = begin_provider_request(settings.llm_provider, settings.llm_model, "llm", settings.llm_api_key)
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
                **anthropic_generation_options(settings.llm_model, temperature=temperature),
                **output_options,
            },
        )

        permanent_error = await observe_provider_response(attempt, response)
        if permanent_error:
            raise LLMError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.")
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
                "Anthropic 응답 JSON 파싱 실패",
            ) from e
        return anthropic_response_text(data)


# Gemini 텍스트(LLM) 엔드포인트. 이미지(image.py)와 같은 Generative Language API지만
# 모델은 LLM_MODEL(예: gemini-3.1-flash / gemini-3-pro)로, IMAGE_MODEL과 별개다.
_GEMINI_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


async def _call_gemini(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    *,
    image_base64: str | None = None,
    image_mime_type: str = "image/jpeg",
) -> str:
    """Call Google Gemini API (텍스트 LLM).

    responseMimeType='application/json' 으로 JSON 출력을 강제해 OpenAI json_object
    모드와 동등한 안정성을 얻는다. 안전 차단(finishReason=SAFETY) 시 candidate에 parts가
    없을 수 있어 추출을 방어적으로 감싸 재시도 가능한 LLM_JSON_INVALID로 표면화한다.
    """
    if not settings.llm_api_key:
        raise LLMError(
            ErrorCode.UNKNOWN,
            "Gemini API 키가 설정되지 않았습니다. LLM_API_KEY 환경 변수를 설정해주세요.",
        )

    parts = [{"text": user_prompt}]
    if image_base64:
        parts.append({"inlineData": {"mimeType": image_mime_type, "data": image_base64}})

    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        attempt = begin_provider_request(settings.llm_provider, settings.llm_model, "llm", settings.llm_api_key)
        response = await client.post(
            f"{_GEMINI_LLM_BASE_URL}/{settings.llm_model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": settings.llm_api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                },
            },
        )

        permanent_error = await observe_provider_response(attempt, response)
        if permanent_error:
            raise LLMError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.")
        if response.status_code != 200:
            status = response.status_code
            error_code = (
                ErrorCode.LLM_TIMEOUT
                if status in {408, 429, 500, 502, 503, 504}
                else ErrorCode.UNKNOWN
            )
            logger.error(
                "Gemini API error",
                status=status,
                body_length=len(response.text or ""),
            )
            raise LLMError(error_code, f"Gemini API error: {status}")

        try:
            data = response.json()
        except Exception as e:
            logger.error(
                "Gemini response JSON parse error",
                body_length=len(response.text or ""),
            )
            raise LLMError(
                ErrorCode.LLM_JSON_INVALID,
                f"Gemini 응답 JSON 파싱 실패: {e}",
            ) from e

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            # 안전 차단·빈 candidate 등 예상 외 형식 — 재시도 가능한 에러로.
            finish = None
            try:
                finish = data["candidates"][0].get("finishReason")
            except (KeyError, IndexError, TypeError):
                pass
            logger.error("Gemini response shape unexpected", finish_reason=finish)
            raise LLMError(
                ErrorCode.LLM_JSON_INVALID,
                f"Gemini 응답 형식이 예상과 다릅니다(finishReason={finish})",
            ) from e


def parse_json_response(text: str, expected_type: type):
    """Validate provider JSON with schema-only diagnostics, never child content."""
    from types import UnionType
    from typing import Union, get_args, get_origin

    from pydantic import BaseModel, ValidationError
    from pydantic_core import ErrorType

    from src.models import dto as owned_models

    known_types = frozenset(get_args(ErrorType))
    owned = (
        isinstance(expected_type, type)
        and issubclass(expected_type, BaseModel)
        and getattr(owned_models, expected_type.__name__, None) is expected_type
    )
    model_name = expected_type.__name__ if owned else "unknown_model"

    def alternatives(annotations):
        for annotation in annotations:
            if get_origin(annotation) in (Union, UnionType):
                yield from alternatives(get_args(annotation))
            else:
                yield annotation

    def owned_field_path(location):
        # Loc may include provider-chosen extra fields, dictionary keys or union
        # labels. Only copy names found in this exact owned model's field tree.
        annotations = [expected_type] if owned else []
        parts = []
        for part in location:
            candidates = list(alternatives(annotations))
            if isinstance(part, int) and not isinstance(part, bool):
                annotations = [
                    get_args(annotation)[0]
                    for annotation in candidates
                    if get_origin(annotation) in (list, tuple) and get_args(annotation)
                ]
                if not annotations or not parts:
                    break
                parts[-1] += "[]"
            elif isinstance(part, str):
                fields = [
                    annotation.model_fields[part]
                    for annotation in candidates
                    if isinstance(annotation, type)
                    and issubclass(annotation, BaseModel)
                    and getattr(owned_models, annotation.__name__, None) is annotation
                    and part in annotation.model_fields
                ]
                if not fields:
                    break
                parts.append(part)
                annotations = [field.annotation for field in fields]
            else:
                break
        return ".".join(parts) or "$"

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
    except json.JSONDecodeError:
        logger.error(
            "LLM response JSON invalid",
            schema_model=model_name,
            schema_diagnostics=[{"field_path": "$", "validation_type": "json_invalid"}],
        )
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            "AI 응답 JSON 형식이 올바르지 않습니다.",
        ) from None
    except ValidationError as exc:
        diagnostics = []
        seen = set()
        for item in exc.errors(include_url=False, include_context=False, include_input=False):
            error_type = item.get("type")
            # Custom validator error types are not necessarily static strings.
            # Unknown types get a fixed marker, never the supplied type/message.
            if error_type not in known_types:
                error_type = "unknown_validation_error"
            entry = (owned_field_path(item.get("loc", ())), error_type)
            if entry not in seen:
                seen.add(entry)
                diagnostics.append({"field_path": entry[0], "validation_type": entry[1]})
            if len(diagnostics) >= 20:
                break
        logger.error(
            "LLM response schema invalid",
            schema_model=model_name,
            schema_error_count=exc.error_count(),
            schema_diagnostics=diagnostics,
        )
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            "AI 응답이 이야기 형식에 맞지 않습니다.",
        ) from None
    except Exception:
        logger.error("LLM response validation unavailable", schema_model=model_name)
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            "AI 응답 형식을 확인할 수 없습니다.",
        ) from None


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
        by_id = {character.id: character for character in result.scalars().all()}
        # SQL IN does not preserve selection order. The first selected character
        # is the protagonist, including when text companions accompany a portrait.
        characters = [by_id[cid] for cid in dict.fromkeys(character_ids) if cid in by_id]

        return [
            {
                "name": c.name,
                "appearance": c.master_description,
                "appearance_details": c.appearance,
                "clothing": c.clothing,
                "visual_style_notes": c.visual_style_notes,
                "identity_locked": bool(c.from_photo and c.avatar_status == "approved"),
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
    if loaded_characters and loaded_characters[0].get("identity_locked"):
        # An optional free-text companion cannot displace the approved protagonist.
        all_character_specs = [*loaded_characters, *([spec.character.model_dump()] if spec.character else [])]

    system_prompt = render_prompt(
        "generate_story.system.jinja2",
        page_count=spec.page_count,
        language=spec.language.value,
        language_name=language_display_name(spec.language.value),
    )
    if any(character.get("identity_locked") for character in loaded_characters):
        system_prompt += (
            "\nFor a supplied character with identity_locked=true, the parent has already "
            "approved that character. Preserve the supplied name, appearance_details, "
            "clothing (including each garment's color), distinctive_features and visual_style_notes. "
            "Do not redesign, re-age or change the character's everyday outfit for a new book, "
            "theme or style. Only the scene, actions, poses and expressions may change. "
            "The first supplied character is the protagonist."
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
        system_prompt, user_prompt, max_tokens=max(4000, spec.page_count * 600), temperature=0.8,
        response_schema=StoryDraft.model_json_schema(),
    )
    story = parse_json_response(response, StoryDraft)
    if [page.page for page in story.pages] != list(range(1, spec.page_count + 1)):
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "요청한 분량의 이야기를 완성하지 못했습니다.")
    validate_story_integrity(
        story, spec, supplied_character_names=[character["name"] for character in loaded_characters]
    )
    return story


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
        story_characters=[c.model_dump() for c in story.characters],
        cover=story.cover.model_dump(),
        pages=[p.model_dump() for p in story.pages],
    )

    response = await call_llm(
        system_prompt, user_prompt, max_tokens=max(4000, (len(story.pages) + 1) * 600), temperature=0.7,
        response_schema=ImagePrompts.model_json_schema(),
    )
    prompts = parse_json_response(response, ImagePrompts)
    if sorted(page.page for page in prompts.pages) != list(range(1, len(story.pages) + 1)):
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "모든 본문 쪽의 그림 준비를 완성하지 못했습니다.")
    return prompts


async def call_text_rewrite(
    spec: BookSpec, story: StoryDraft, page_number: int, feedback: str
) -> dict:
    """페이지 텍스트 리라이트"""
    page = next((p for p in story.pages if p.page == page_number), None)
    if not page:
        raise ValueError(f"Page {page_number} not found")

    # H23: 책 언어를 프롬프트에 전달(generate_story 패턴 미러) — 비한국어 책이 재작성 시
    # 한국어로 회귀하던 문제 차단.
    system_prompt = render_prompt(
        "rewrite_page_text.system.jinja2",
        language=spec.language.value,
        language_name=language_display_name(spec.language.value),
    )
    user_prompt = f"""입력:
- language: {spec.language.value}
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
    result = parse_json_response(response, RewriteResult)
    validate_generated_text_unicode(result)
    return result


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
        system_prompt, user_prompt, max_tokens=max(3000, len(pages_text) * 600), temperature=0.7
    )
    result = parse_json_response(response, RetoldStory)
    validate_generated_text_unicode(result)
    return result


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
        system_prompt, user_prompt, max_tokens=max(6000, len(story.pages) * 750), temperature=0.7
    )
    result = parse_json_response(response, LearningAssets)
    validate_generated_text_unicode(result)
    return result
