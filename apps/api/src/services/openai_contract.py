"""Bounded, stateless OpenAI JSON requests and sanitized response validation.

Verified against the official Responses migration, reasoning and model guides
on 2026-09-06. Only the documented Astra/Sol aliases opt into Responses;
unverified model names retain the existing Chat Completions request shape.
"""

import base64
import binascii

import httpx
import structlog

from src.core.errors import ErrorCode, LLMError
from src.services.structured_output import provider_output_schema
from src.services.provider_runtime import (
    begin_provider_request, observe_invalid_provider_response, observe_json_output, observe_provider_response,
)

logger = structlog.get_logger()

RESPONSES_MODELS = frozenset({"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6"})
MAX_RESPONSE_OUTPUT_TOKENS = 32_000
_OUTPUT_FORMAT_NAMES = {
    "StoryDraft": "story_draft", "ImagePrompts": "image_prompts",
    "CharacterSheet": "character_sheet",
    "BookIllustrationReview": "book_illustration_review",
    "AvatarIllustrationReview": "avatar_illustration_review",
}
MAX_REVIEW_IMAGES = 13
MAX_REVIEW_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REVIEW_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024
_REVIEW_IMAGE_PREFIXES = (
    "data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,",
)


def _validate_review_images(image_urls: list[str], *, modern: bool) -> None:
    """The new multi-image seam accepts bounded inline images, never remote URLs."""
    invalid = LLMError(ErrorCode.UNKNOWN, "Invalid OpenAI multi-image input")
    if not modern or type(image_urls) is not list or not 1 <= len(image_urls) <= MAX_REVIEW_IMAGES:
        raise invalid
    total = 0
    for value in image_urls:
        if not isinstance(value, str) or not value.startswith(_REVIEW_IMAGE_PREFIXES):
            raise invalid
        encoded = value.split(",", 1)[1]
        if not encoded or len(encoded) > 4 * ((MAX_REVIEW_IMAGE_BYTES + 2) // 3):
            raise invalid
        try:
            data_size = len(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error):
            raise invalid from None
        total += data_size
        if not 0 < data_size <= MAX_REVIEW_IMAGE_BYTES or total > MAX_REVIEW_TOTAL_IMAGE_BYTES:
            raise invalid


def openai_generation_options(
    model: str, *, max_tokens: int, temperature: float | None = None,
    response_schema: dict | None = None,
) -> dict:
    if type(max_tokens) is not int or max_tokens < 1:
        raise LLMError(ErrorCode.UNKNOWN, "Invalid OpenAI output budget")
    if model in RESPONSES_MODELS:
        output_format = {"type": "json_object"}
        if response_schema is not None:
            # Names come only from the fixed DTO registry, never user text/keys.
            schema_title = response_schema.get("title")
            if not isinstance(schema_title, str) or schema_title not in _OUTPUT_FORMAT_NAMES:
                raise LLMError(ErrorCode.UNKNOWN, "Unsupported OpenAI output schema")
            output_format = {
                "type": "json_schema", "name": _OUTPUT_FORMAT_NAMES[schema_title], "strict": True,
                "schema": provider_output_schema(response_schema, provider="openai"),
            }
        # Responses counts reasoning and visible output together. This local
        # ceiling bounds each paid request; it is not the model's maximum.
        return {
            "max_output_tokens": min(
                MAX_RESPONSE_OUTPUT_TOKENS,
                max_tokens + max(4096, max_tokens),
            ),
            "reasoning": {"effort": "low"},
            "text": {"format": output_format},
            "store": False,
        }
    return {
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "store": False,
        **({} if temperature is None else {"temperature": temperature}),
    }


def openai_request(
    model: str, *, user_prompt: str, max_tokens: int,
    system_prompt: str | None = None, temperature: float | None = None,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    response_schema: dict | None = None,
) -> tuple[str, dict]:
    """Build either API shape without retaining prompts or image data."""
    modern = model in RESPONSES_MODELS
    content: str | list = user_prompt
    if image_urls is not None:
        if image_url is not None:
            raise LLMError(ErrorCode.UNKNOWN, "Conflicting OpenAI image inputs")
        _validate_review_images(image_urls, modern=modern)
        content = [{"type": "input_text", "text": user_prompt}]
        for page_number, inline_image in enumerate(image_urls):
            content.extend([
                {"type": "input_text", "text": f"page{page_number}"},
                {"type": "input_image", "image_url": inline_image, "detail": "high"},
            ])
    elif image_url is not None:
        content = (
            [{"type": "input_text", "text": user_prompt},
             {"type": "input_image", "image_url": image_url}]
            if modern else
            [{"type": "text", "text": user_prompt},
             {"type": "image_url", "image_url": {"url": image_url}}]
        )
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})
    return (
        "https://api.openai.com/v1/responses" if modern
        else "https://api.openai.com/v1/chat/completions",
        {
            "model": model,
            "input" if modern else "messages": messages,
            **openai_generation_options(
                model, max_tokens=max_tokens, temperature=temperature,
                response_schema=response_schema,
            ),
        },
    )


