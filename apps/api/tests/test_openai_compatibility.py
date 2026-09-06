"""Official Astra/Sol request shapes and fail-closed OpenAI JSON adapters."""

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError, is_retryable
from src.services import llm, openai_contract
from src.services.openai_contract import (
    MAX_RESPONSE_OUTPUT_TOKENS,
    openai_generation_options,
    openai_request,
    openai_response_text,
)
from src.services.photo_character import PhotoCharacterService
from tests.test_photo_provider_boundary import live_configuration

MODERN_MODELS = ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6"]
PRIVATE = "private-child-data-and-provider-secret"


def completed_response():
    return {
        "status": "completed", "error": None, "incomplete_details": None,
        "output": [
            {"type": "reasoning", "encrypted_content": PRIVATE, "summary": []},
            {"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": '{"name":'},
                {"type": "output_text", "text": '"별이"}'},
            ]},
        ],
    }


@pytest.mark.parametrize("model", MODERN_MODELS)
def test_verified_models_use_stateless_responses_with_bounded_reasoning(model):
    url, body = openai_request(
        model, system_prompt="Return JSON", user_prompt="User prompt",
        max_tokens=1000, temperature=0.7,
    )
    assert url == "https://api.openai.com/v1/responses"
    assert body["model"] == model
    assert body["input"] == [
        {"role": "system", "content": "Return JSON"},
        {"role": "user", "content": "User prompt"},
    ]
    assert body["reasoning"] == {"effort": "low"}
    assert body["text"] == {"format": {"type": "json_object"}}
    assert body["store"] is False
    assert body["max_output_tokens"] == 5096
    assert not {"temperature", "max_tokens", "response_format", "messages", "tools"} & body.keys()
    assert openai_generation_options(model, max_tokens=100_000)["max_output_tokens"] == MAX_RESPONSE_OUTPUT_TOKENS


@pytest.mark.parametrize("model", [
    "gpt-4o", "gpt-4-turbo", "gpt-6-astra-pro", "gpt-6-astra-20260901",
    "gpt-6-astra-other", "custom-gpt-6-astra", "gpt-5.6-terra", "gpt-5.6-sol-other",
])
def test_legacy_and_unverified_names_do_not_inherit_new_model_options(model):
    url, body = openai_request(model, user_prompt="JSON", max_tokens=100, temperature=0.4)
    assert url.endswith("/chat/completions")
    assert body["max_tokens"] == 100
    assert body["temperature"] == 0.4
    assert body["response_format"] == {"type": "json_object"}
    assert body["store"] is False
    assert "reasoning" not in body
    assert "max_output_tokens" not in body


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, None])
def test_invalid_output_budget_is_rejected_without_echoing_values(budget):
    with pytest.raises(LLMError) as caught:
        openai_generation_options("gpt-6-astra", max_tokens=budget)
    assert caught.value.code == ErrorCode.UNKNOWN


def test_modern_response_combines_only_completed_visible_text():
    assert openai_response_text(completed_response(), model="gpt-6-astra") == '{"name":"별이"}'


INVALID_RESPONSES = [
    None, [], {}, {"status": "completed"},
    {"status": "completed", "output": []},
    {"status": "completed", "output": [None]},
    {"status": "completed", "output": [{"type": "reasoning", "summary": PRIVATE}]},
    {"status": "completed", "output": [{"type": "function_call", "arguments": PRIVATE}]},
]


@pytest.mark.parametrize("payload", INVALID_RESPONSES)
def test_malformed_or_empty_responses_are_rejected(payload):
    with pytest.raises(LLMError) as caught:
        openai_response_text(payload, model="gpt-6-astra")
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert PRIVATE not in str(caught.value)
    assert caught.value.details["raw_output"] is None


