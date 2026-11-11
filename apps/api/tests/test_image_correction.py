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
    assert "The children leave the book open to dry." in expanded.positive_prompt


def test_action_correction_distinguishes_a_plan_from_the_action_being_planned():
    text = "The teacher studies the rain barrel blueprint while the children discuss who will decorate the barrel."
    with image_correction_scope(page_text=text, issues=["action_mismatch"]):
        expanded = provider_prompt_with_correction(complete_prompt())
    assert "Depict planning as talk, not action; objects only on plans stay on paper." in expanded.positive_prompt
    assert text in expanded.positive_prompt


def test_action_correction_overrides_an_incomplete_cast_count():
    prompt = complete_prompt().model_copy(update={"positive_prompt": "Visible cast: three children."})
    narrative = "The three children and the attendant tie the sign to the noticeboard together."
    with image_correction_scope(page_text=narrative, issues=["action_mismatch"]):
        expanded = provider_prompt_with_correction(prompt)
    assert "Follow the narrative over conflicting staging or cast counts." in expanded.positive_prompt
    assert "Show only its stated actors." in expanded.positive_prompt
    assert narrative in expanded.positive_prompt
    assert expanded.positive_prompt.startswith(f"CURRENT PAGE NARRATIVE: {narrative}")
    assert expanded.positive_prompt.endswith(f"COMPATIBLE BRIEF: {prompt.positive_prompt}")


def test_action_correction_omits_old_staging_when_cast_looks_are_separate():
    prompt = complete_prompt().model_copy(update={
        "positive_prompt": "Haru puts the pebble in the flowerpot. Dami watches.",
        "guidance_notes": "CAST LOOKS: Haru = brown bear, yellow hat; Dami = white rabbit, purple scarf",
    })
    narrative = "Dami sets the pebble on the ground beside the flowerpot."
    with image_correction_scope(page_text=narrative, issues=["action_mismatch"]):
        corrected = provider_prompt_with_correction(prompt, use_cast_looks=True)
        without_cover = provider_prompt_with_correction(prompt)
    assert corrected.positive_prompt.startswith(f"CURRENT PAGE NARRATIVE: {narrative}")
    assert corrected.positive_prompt.endswith(prompt.guidance_notes)
    assert "Connect each held prop to the named actor's hand; observers keep hands clear." in corrected.positive_prompt
    assert "Show direct actions without adding tools." in corrected.positive_prompt
    assert "Keep each prop's stated count, state and position." in corrected.positive_prompt
    assert prompt.positive_prompt not in corrected.positive_prompt
    assert prompt.positive_prompt in without_cover.positive_prompt

    with image_correction_scope(page_text=narrative, issues=["readable_text"]):
        typography = provider_prompt_with_correction(prompt)
    assert typography.positive_prompt.startswith(prompt.positive_prompt)


@pytest.mark.parametrize("brief", [
    "ACTION FOCUS: The only line",
    "Wide forest view.\nACTION FOCUS: The second line",
    "ACTION FOCUS: \nWide forest view.",
    f"ACTION FOCUS: {'x' * 181}\nWide forest view.",
    "ACTION FOCUS: A hidden\u200b character.\nWide forest view.",
])
def test_optional_action_focus_ignores_missing_or_invalid_lines(brief):
    prompt = complete_prompt().model_copy(update={
        "positive_prompt": brief,
        "guidance_notes": "CAST LOOKS: Haru = white rabbit",
    })
    with image_correction_scope(
        page_text="Haru watches.", issues=["action_mismatch"], use_prompt_action_focus=True,
    ):
        repaired = provider_prompt_with_correction(prompt, use_cast_looks=True)
    assert "ACTION FOCUS" not in repaired.positive_prompt
    assert prompt.guidance_notes in repaired.positive_prompt


def test_action_correction_uses_adjacent_pages_only_for_continuity():
    prompt = complete_prompt().model_copy(update={
        "positive_prompt": "The plant grows out of the garden bed.",
        "guidance_notes": "CAST LOOKS: Haru = brown bear, yellow hat",
    })
    narrative = "The tiny green loop pushes through the soil. Haru stops watering and watches."
    previous = "Haru set two flowerpots beside the wooden box."
    following = "Tomorrow the plant opens two leaves in the first pot."
    with image_correction_scope(
        page_text=narrative, issues=["action_mismatch"],
        previous_page_text=previous, next_page_text=following,
    ):
        corrected = provider_prompt_with_correction(prompt, use_cast_looks=True).positive_prompt
    assert corrected.startswith(f"CURRENT PAGE NARRATIVE: {narrative}")
    assert "show the stopped state" in corrected
    assert "persistent setting and props only; do not show their actions or later states" in corrected
    assert f"Previous page: {previous}" in corrected
    assert f"Next page: {following}" in corrected
    assert prompt.positive_prompt not in corrected
    assert prompt.guidance_notes in corrected
    with image_correction_scope(
        page_text=narrative, issues=["readable_text"],
        previous_page_text=previous, next_page_text=following,
    ):
        typography = provider_prompt_with_correction(prompt).positive_prompt
    assert previous not in typography and following not in typography


def test_full_repair_context_fits_reference_provider_request_without_losing_tail():
    original = complete_prompt().model_copy(update={"negative_prompt": "n" * 600})
    narrative = "The tap fills the watering can through its top opening. " + "x" * 540
    assert len(narrative) <= 600
    with image_correction_scope(
        page_text=narrative, issues=list(CORRECTION_INSTRUCTIONS),
        previous_page_text="a" * 600, next_page_text="b" * 600,
    ):
        expanded = provider_prompt_with_correction(original)
        wire = image._REFERENCE_RULES + "\n" + image.gemini_prompt_text(expanded)
    # Cross-boundary regression: bounded product context must still fit the
    # stricter live acceptance request guard with a full negative prompt/reference.
    assert len(wire) <= 5000
    assert original.positive_prompt in wire and narrative in wire
    assert "Follow the narrative over conflicting staging" in wire
    assert "Match contact, scale and flow" in wire
    assert "keep beside distinct from inside" in wire
    assert "Show only its stated actors" in wire
    assert "Keep each prop's stated count, state and position" in wire
    assert "never from the lower tap" in wire
    assert "crop the fittings out" in wire
    assert "No fresh stream or drips" in wire
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
    assert payloads[0].startswith(f"CURRENT PAGE NARRATIVE: {body}")
    assert f"COMPATIBLE BRIEF: {prompt.positive_prompt}" in payloads[0]
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
    if issue in {"identity_swap", "duplicate_character"}:
        assert calls[0][0] == "https://owned.invalid/approved-avatar"
        assert "EDIT THE GENERATED" not in calls[0][1]
    else:
        assert calls[0][0] == "https://owned.invalid/current-page"
        if issue == "action_mismatch":
            assert "old action and composition" in calls[0][1]
            assert "are not constraints" in calls[0][1]
        else:
            assert "Preserve its composition" in calls[0][1]
    assert calls[1][0] == "https://owned.invalid/approved-avatar"
    assert "EDIT THE GENERATED" not in calls[1][1]
    assert correction_scene_reference() is None


@pytest.mark.parametrize('identity_issue', ['identity_swap', 'duplicate_character'])
def test_mixed_identity_and_action_defects_keep_approved_character_anchor(identity_issue):
    with image_correction_scope(
        page_text="The child fills the can.", issues=[identity_issue, "action_mismatch"],
        source_image_url="https://owned.invalid/wrong-character-page",
    ):
        assert correction_scene_reference() is None