def _invalid_response() -> LLMError:
    return LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid or incomplete OpenAI response")


def _refusal() -> LLMError:
    return LLMError(ErrorCode.SAFETY_OUTPUT, "AI 제공자가 콘텐츠 생성을 거절했습니다.")


def openai_response_text(data: object, *, model: str) -> str:
    """Accept completed assistant text only, never partial/refused/tool output."""
    if not isinstance(data, dict):
        raise _invalid_response()
    if data.get("error") is not None:
        raise LLMError(ErrorCode.UNKNOWN, "OpenAI response failed")

    if model not in RESPONSES_MODELS:
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise _invalid_response()
        choice = choices[0]
        if not isinstance(choice, dict):
            raise _invalid_response()
        message = choice.get("message")
        if not isinstance(message, dict):
            raise _invalid_response()
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise _refusal()
        if choice.get("finish_reason") != "stop" or message.get("tool_calls"):
            raise _invalid_response()
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise _invalid_response()
        return text

    incomplete = data.get("incomplete_details")
    if isinstance(incomplete, dict) and incomplete.get("reason") == "content_filter":
        raise _refusal()
    if data.get("status") != "completed" or incomplete is not None:
        raise _invalid_response()
    output = data.get("output")
    if not isinstance(output, list):
        raise _invalid_response()
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise _invalid_response()
        if item.get("type") == "reasoning":
            continue
        if (item.get("type") != "message" or item.get("role") != "assistant"
                or item.get("status") != "completed"):
            raise _invalid_response()
        content = item.get("content")
        if not isinstance(content, list):
            raise _invalid_response()
        for block in content:
            if not isinstance(block, dict):
                raise _invalid_response()
            if block.get("type") == "refusal":
                raise _refusal()
            if block.get("type") != "output_text" or not isinstance(block.get("text"), str):
                raise _invalid_response()
            texts.append(block["text"])
    text = "".join(texts)
    if not text.strip():
        raise _invalid_response()
    return text


async def request_openai_json(
    *, model: str, api_key: str | None, timeout: float, user_prompt: str,
    max_tokens: int, system_prompt: str | None = None,
    temperature: float | None = None, image_url: str | None = None,
    image_urls: list[str] | None = None,
    response_schema: dict | None = None,
) -> str:
    """Single bounded HTTP attempt; retry policy belongs to the caller."""
    if not api_key:
        raise LLMError(ErrorCode.UNKNOWN, "OpenAI API 키가 설정되지 않았습니다.")
    url, payload = openai_request(
        model, user_prompt=user_prompt, system_prompt=system_prompt,
        max_tokens=max_tokens, temperature=temperature, image_url=image_url,
        image_urls=image_urls,
        response_schema=response_schema,
    )
    attempt = begin_provider_request("openai", model, "llm", api_key)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except (httpx.TimeoutException, TimeoutError):
        logger.warning("OpenAI request timed out")
        raise LLMError(ErrorCode.LLM_TIMEOUT, "OpenAI request timed out") from None
    except httpx.HTTPError:
        logger.warning("OpenAI transport failed")
        raise LLMError(ErrorCode.UNKNOWN, "OpenAI transport failed") from None
    permanent_error = await observe_provider_response(attempt, response, defer_success=True)
    if permanent_error:
        raise LLMError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.")
    if response.status_code != 200:
        status = response.status_code
        logger.warning("OpenAI request failed", status=status)
        code = ErrorCode.LLM_TIMEOUT if status in {408, 429, 500, 502, 503, 504} else ErrorCode.UNKNOWN
        raise LLMError(code, "OpenAI request failed")
    try:
        data = response.json()
        text = openai_response_text(data, model=model)
    except ValueError:
        await observe_invalid_provider_response(attempt)
        logger.warning("OpenAI response JSON invalid")
        raise _invalid_response() from None
    except LLMError:
        await observe_invalid_provider_response(attempt)
        raise
    await observe_json_output(attempt, text)
    return text
