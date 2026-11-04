"""Image prompt length/schema regression exposed by real Sol book generation."""

from copy import deepcopy
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError
from src.models.dto import BookSpec, CharacterSheet, ImagePrompts, StoryDraft
from src.services import llm, openai_contract
from src.services.structured_output import provider_output_schema
from tests.test_live_generation_improvements import prompts
from tests.test_llm_schema_diagnostics import valid_story
from tests.test_story_structured_output import SUPPORTED, _body, _mock_provider, _schema_nodes

PRIVATE = "PRIVATE_CHILD_INPUT_NEVER_IN_SCHEMA_OR_DIAGNOSTICS"


def inputs(valid_character):
    spec = BookSpec(topic="정원을 가꾸는 이야기 " + PRIVATE, target_age="7-9",
                    style="watercolor", page_count=8)
    draft = valid_story()
    draft["pages"] = [{**draft["pages"][0], "page": page} for page in range(1, 9)]
    character = CharacterSheet(character_id="hero", **valid_character)
    return spec, StoryDraft.model_validate(draft), character


@pytest.mark.asyncio
async def test_character_sheet_requests_bounded_style_notes(monkeypatch, valid_character):
    spec, story, character = inputs(valid_character)
    payload = character.model_dump()
    payload["visual_style_notes"] = "a" * 200
    requests = _mock_provider(monkeypatch, "openai", "gpt-6-astra", payload)
    result = await llm.call_character_sheet_generation(spec, story)
    assert result.visual_style_notes == payload["visual_style_notes"]
    _, request = requests[0]
    output = request["text"]["format"]
    assert output["name"] == "character_sheet"
    assert output["strict"] is True
    assert output["schema"]["properties"]["visual_style_notes"]["maxLength"] == 200
    assert "200자를 넘기지 않는다" in request["input"][0]["content"]


def test_image_schema_preserves_nulls_and_bounds_without_changing_dto_defaults():
    canonical = ImagePrompts.model_json_schema()
    before = deepcopy(canonical)
    anthropic = provider_output_schema(canonical, provider="anthropic")
    openai = provider_output_schema(canonical, provider="openai")
    assert canonical == before
    original_fields = canonical["$defs"]["ImagePrompt"]["properties"]
    openai_fields = openai["$defs"]["ImagePrompt"]["properties"]
    for field, low, high in [("positive_prompt", 10, 1200), ("negative_prompt", 10, 600)]:
        assert (openai_fields[field]["minLength"], openai_fields[field]["maxLength"]) == (low, high)
    for field, high in [("guidance_notes", 200), ("base_image_url", 500), ("mask_url", 500)]:
        assert original_fields[field]["default"] is None
        for wire in (anthropic, openai):
            assert {"type": "null"} in wire["$defs"]["ImagePrompt"]["properties"][field]["anyOf"]
        assert {"type": "string", "maxLength": high} in openai_fields[field]["anyOf"]
    assert original_fields["aspect_ratio"]["default"] == "3:4"
    assert openai_fields["aspect_ratio"]["enum"] == original_fields["aspect_ratio"]["enum"]
    for node in _schema_nodes(openai):
        assert "default" not in node
        if "properties" in node:
            assert node["required"] == list(node["properties"])
            assert node["additionalProperties"] is False
    for node in _schema_nodes(anthropic):
        assert not {"minimum", "maximum", "minLength", "maxLength", "maxItems"} & node.keys()
        assert node.get("minItems", 0) <= 1
        if "properties" in node:
            assert node["additionalProperties"] is False
    assert ImagePrompts.model_validate(prompts(8).model_dump(exclude_none=True)).cover.base_image_url is None
    assert ImagePrompts.model_validate(prompts(8).model_dump(exclude_none=True)).cover.mask_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", SUPPORTED)
