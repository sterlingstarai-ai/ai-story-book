"""Shared request and response contract for Anthropic structured text tasks."""

import re

from src.core.errors import ErrorCode, LLMError


def anthropic_generation_options(
    model: str, *, temperature: float | None = None,
) -> dict:
    """Keep legacy sampling while bounding the verified Claude 5 JSON tasks.

    Sonnet 5 and Opus 5 enable thinking by default. Both accept disabled thinking
    at their default effort; omit sampling overrides on these verified models.
    Do not extrapolate to Fable models, whose thinking is always on.
    """
    if re.fullmatch(r"claude-(?:sonnet|opus)-5(?:-\d{8})?", model):
        return {"thinking": {"type": "disabled"}}
    return {} if temperature is None else {"temperature": temperature}


def anthropic_response_text(data: object) -> str:
    """Extract only text blocks, refusing partial or provider-rejected output."""
    if not isinstance(data, dict):
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid Anthropic response")
    stop_reason = data.get("stop_reason")
    if stop_reason is not None and not isinstance(stop_reason, str):
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid Anthropic stop reason")
    if stop_reason == "refusal":
        raise LLMError(ErrorCode.SAFETY_OUTPUT, "AI 제공자가 콘텐츠 생성을 거절했습니다.")
    if stop_reason in {"max_tokens", "model_context_window_exceeded"}:
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "Anthropic response was truncated")

    content = data.get("content")
    if not isinstance(content, list):
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid Anthropic content blocks")
    texts = []
    for block in content:
        if not isinstance(block, dict):
            raise LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid Anthropic content block")
        if block.get("type") == "text":
            value = block.get("text")
            if not isinstance(value, str):
                raise LLMError(ErrorCode.LLM_JSON_INVALID, "Invalid Anthropic text block")
            texts.append(value)
    text = "".join(texts)
    if not text.strip():
        raise LLMError(ErrorCode.LLM_JSON_INVALID, "Anthropic response contained no text")
    return text
