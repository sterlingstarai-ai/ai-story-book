"""Cast bindings reach both prompt generation and Gemini's actual HTTP request.

These offline checks verify instructions and transport, not visual adherence.
"""

import base64
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from src.models.dto import BookSpec, CharacterSheet, ImagePrompt, ImagePrompts, StoryDraft
from src.services import image, llm
from tests.test_live_generation_improvements import prompts
from tests.test_llm_schema_diagnostics import valid_story


@pytest.mark.asyncio
async def test_image_prompt_request_includes_roster_matching_each_pages_present_ids(
    monkeypatch, valid_character,
):
    data = valid_story()
    data["characters"].extend([
        {"id": "friend", "name": "나래", "role": "support", "brief": "빨간 조끼를 입은 작은 다람쥐"},
        {"id": "teacher", "name": "선생님", "role": "support", "brief": "초록 앞치마를 입은 노년의 곰"},
    ])
    # A single character, a pair, an absent protagonist and the full group must
    # retain different casts instead of inheriting the cover's complete group.
    casts = [["hero"], ["hero", "friend"], ["friend"], ["hero", "friend", "teacher"]]
    for page, cast in zip(data["pages"], casts, strict=True):
        page["characters_present"] = cast
    story = StoryDraft.model_validate(data)
    before = deepcopy(story.model_dump())
    character = CharacterSheet(character_id="hero", **valid_character)
    expected = prompts(4)
    provider = AsyncMock(return_value=expected.model_dump_json())
    monkeypatch.setattr(llm, "call_llm", provider)
    spec = BookSpec(topic="친구들과 도서관에서 만나는 이야기", target_age="7-9", style="watercolor", page_count=4)

    result = await llm.call_image_prompts_generation(spec, story, character)

    system, user = provider.call_args.args
    def field(name):
        return json.loads(user.split(f"- {name}: ", 1)[1].splitlines()[0])
    assert field("story_characters") == data["characters"]
    assert [page["characters_present"] for page in field("story_pages")] == casts
    assert field("character_sheet") == character.model_dump()
    assert "characters_present를 정확히 해석" in system
    assert "주인공이 없는 장면에는 마스터 묘사를 넣어 주인공을 추가하지 않는다" in system
    assert "Visible cast: N distinct characters, one of each." in system
    assert "이름을 주어로 연결" in system
    assert "상의와 멜빵·바지의 색을 서로 바꾸지 않는다" in system
    assert "명단에 없는 인물은 제외" in system
    assert result == expected and story.model_dump() == before
    assert provider.await_count == 1
    assert provider.call_args.kwargs["response_schema"] == ImagePrompts.model_json_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_state", ["none", "available", "unavailable"])
async def test_gemini_http_keeps_cast_and_identity_rules_with_or_without_reference(
    monkeypatch, reference_state,
):
    monkeypatch.setattr(image.settings, "image_provider", "gemini")
    monkeypatch.setattr(image.settings, "image_model", "gemini-3-pro-image")
    monkeypatch.setattr(image.settings, "image_api_key", "inert-image-secret")
    positive = ("Visible cast: 1 distinct character, one of each. Tori is one small brown rabbit "
                "with round ears, a yellow shirt under blue overalls and red shoes. "
                "Tori waters a flower alone. Soft watercolor painting.")
    prompt = ImagePrompt(page=2, positive_prompt=positive, negative_prompt="text, logos, duplicate characters", seed=10)
    before = prompt.model_dump()
    reference = "https://private.example.invalid/owned-reference.png"
    encoded_reference = base64.b64encode(b"fictional-reference-bytes").decode()
    fetched = AsyncMock(return_value=(encoded_reference, "image/png") if reference_state == "available" else None)
    monkeypatch.setattr(image, "_fetch_image_as_base64", fetched)
    logger = Mock()
    monkeypatch.setattr(image, "logger", logger)
    requests = []
    generated = b"fictional-generated-png"

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(generated).decode()}}
        ]}}]})

    client = httpx.AsyncClient
    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: client(
        transport=httpx.MockTransport(respond), **kwargs)))
    persisted = AsyncMock(return_value="https://private.example.invalid/generated.png")
    monkeypatch.setattr(image, "_persist_image_bytes", persisted)
    if reference_state == "unavailable":
        from src.core.errors import ImageError
        with pytest.raises(ImageError):
            await image.generate_image(prompt, reference)
        assert not requests
        persisted.assert_not_awaited()
        assert reference not in str(logger.mock_calls)
        return
    result = await image.generate_image(prompt, None if reference_state == "none" else reference)

    assert result.endswith("generated.png") and len(requests) == 1
    persisted.assert_awaited_once_with(generated, "image/png", "gemini")
    parts = requests[0]["contents"][0]["parts"]
    scene = parts[-1]["text"]
    assert scene.count(positive) == 1
    assert "exactly one instance of each" in scene
    assert "not additional people" in scene
    assert "Bind each action to its named character" in scene
    assert "hair length, parting and hairstyle unchanged" in scene
    assert "never transfer a companion's features to the protagonist" in scene
    assert "Preserve the exact garment-to-color assignment" in scene
    assert "never swap these colors or outfits" in scene
    assert "No readable text" in scene and prompt.negative_prompt in scene
    if reference_state == "available":
        assert len(parts) == 3
        assert "the reference does not" in parts[0]["text"]
        assert "Omit every reference character absent from the current cast" in parts[0]["text"]
        assert "Never copy the reference's group size" in parts[0]["text"]
        assert "established default outfit and its colors" in parts[0]["text"]
        assert "scene or style instructions must not redesign the character" in parts[0]["text"]
        assert parts[1] == {"inline_data": {"mime_type": "image/png", "data": encoded_reference}}
    else:
        assert len(parts) == 1 and "inline_data" not in parts[0]
    assert fetched.await_count == (0 if reference_state == "none" else 1)
    assert prompt.model_dump() == before
    assert reference not in str(logger.mock_calls)
    assert positive not in str(logger.mock_calls)
    assert encoded_reference not in str(logger.mock_calls)
