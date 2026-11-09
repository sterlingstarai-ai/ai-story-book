"""Story requests use native schemas; local validation stays authoritative."""

from copy import deepcopy
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError
from src.models.dto import BookSpec, Language, StoryDraft
from src.services import llm, openai_contract, story_integrity
from src.services.structured_output import provider_output_schema
from tests.test_llm_schema_diagnostics import valid_story

PRIVATE = "PRIVATE_CHILD_NAME_AND_REFERENCE"
SUPPORTED = [
    ("anthropic", "claude-sonnet-5"), ("anthropic", "claude-opus-5"),
    ("openai", "gpt-6-astra"), ("openai", "gpt-5.6-sol"), ("openai", "gpt-5.6"),
]


def _spec():
    return BookSpec(topic="함께 책 읽기 " + PRIVATE, protagonist_name=PRIVATE,
                    target_age="7-9", style="watercolor", page_count=4)


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_words", [37, 39, 40])
async def test_korean_twelve_page_story_repairs_only_the_length_deficit(monkeypatch, repair_words):
    payload = valid_story()
    original_page = payload["pages"][0]
    long_text = " ".join(["이야기"] * 40)
    short_text = " ".join(["이야기"] * 37) + " !"
    payload.update(language="ko", target_age="7-9", pages=[
        {**original_page, "page": number, "text": long_text if number <= 8 else short_text}
        for number in range(1, 13)
    ])
    call = AsyncMock(side_effect=[
        json.dumps(payload, ensure_ascii=False),
        json.dumps({"pages": [{"page": 9, "revised_text": " ".join(["관찰"] * repair_words)}]}, ensure_ascii=False),
    ])
    monkeypatch.setattr(llm, "call_llm", call)
    spec = _spec().model_copy(update={"page_count": 12})
    if repair_words == 37:
        with pytest.raises(LLMError) as error:
            await llm.call_story_generation(spec)
        assert error.value.code == ErrorCode.LLM_JSON_INVALID
    else:
        result = await llm.call_story_generation(spec)
        assert story_integrity.count_story_words(result.pages[8].text) == repair_words
        assert [page.scene for page in result.pages] == [page["scene"] for page in payload["pages"]]
        assert [page.text for page in result.pages if page.page != 9] == [
            page["text"] for page in payload["pages"] if page["page"] != 9
        ]
    assert call.await_count == 2
    system = call.await_args_list[0].args[0]
    assert "누가 드는지 명시" in system
    assert "시작 또는 결과 중 한 순간만" in system
    assert json.loads(call.await_args.args[1])["target_pages"] == [9]
    options = openai_contract.openai_generation_options(
        "gpt-5.6-sol", max_tokens=1800, response_schema=call.await_args.kwargs["response_schema"],
    )
    assert options["text"]["format"]["name"] == "story_length_repair"
    assert options["text"]["format"]["strict"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("near_miss_words", [38, 39])
async def test_korean_twelve_page_story_accepts_one_close_page_without_extra_call(monkeypatch, near_miss_words):
    payload = valid_story()
    original_page = payload["pages"][0]
    payload.update(language="ko", target_age="7-9", pages=[
        {**original_page, "page": number, "text": " ".join(["이야기"] * word_count)}
        for number, word_count in enumerate([40] * 8 + [near_miss_words, 32, 32, 32], start=1)
    ])
    call = AsyncMock(return_value=json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(llm, "call_llm", call)

    result = await llm.call_story_generation(_spec().model_copy(update={"page_count": 12}))

    assert [page.text for page in result.pages] == [page["text"] for page in payload["pages"]]
    call.assert_awaited_once()


def _schema_nodes(schema):
    yield schema
    for group in ("properties", "$defs"):
        for child in schema.get(group, {}).values():
            yield from _schema_nodes(child)
    if "items" in schema:
        yield from _schema_nodes(schema["items"])
    for child in schema.get("anyOf", []):
        yield from _schema_nodes(child)


def _body(provider, model, draft):
    text = json.dumps(draft, ensure_ascii=False)
    if provider == "anthropic":
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}
    if model in openai_contract.RESPONSES_MODELS:
        return {"status": "completed", "output": [{
            "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text}],
        }]}
    return {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}


def _mock_provider(monkeypatch, provider, model, draft, *, status=200):
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(settings, "llm_api_key", "inert-provider-secret")
    requests = []

    async def post(self, url, **kwargs):
        requests.append((url, kwargs["json"]))
        response = _body(provider, model, draft) if status == 200 else {"message": PRIVATE}
        return httpx.Response(status, request=httpx.Request("POST", url), json=response)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return requests


@pytest.mark.asyncio
async def test_twelve_page_learning_assets_fit_openai_acceptance_request_budget(monkeypatch):
    payload = valid_story()
    payload["pages"] = [{**payload["pages"][0], "page": n} for n in range(1, 13)]
    story = StoryDraft.model_validate(payload)
    requests = _mock_provider(monkeypatch, "openai", "gpt-5.6-sol", {
        "source_language": "ko",
        "target_language": "en",
        "title_translation": "A new story",
        "pages": [{"page": n, "translated_text": "A friend came to the garden."} for n in range(1, 13)],
        "parent_guide": {"summary": "A day in the garden.", "discussion_prompts": [], "activities": []},
    })

    assets = await llm.call_learning_assets(story, Language.ko, Language.en)

    assert [page.page for page in assets.pages] == list(range(1, 13))
    assert len(requests) == 1
    assert requests[0][1]["max_output_tokens"] == 16_000


def test_wire_schemas_preserve_canonical_constraints_and_owned_field_names():
    original = StoryDraft.model_json_schema()
    before = deepcopy(original)
    anthropic = provider_output_schema(original, provider="anthropic")
    openai = provider_output_schema(original, provider="openai")
    assert original == before
    assert len(list(_schema_nodes(original))) == len(list(_schema_nodes(anthropic)))
    for node in _schema_nodes(anthropic):
        assert not {"minimum", "maximum", "minLength", "maxLength", "maxItems"} & node.keys()
        assert node.get("minItems", 0) <= 1
        if "properties" in node:
            assert node["additionalProperties"] is False
    page = anthropic["$defs"]["StoryPage"]
    assert "characters_present" in page["required"]
    assert page["properties"]["characters_present"]["minItems"] == 1
    assert "theme" not in anthropic["required"]
    assert "learning_point" not in page["required"]
    for node in _schema_nodes(openai):
        if "properties" in node:
            assert node["required"] == list(node["properties"])
            assert node["additionalProperties"] is False
        assert "default" not in node
    for field in (openai["properties"]["theme"],
                  openai["$defs"]["StoryPage"]["properties"]["learning_point"],
                  openai["$defs"]["StoryPage"]["properties"]["series_hook"]):
        assert {"type": "null"} in field["anyOf"]
    assert original["$defs"]["StoryPage"]["properties"]["text"]["maxLength"] == 600
    assert openai["$defs"]["StoryPage"]["properties"]["text"]["maxLength"] == 600
    anthropic["$defs"]["StoryPage"]["required"].clear()
    assert "characters_present" in original["$defs"]["StoryPage"]["required"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", SUPPORTED)
async def test_story_request_transmits_native_schema_without_user_values(monkeypatch, provider, model):
    requests = _mock_provider(monkeypatch, provider, model, valid_story())
    result = await llm.call_story_generation(_spec())
    assert result.model_dump() == StoryDraft.model_validate(valid_story()).model_dump()
    assert len(requests) == 1
    url, request = requests[0]
    if provider == "anthropic":
        assert url == "https://api.anthropic.com/v1/messages"
        output = request["output_config"]["format"]
        assert set(output) == {"type", "schema"}
        assert request["thinking"] == {"type": "disabled"}
        assert "temperature" not in request
    else:
        assert url == "https://api.openai.com/v1/responses"
        output = request["text"]["format"]
        assert output["strict"] is True
        assert output["name"] == "story_draft"
        assert request["store"] is False
    assert output["type"] == "json_schema"
    assert "characters_present" in output["schema"]["$defs"]["StoryPage"]["required"]
    serialized = json.dumps(output, ensure_ascii=False)
    assert PRIVATE not in serialized
    assert "inert-provider-secret" not in serialized
    # Schemas are identical across user topics/names. Private values stay in prompts.
    assert "PRIVATE_" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [
    ("anthropic", "claude-sonnet-5-20260901"), ("anthropic", "claude-sonnet-4-6"),
    ("anthropic", "custom-claude-opus-5"), ("openai", "gpt-6-astra-20260901"),
    ("openai", "gpt-6-astra-pro"), ("openai", "gpt-4o"),
])
async def test_unverified_models_keep_their_existing_request_contract(monkeypatch, provider, model):
    requests = _mock_provider(monkeypatch, provider, model, valid_story())
    await llm.call_story_generation(_spec())
    assert len(requests) == 1
    _, request = requests[0]
    assert "output_config" not in request
    if provider == "openai":
        assert request["response_format"] == {"type": "json_object"}
        assert "text" not in request


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["gemini", "mock"])
async def test_other_provider_seams_receive_no_new_schema_argument(monkeypatch, provider):
    monkeypatch.setattr(settings, "llm_provider", provider)
    adapter = AsyncMock(return_value='{"ok":true}')
    monkeypatch.setattr(llm, "_call_" + provider, adapter)
    assert await llm.call_llm("System", "User", 123, 0.4, response_schema=StoryDraft.model_json_schema()) == '{"ok":true}'
    adapter.assert_awaited_once_with("System", "User", 123, 0.4)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("anthropic", "claude-opus-5"), ("openai", "gpt-6-astra")])
