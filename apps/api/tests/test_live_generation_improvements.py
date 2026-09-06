"""Regression cases exposed by the first real eight-page Korean book."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.dto import BookSpec, CharacterSheet, ImagePrompt, ImagePrompts
from src.services import image, llm, orchestrator


def prompts(count=4):
    return ImagePrompts(style="watercolor", cover=ImagePrompt(
        page=0, positive_prompt="A child in a quiet library", negative_prompt="text, logo, weapons", seed=1),
        pages=[ImagePrompt(page=i, positive_prompt="The child waters a flower",
                           negative_prompt="text, logo, weapons", seed=i + 1) for i in range(1, count + 1)])


def test_unicode_json_keeps_korean_meaning_without_escape_expansion():
    payload = {"text": "하루는 젖은 책을 조심조심 꺼냈어요.", "quote": '"친구야"'}
    rendered = llm.jinja_env.from_string("{{ value | tojson }}").render(value=payload)
    assert json.loads(rendered) == payload
    assert "하루는" in rendered
    assert len(rendered) < len(json.dumps(payload, ensure_ascii=True))


@pytest.mark.asyncio
async def test_twelve_page_prompts_have_room_for_all_scenes(monkeypatch, valid_character):
    spec = BookSpec(topic="작은 정원을 돌보는 이야기", target_age="7-9", style="watercolor", page_count=12)
    character = CharacterSheet(character_id="hero", **valid_character)
    story = SimpleNamespace(cover=SimpleNamespace(model_dump=lambda: {"scene": "작은 정원"}),
                            characters=[SimpleNamespace(model_dump=lambda: {
                                "id": "hero", "name": character.name, "role": "main", "brief": "친절한 정원 탐험가"})],
                            pages=[SimpleNamespace(model_dump=lambda: {"scene": "꽃에 물을 주어요"}) for _ in range(12)])
    async def provider(_system, user, max_tokens, temperature, *, response_schema=None):
        assert "꽃에 물을 주어요" in user
        # A realistic 13-scene JSON exceeds the old fixed4k output limit.
        assert 6500 <= max_tokens <= 8000
        assert response_schema == ImagePrompts.model_json_schema()
        return prompts(12).model_dump_json()
    monkeypatch.setattr(llm, "call_llm", provider)
    result = await llm.call_image_prompts_generation(spec, story, character)
    assert [p.page for p in result.pages] == list(range(1, 13))


def test_gemini_forwards_negative_prompt_and_blank_sign_policy():
    text = image.gemini_prompt_text(prompts().cover)
    assert "A child in a quiet library" in text
    assert "Exclude these elements: text, logo, weapons" in text
    assert "Signs and book covers must be blank" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,reference,cover,expected", [
    ("gemini", None, "https://s3.example/owned-cover.png", "https://s3.example/owned-cover.png"),
    ("gemini", "https://s3.example/owned-photo.png", "https://s3.example/owned-cover.png", "https://s3.example/owned-photo.png"),
    ("gemini", None, "https://placeholder.invalid/image-unavailable.png", None),
    ("mock", None, "https://s3.example/owned-cover.png", "https://s3.example/owned-cover.png"),
])
async def test_owned_cover_anchors_pages_without_overriding_explicit_reference(
        monkeypatch, provider, reference, cover, expected):
    monkeypatch.setattr(orchestrator.settings, "image_provider", provider)
    seen = []
    async def generate(prompt, job_id, page, reference_image_url=None):
        seen.append((page, reference_image_url, image._book_reference_url.get()))
        return cover if page == 0 else f"https://s3.example/owned-page-{page}.png"
    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        result = await orchestrator.generate_all_images("synthetic", prompts(), 5, reference)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert result[0] == cover
    assert seen[0] == (0, reference, None)
    assert all(ref == expected for page, ref, _ in seen if page > 0)
    expected_cover = None if "placeholder" in cover else cover
    assert all(anchor == expected_cover for page, _, anchor in seen if page > 0)


@pytest.mark.asyncio
async def test_concurrent_books_keep_their_own_avatar_and_generated_cover(monkeypatch):
    from src.services.storage import canonical_media_url

    monkeypatch.setattr(orchestrator.settings, "image_provider", "openai")
    monkeypatch.setattr(orchestrator.settings, "image_model", "gpt-image-2")
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    seen = []

    async def generate(prompt, job_id, page, reference_image_url=None):
        before = image._book_reference_url.get()
        await asyncio.sleep(0)
        assert image._book_reference_url.get() == before
        seen.append((job_id, page, reference_image_url, before))
        return canonical_media_url(f"jobs/{job_id}/page-{page}.png")

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    avatars = {job: canonical_media_url(f"jobs/{job}/character-reference/avatar.png") for job in ("one", "two")}
    await asyncio.gather(*[
        orchestrator.generate_all_images(job, prompts(), 5, avatars[job]) for job in avatars
    ])
    assert len(seen) == 10
    for job, page, avatar, cover in seen:
        assert avatar == avatars[job]
        assert cover == (canonical_media_url(f"jobs/{job}/page-0.png") if page else None)
    assert image._book_reference_url.get() is None


@pytest.mark.asyncio
async def test_failed_cover_restores_the_callers_reference_scope(monkeypatch):
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())

    async def fail(*args, **kwargs):
        assert image._book_reference_url.get() is None
        raise RuntimeError("cover failed")

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", fail)
    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        with pytest.raises(RuntimeError, match="cover failed"):
            await orchestrator.generate_all_images("synthetic", prompts(), 5)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert image._book_reference_url.get() is None