@pytest.mark.parametrize("mutation", [
    {"status": "incomplete"}, {"status": "failed"}, {"status": "queued"},
    {"status": "in_progress"}, {"status": "cancelled"}, {"status": [PRIVATE]},
    {"incomplete_details": {"reason": "max_output_tokens", "detail": PRIVATE}},
])
def test_complete_looking_json_with_incomplete_status_is_never_accepted(mutation):
    payload = completed_response()
    payload.update(mutation)
    with pytest.raises(LLMError) as caught:
        openai_response_text(payload, model="gpt-6-astra")
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("message_mutation", [
    {"status": "incomplete"}, {"role": "user"}, {"content": None},
    {"content": [PRIVATE]}, {"content": [{"type": "output_text", "text": 1}]},
    {"content": [{"type": "output_text", "text": " \n "}]},
    {"content": [{"type": "unknown", "text": PRIVATE}]},
])
def test_partial_or_malformed_message_is_rejected(message_mutation):
    payload = completed_response()
    payload["output"][1].update(message_mutation)
    with pytest.raises(LLMError) as caught:
        openai_response_text(payload, model="gpt-6-astra")
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("kind", ["refusal", "content_filter", "legacy_refusal", "legacy_filter"])
def test_refusal_never_becomes_retryable_json_failure(kind):
    payload = completed_response()
    model = "gpt-6-astra"
    if kind == "refusal":
        payload["output"][1]["content"].append({"type": "refusal", "refusal": PRIVATE})
    elif kind == "content_filter":
        payload.update(status="incomplete", incomplete_details={"reason": "content_filter"})
    else:
        model = "gpt-4o"
        payload = {"choices": [{
            "finish_reason": "content_filter" if kind == "legacy_filter" else "stop",
            "message": {"content": '{"ok":true}', "refusal": PRIVATE if kind == "legacy_refusal" else None},
        }]}
    with pytest.raises(LLMError) as caught:
        openai_response_text(payload, model=model)
    assert caught.value.code == ErrorCode.SAFETY_OUTPUT
    assert not is_retryable(caught.value)
    assert PRIVATE not in str(caught.value)
    assert caught.value.details["raw_output"] is None


@pytest.mark.parametrize("reason", ["length", "tool_calls", "unexpected", None])
def test_legacy_partial_or_unexpected_response_is_rejected(reason):
    with pytest.raises(LLMError) as caught:
        openai_response_text({"choices": [{
            "finish_reason": reason, "message": {"content": '{"ok":true}'},
        }]}, model="gpt-4o")
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID


async def invoke_adapter(operation):
    if operation == "story":
        return await llm.call_llm("Return JSON", "User prompt", max_tokens=384, temperature=0.7)
    service = PhotoCharacterService()
    if operation == "photo":
        return await service.analyze_photo(b"inert-image")
    if operation == "drawing":
        return await service.analyze_drawing(b"inert-image")
    return await service._generate_text_character_openai("Test character JSON")


