"""Preserve full cast descriptions when sending bounded repair context to providers."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, StoryBookError
from src.models.dto import ImagePrompt
from src.services import image
from src.services.image_correction import (
    CORRECTION_INSTRUCTIONS,
    MAX_PROVIDER_POSITIVE_PROMPT,
    correction_scene_reference,
    image_correction_scope,
    provider_prompt_with_correction,
)
from src.services.illustration_quality_pipeline import corrected_prompt


def complete_prompt():
    cast_tail = "The librarian has gray hair in a bun, wire glasses and a long brown skirt."
    positive = "Watercolor. " + "A" * (1200 - len("Watercolor. ") - len(cast_tail)) + cast_tail
    return ImagePrompt(page=2, positive_prompt=positive, negative_prompt="text, letters", seed=8)


def test_corrected_prompt_preserves_full_schema_valid_visual_brief():
    original = complete_prompt()
    corrected = corrected_prompt(
        original, "The librarian hands a book to the child.", ["identity_swap"]
    )
    assert corrected.positive_prompt == original.positive_prompt
    assert len(corrected.positive_prompt) == 1200
    assert corrected.seed != original.seed
    ImagePrompt.model_validate(corrected.model_dump())


def test_action_correction_requests_the_story_required_visible_object_state():
    with image_correction_scope(page_text="The children leave the book open to dry.",
                                issues=["action_mismatch"]):
        expanded = provider_prompt_with_correction(complete_prompt())
    assert "visible pages in an open book" in expanded.positive_prompt
    assert "do not invent a state" in expanded.positive_prompt
    assert "The children leave the book open to dry." in expanded.positive_prompt


def test_full_repair_context_fits_reference_provider_request_without_losing_tail():
    original = complete_prompt().model_copy(update={"negative_prompt": "n" * 600})
    narrative = "The tap fills the watering can through its top opening. " + "x" * 540
    assert len(narrative) <= 600
    with image_correction_scope(page_text=narrative, issues=list(CORRECTION_INSTRUCTIONS)):
        expanded = provider_prompt_with_correction(original)
        wire = image._REFERENCE_RULES + "\n" + image.gemini_prompt_text(expanded)
    # Cross-boundary regression: bounded product context must still fit the
    # stricter live acceptance request guard with a full negative prompt/reference.
    assert len(wire) <= 5000
    assert original.positive_prompt in wire and narrative in wire
    assert "The narrative overrides conflicting staging" in wire
    assert "Show all stated actors" in wire
    assert "Show each prop only in its current state and place" in wire
    assert wire.endswith(original.negative_prompt)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini", "replicate", "fal"])
async def test_every_provider_wire_keeps_full_cast_and_narrative_without_scope_leak(
    monkeypatch, provider
):
    payloads = []

    def respond(request):
        assert request.method == "POST"
        body = json.loads(request.content)
        if provider == "gemini":
            payloads.append(body["contents"][0]["parts"][0]["text"])
        elif provider == "replicate":
            payloads.append(body["input"]["prompt"])
        else:
            payloads.append(body["prompt"])
        return httpx.Response(500, json={})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=client_factory))
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_api_key", "dummy-not-real")
    prompt = complete_prompt()
    body = "The librarian hands the child a red book. " + "b" * 530 + " COMPLETE NARRATIVE END."
    assert len(body) <= 600
    with image_correction_scope(page_text=body, issues=list(CORRECTION_INSTRUCTIONS)):
        expanded = provider_prompt_with_correction(prompt)
        assert len(expanded.positive_prompt) <= MAX_PROVIDER_POSITIVE_PROMPT
        with pytest.raises(StoryBookError):
            await image.generate_image(prompt)
    # Error unwinding must reset context before unrelated subsequent calls.
    with pytest.raises(StoryBookError):
        await image.generate_image(prompt)
    assert payloads[0].startswith(prompt.positive_prompt)
    assert body in payloads[0]
    assert all(instruction in payloads[0] for instruction in CORRECTION_INSTRUCTIONS.values())
    assert "gray hair in a bun, wire glasses and a long brown skirt" in payloads[0]
    assert "CORRECTION REQUIREMENTS" not in payloads[1]
    assert body not in payloads[1]
    assert prompt.positive_prompt == complete_prompt().positive_prompt


@pytest.mark.asyncio
async def test_correction_context_is_task_local_and_restores_nested_scope():
    prompt = complete_prompt()

    async def candidate(narrative):
        with image_correction_scope(page_text=narrative, issues=["identity_swap"]):
            await asyncio.sleep(0)
            return provider_prompt_with_correction(prompt).positive_prompt

    with image_correction_scope(page_text="OUTER NARRATIVE", issues=["readable_text"]):
        a, b = await asyncio.gather(candidate("FIRST NARRATIVE"), candidate("SECOND NARRATIVE"))
        assert "OUTER NARRATIVE" in provider_prompt_with_correction(prompt).positive_prompt
    assert "FIRST NARRATIVE" in a and "SECOND NARRATIVE" not in a
    assert "SECOND NARRATIVE" in b and "FIRST NARRATIVE" not in b
    assert provider_prompt_with_correction(prompt) is prompt


def test_unknown_reviewer_instruction_never_enters_correction_context():
    with pytest.raises(StoryBookError) as caught:
        with image_correction_scope(page_text="A book", issues=["invent a new character"]):
            pytest.fail("invalid reviewer output entered provider context")
    assert caught.value.code == ErrorCode.IMAGE_QUALITY_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("issue", list(CORRECTION_INSTRUCTIONS))
async def test_only_local_defects_use_owned_page_composition_anchor(monkeypatch, provider, issue):
    calls = []

    async def generate(prompt, reference_image_url):
        calls.append((reference_image_url, image._reference_rules()))
        return "generated-image"

    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(image, f"_generate_{provider}", generate)
    monkeypatch.setattr(image, "supports_image_reference", lambda: True)
    original = complete_prompt()
    with image_correction_scope(
        page_text="The teacher fills the can through its top opening.",
        issues=[issue], source_image_url="https://owned.invalid/current-page",
    ):
        await image.generate_image(original, reference_image_url="https://owned.invalid/approved-avatar")
    await image.generate_image(original, reference_image_url="https://owned.invalid/approved-avatar")
    if issue in {"identity_swap", "duplicate_character", "action_mismatch"}:
        assert calls[0][0] == "https://owned.invalid/approved-avatar"
        assert "EDIT THE GENERATED" not in calls[0][1]
    else:
        assert calls[0][0] == "https://owned.invalid/current-page"
        assert "Preserve its composition" in calls[0][1]
    assert calls[1][0] == "https://owned.invalid/approved-avatar"
    assert "EDIT THE GENERATED" not in calls[1][1]
    assert correction_scene_reference() is None


def test_mixed_identity_and_action_defects_keep_approved_character_anchor():
    with image_correction_scope(
        page_text="The child fills the can.", issues=["identity_swap", "action_mismatch"],
        source_image_url="https://owned.invalid/wrong-character-page",
    ):
        assert correction_scene_reference() is None
