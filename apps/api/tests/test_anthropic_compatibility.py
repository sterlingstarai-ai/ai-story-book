"""Anthropic requests remain valid across legacy models and Sonnet 5."""

import json

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError, is_retryable
from src.core.exceptions import APIError
from src.services import llm
from src.services.anthropic_contract import (
    anthropic_generation_options,
    anthropic_response_text,
)
from src.services.photo_character import PhotoCharacterService


@pytest.mark.parametrize("model", [
    "claude-sonnet-5", "claude-sonnet-5-20260901",
    "claude-opus-5", "claude-opus-5-20260724",
])
def test_verified_claude_5_uses_no_sampling_and_no_default_thinking(model):
    assert anthropic_generation_options(model, temperature=0.7) == {
        "thinking": {"type": "disabled"},
    }


@pytest.mark.parametrize("model", [
    "claude-sonnet-4-6", "claude-3-5-sonnet-20241022",
    "claude-sonnet-50", "claude-sonnet-5-other", "custom-claude-sonnet-5",
])
def test_legacy_and_unknown_models_retain_existing_sampling(model):
    assert anthropic_generation_options(model, temperature=0.3) == {"temperature": 0.3}
    assert anthropic_generation_options(model) == {}


def test_response_combines_text_blocks_and_ignores_thinking():
    assert anthropic_response_text({
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "private-signature"},
            {"type": "text", "text": '{"name":'},
            {"type": "redacted_thinking", "data": "private-data"},
            {"type": "text", "text": '"별이"}'},
        ],
    }) == '{"name":"별이"}'


@pytest.mark.parametrize("payload", [
    None, [], {}, {"content": None}, {"content": []},
    {"content": [{"type": "thinking", "thinking": "private-content"}]},
    {"content": [{"type": "text", "text": " \n "}]},
    {"content": [{"type": "text", "text": 1}]},
    {"content": [{"text": "private-content"}]},
    {"content": ["private-content"]},
    {"stop_reason": ["private-content"], "content": []},
])
def test_invalid_or_textless_response_is_canonical_and_redacted(payload):
    with pytest.raises(LLMError) as caught:
        anthropic_response_text(payload)
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert "private-content" not in str(caught.value)
    assert caught.value.details["raw_output"] is None


@pytest.mark.parametrize("stop_reason,expected_code", [
    ("refusal", ErrorCode.SAFETY_OUTPUT),
    ("max_tokens", ErrorCode.LLM_JSON_INVALID),
    ("model_context_window_exceeded", ErrorCode.LLM_JSON_INVALID),
])
def test_rejected_or_truncated_json_is_never_accepted(stop_reason, expected_code):
    with pytest.raises(LLMError) as caught:
        anthropic_response_text({
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": '{"private-child-data":"complete JSON"}'}],
        })
    assert caught.value.code == expected_code
    assert "private-child-data" not in str(caught.value)
    assert caught.value.details["raw_output"] is None
    if stop_reason == "refusal":
        assert not is_retryable(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["story", "text_character"])
async def test_all_anthropic_adapters_use_sonnet_5_options_and_text_blocks(monkeypatch, operation):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_model", "claude-sonnet-5")
    monkeypatch.setattr(settings, "llm_api_key", "inert-test-key")
    requests = []
    character_payload = {
        "name": "별이",
        "master_description": "A friendly white rabbit with long ears and a red scarf.",
        "appearance": {
            "age_visual": "어린 토끼", "face": "분홍 코", "hair": "흰 털",
            "skin": "하얀 털", "body": "작은 몸과 긴 귀",
        },
        "clothing": {"top": "파란 조끼", "bottom": "없음", "shoes": "없음", "accessories": "빨간 목도리"},
        "personality_traits": ["친절함"], "visual_style_notes": "수채화",
        "distinctive_features": ["긴 귀", "빨간 목도리"],
    }
    text = json.dumps(character_payload, ensure_ascii=False) if operation == "text_character" else '{"name":"별이"}'

    async def fake_post(self, url, **kwargs):
        requests.append(kwargs["json"])
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "opaque"},
                {"type": "text", "text": text[:8]},
                {"type": "text", "text": text[8:]},
            ],
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    service = PhotoCharacterService()
    if operation == "story":
        result = await llm.call_llm("System", "User", max_tokens=384, temperature=0.7)
        assert result == '{"name":"별이"}'
        assert requests[0]["max_tokens"] == 384
    else:
        assert await service.create_character_from_text("별이", "6살", ["친절함"]) == character_payload
    assert len(requests) == 1
    assert "output_config" not in requests[0], "Generic text and character calls do not opt into a schema"
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert "temperature" not in requests[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["analyze_photo", "analyze_drawing"])
@pytest.mark.parametrize("photo_provider", ["mock", "anthropic"])
async def test_photo_analysis_never_inherits_anthropic_writing_credentials(
    monkeypatch, method, photo_provider,
):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_model", "claude-sonnet-5")
    monkeypatch.setattr(settings, "llm_api_key", "inert-writing-key")
    monkeypatch.setattr(settings, "photo_analysis_provider", photo_provider)
    monkeypatch.setattr(settings, "photo_processing_enabled", True)

    async def unexpected_post(*args, **kwargs):
        pytest.fail("Child images must not use the writing provider as a fallback")

    monkeypatch.setattr(httpx.AsyncClient, "post", unexpected_post)
    with pytest.raises(APIError) as caught:
        await getattr(PhotoCharacterService(), method)(b"inert-image")
    assert caught.value.status_code == 503
    assert caught.value.error_code == "PHOTO_PROCESSING_UNAVAILABLE"


@pytest.mark.asyncio
async def test_legacy_story_request_keeps_temperature(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_model", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "llm_api_key", "inert-test-key")

    async def fake_post(self, url, **kwargs):
        assert kwargs["json"]["temperature"] == 0.4
        assert "thinking" not in kwargs["json"]
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"ok":true}'}],
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await llm.call_llm("System", "User", temperature=0.4) == '{"ok":true}'