@pytest.fixture
def openai_settings(monkeypatch):
    live_configuration(monkeypatch)
    monkeypatch.setattr(settings, "llm_model", "gpt-6-astra")
    monkeypatch.setattr(settings, "photo_analysis_model", "gpt-6-astra")
    monkeypatch.setattr(settings, "llm_api_key", "inert-test-key")
    monkeypatch.setattr(settings, "llm_timeout", 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", MODERN_MODELS + ["gpt-4o"])
@pytest.mark.parametrize("operation", ["story", "photo", "drawing", "text_character"])
async def test_all_openai_adapters_use_matching_api_contract(monkeypatch, openai_settings, operation, model):
    media = operation in {"photo", "drawing"}
    monkeypatch.setattr(settings, "photo_analysis_model" if media else "llm_model", model)
    requests = []

    async def fake_post(self, url, **kwargs):
        expected_key = settings.photo_analysis_api_key if media else settings.llm_api_key
        assert kwargs["headers"]["Authorization"] == f"Bearer {expected_key}"
        requests.append((url, kwargs["json"]))
        payload = completed_response() if model in MODERN_MODELS else {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"name":"별이"}'}}],
        }
        return httpx.Response(200, request=httpx.Request("POST", url), json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await invoke_adapter(operation)
    assert result == ('{"name":"별이"}' if operation == "story" else {"name": "별이"})
    assert len(requests) == 1
    url, body = requests[0]
    modern = model in MODERN_MODELS
    assert url.endswith("/responses" if modern else "/chat/completions")
    assert body["store"] is False
    assert body["model"] == model
    if modern:
        assert body["text"] == {"format": {"type": "json_object"}}, "Only call_story_generation opts in"
        assert body["reasoning"] == {"effort": "low"}
        assert "temperature" not in body
    if operation in {"photo", "drawing"}:
        content = body["input" if modern else "messages"][-1]["content"]
        assert content[0]["type"] == ("input_text" if modern else "text")
        assert content[1]["type"] == ("input_image" if modern else "image_url")
        image_url = content[1]["image_url"] if modern else content[1]["image_url"]["url"]
        assert image_url == "data:image/jpeg;base64,aW5lcnQtaW1hZ2U="


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["story", "photo", "drawing", "text_character"])
@pytest.mark.parametrize("failure,expected", [
    ("refusal", ErrorCode.SAFETY_OUTPUT), ("incomplete", ErrorCode.LLM_JSON_INVALID),
    ("invalid_json", ErrorCode.LLM_JSON_INVALID), ("provider_error", ErrorCode.UNKNOWN),
    ("http_401", ErrorCode.UNKNOWN), ("http_429", ErrorCode.LLM_TIMEOUT),
    ("timeout", ErrorCode.LLM_TIMEOUT), ("transport", ErrorCode.UNKNOWN),
])
async def test_failures_across_adapters_are_canonical_without_private_diagnostics(
    monkeypatch, openai_settings, operation, failure, expected,
):
    logs = []
    monkeypatch.setattr(openai_contract, "logger", SimpleNamespace(warning=lambda *a, **kw: logs.append((a, kw))))
    requests = []

    async def fake_post(self, url, **kwargs):
        requests.append(url)
        if failure == "timeout":
            raise httpx.ReadTimeout(PRIVATE)
        if failure == "transport":
            raise httpx.ConnectError(PRIVATE)
        request = httpx.Request("POST", url)
        if failure.startswith("http_"):
            return httpx.Response(int(failure[5:]), request=request, text=PRIVATE)
        if failure == "invalid_json":
            return httpx.Response(200, request=request, text=PRIVATE)
        payload = deepcopy(completed_response())
        if failure == "refusal":
            payload["output"][1]["content"].append({"type": "refusal", "refusal": PRIVATE})
        elif failure == "incomplete":
            payload.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        else:
            payload["error"] = {"message": PRIVATE}
        return httpx.Response(200, request=request, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(LLMError) as caught:
        await invoke_adapter(operation)
    assert len(requests) == 1
    assert caught.value.code == expected
    assert caught.value.details["raw_output"] is None
    assert PRIVATE not in str(caught.value)
    assert PRIVATE not in repr(logs)


@pytest.mark.asyncio
async def test_missing_key_fails_before_http(monkeypatch, openai_settings):
    monkeypatch.setattr(settings, "llm_api_key", None)

    async def unexpected_post(*args, **kwargs):
        pytest.fail("No request may be made without a configured key")

    monkeypatch.setattr(httpx.AsyncClient, "post", unexpected_post)
    with pytest.raises(LLMError) as caught:
        await invoke_adapter("story")
    assert caught.value.code == ErrorCode.UNKNOWN


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["photo", "drawing", "text_character"])
@pytest.mark.parametrize("content", [PRIVATE, '{"child":' + PRIVATE, "[]", "{}"])
async def test_character_content_json_failure_is_canonical_and_redacted(
    monkeypatch, openai_settings, operation, content,
):
    async def fake_post(self, url, **kwargs):
        payload = completed_response()
        payload["output"][1]["content"] = [{"type": "output_text", "text": content}]
        return httpx.Response(200, request=httpx.Request("POST", url), json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(LLMError) as caught:
        await invoke_adapter(operation)
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None
    assert PRIVATE not in str(caught.value)
    assert not hasattr(caught.value, "doc")