async def test_eight_page_image_request_uses_owned_native_schema_and_original_budget(
    monkeypatch, valid_character, provider, model,
):
    response = prompts(8).model_dump()
    requests = _mock_provider(monkeypatch, provider, model, response)
    result = await llm.call_image_prompts_generation(*inputs(valid_character))
    assert result.model_dump() == response
    assert [item.page for item in [result.cover, *result.pages]] == list(range(9))
    assert len(requests) == 1
    _, request = requests[0]
    if provider == "openai":
        output = request["text"]["format"]
        assert output["name"] == "image_prompts"
        assert output["strict"] is True
        assert request["store"] is False
        assert request["max_output_tokens"] == 10800
        assert "temperature" not in request
    else:
        output = request["output_config"]["format"]
        assert request["max_tokens"] == 5400
        assert request["thinking"] == {"type": "disabled"}
    assert output["type"] == "json_schema"
    assert output["schema"] == provider_output_schema(ImagePrompts.model_json_schema(), provider=provider)
    assert PRIVATE not in json.dumps(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [
    ("anthropic", "claude-sonnet-5-20260901"), ("openai", "gpt-6-astra-other"),
    ("openai", "gpt-4o"),
])
async def test_unverified_models_keep_image_json_mode(monkeypatch, valid_character, provider, model):
    requests = _mock_provider(monkeypatch, provider, model, prompts(8).model_dump())
    await llm.call_image_prompts_generation(*inputs(valid_character))
    _, request = requests[0]
    assert "output_config" not in request
    assert "text" not in request
    if provider == "openai":
        assert request["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("anthropic", "claude-opus-5"), ("openai", "gpt-5.6-sol")])
@pytest.mark.parametrize("field,limit", [("positive_prompt", 1200), ("negative_prompt", 600), ("guidance_notes", 200)])
async def test_native_image_responses_keep_exact_length_bounds_and_safe_failures(
    monkeypatch, valid_character, provider, model, field, limit,
):
    payload = prompts(8).model_dump()
    payload["cover"][field] = "x" * limit
    payload["pages"][0][field] = "x" * limit
    requests = _mock_provider(monkeypatch, provider, model, payload)
    args = inputs(valid_character)
    accepted = await llm.call_image_prompts_generation(*args)
    assert getattr(accepted.cover, field) == "x" * limit
    # Simulate a provider violating the wire schema: no clipping or fallback.
    overlong = (PRIVATE * (limit // len(PRIVATE) + 2))[:limit + 1]
    payload["cover"][field] = overlong
    payload["pages"][0][field] = overlong
    logger = Mock()
    monkeypatch.setattr(llm, "logger", logger)
    with pytest.raises(LLMError) as caught:
        await llm.call_image_prompts_generation(*args)
    assert len(requests) == 2, "Each operation is exactly one HTTP attempt"
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None
    assert PRIVATE not in str(logger.mock_calls) + str(caught.value)
    diagnostics = logger.error.call_args.kwargs["schema_diagnostics"]
    assert {"field_path": f"cover.{field}", "validation_type": "string_too_long"} in diagnostics
    assert {"field_path": f"pages[].{field}", "validation_type": "string_too_long"} in diagnostics


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("anthropic", "claude-sonnet-5"), ("openai", "gpt-5.6-sol")])
@pytest.mark.parametrize("defect", ["refusal", "truncated"])
async def test_complete_looking_image_json_is_rejected_on_provider_stop(
    monkeypatch, valid_character, provider, model, defect,
):
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(settings, "llm_api_key", "inert-test-secret")
    requests = []

    async def post(self, url, **kwargs):
        requests.append(kwargs["json"])
        body = _body(provider, model, prompts(8).model_dump())
        if provider == "anthropic":
            body["stop_reason"] = "refusal" if defect == "refusal" else "max_tokens"
        elif defect == "refusal":
            body["output"][0]["content"].append({"type": "refusal", "refusal": PRIVATE})
        else:
            body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(LLMError) as caught:
        await llm.call_image_prompts_generation(*inputs(valid_character))
    assert len(requests) == 1
    assert caught.value.code == (ErrorCode.SAFETY_OUTPUT if defect == "refusal" else ErrorCode.LLM_JSON_INVALID)
    assert PRIVATE not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["mock", "gemini"])
async def test_image_non_native_adapter_seams_do_not_receive_schema(monkeypatch, valid_character, provider):
    monkeypatch.setattr(settings, "llm_provider", provider)
    adapter = AsyncMock(return_value=prompts(8).model_dump_json())
    monkeypatch.setattr(llm, "_call_" + provider, adapter)
    await llm.call_image_prompts_generation(*inputs(valid_character))
    assert adapter.await_count == 1
    assert len(adapter.call_args.args) == 4
    assert adapter.call_args.kwargs == {}


@pytest.mark.asyncio
async def test_real_mock_image_prompt_branch_remains_valid(monkeypatch, valid_character):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    result = await llm.call_image_prompts_generation(*inputs(valid_character))
    assert len(result.pages) == 8
    assert result.cover.page == 0
    assert all(p.base_image_url is None and p.mask_url is None for p in [result.cover, *result.pages])


def test_image_prompt_instructions_match_dto_budgets_and_null_inpaint_fields():
    system = llm.render_prompt("generate_image_prompts.system.jinja2")
    assert "positive_prompt: 10~1200자" in system
    assert "negative_prompt: 10~600자" in system
    assert "guidance_notes: null 또는 200자 이하" in system
    assert "공백·문장부호를 포함한 문자 수" in system
    assert "마스터 묘사를 한 번만" in system
    assert '"base_image_url": null' in system and '"mask_url": null' in system


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("anthropic", "claude-sonnet-5"), ("openai", "gpt-5.6-sol")])
async def test_recurring_prop_design_reaches_one_request_with_complete_book_context(
    monkeypatch, valid_character, provider, model,
):
    """Check request wiring and unchanged bounds, not the model's visual compliance."""
    spec, story, character = inputs(valid_character)
    spec = spec.model_copy(update={"page_count": 12})
    story.pages = [
        story.pages[0].model_copy(update={"page": page, "scene": f"Recurring garden device, scene {page:02d}."})
        for page in range(1, 13)
    ]
    response = prompts(12).model_dump()
    requests = _mock_provider(monkeypatch, provider, model, response)
    result = await llm.call_image_prompts_generation(spec, story, character)

    assert len(requests) == 1, "Whole-book prop planning must not add a provider call"
    wire = json.dumps(requests[0][1], ensure_ascii=False)
    assert "책 전체의 반복 소품 디자인" in wire
    assert "재질·색·형태·인물에 대한 상대 크기·기능 부품의 배치" in wire
    assert "positive_prompt에 동일한 구절을 반복" in wire
    assert "페이지별 현재 상태는 본문 순서대로" in wire
    assert "그 장면에서 실제 사용하는 수량과 위치" in wire
    assert "그 한 쌍을 바닥에도 동시에 두지 않는다" in wire
    assert "별도 소품 목록은 출력하지 않는다" in wire
    assert all(f"Recurring garden device, scene {page:02d}." in wire for page in range(1, 13))
    assert "positive_prompt: 10~1200자" in wire
    assert result.model_dump() == response


def test_openai_schema_name_never_echoes_an_unregistered_title():
    with pytest.raises(LLMError) as caught:
        openai_contract.openai_generation_options(
            "gpt-5.6-sol", max_tokens=1000,
            response_schema={"title": PRIVATE, "type": "object", "properties": {}},
        )
    assert caught.value.code == ErrorCode.UNKNOWN
    assert PRIVATE not in str(caught.value)