@pytest.mark.parametrize("defect", ["missing", "length", "unicode"])
async def test_native_schema_keeps_local_validation_and_redacted_diagnostics(monkeypatch, provider, model, defect):
    draft = valid_story()
    if defect == "missing":
        del draft["pages"][0]["characters_present"]
    elif defect == "length":
        draft["pages"][0]["text"] = PRIVATE * 30
    else:
        draft["pages"][0]["text"] = PRIVATE + "\ufffd"
    requests = _mock_provider(monkeypatch, provider, model, draft)
    logger = Mock()
    monkeypatch.setattr(llm, "logger", logger)
    monkeypatch.setattr(story_integrity, "logger", logger)
    with pytest.raises(LLMError) as caught:
        await llm.call_story_generation(_spec())
    assert len(requests) == 1
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None
    assert PRIVATE not in str(logger.mock_calls) + str(caught.value) + str(caught.value.details)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("anthropic", "claude-sonnet-5"), ("openai", "gpt-5.6-sol")])
async def test_schema_request_rejection_never_silently_falls_back_or_retries(monkeypatch, provider, model):
    requests = _mock_provider(monkeypatch, provider, model, valid_story(), status=400)
    logger = Mock()
    monkeypatch.setattr(llm, "logger", logger)
    monkeypatch.setattr(openai_contract, "logger", logger)
    with pytest.raises(LLMError) as caught:
        await llm.call_story_generation(_spec())
    assert len(requests) == 1
    assert caught.value.code == ErrorCode.UNKNOWN
    assert PRIVATE not in str(logger.mock_calls) + str(caught.value) + str(caught.value.details)
