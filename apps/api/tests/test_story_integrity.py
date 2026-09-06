"""Text defects fail before paid images; intentional names and learning survive."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import create_model

from src.core.errors import ErrorCode, LLMError
from src.models.dto import BookSpec, Language, ModerationResult, StoryDraft
from src.services import llm, orchestrator, story_integrity
from tests.test_learning_quality import _assets
from tests.test_llm_schema_diagnostics import valid_story


def _spec(**overrides):
    return BookSpec.model_validate({
        "topic": "친구들과 함께 책 읽기", "target_age": "7-9", "style": "watercolor",
        "page_count": 4, **overrides,
    })


def _story(text="친구들과 함께 책을 읽어요."):
    data = valid_story()
    data["pages"][0]["text"] = text
    return StoryDraft.model_validate(data)


@pytest.mark.parametrize("path,corruption", [
    (("title",), "\ufffd"),
    (("cover", "cover_text"), "\x00"),
    (("moral",), "\u202e"),
    (("pages", 0, "learning_point"), "\u2066"),
    (("characters", 0, "name"), "\x7f"),
    (("continuity", "character_consistency_notes"), "\ufeff"),
    (("pages", 3, "series_hook"), "\U0001ffff"),
])
def test_unicode_gate_covers_nested_strings_without_leaking_text(monkeypatch, path, corruption):
    secret = "PRIVATE_CHILD_PHOTO_TOKEN"
    data = valid_story()
    parent = data
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = secret + corruption
    logger = Mock()
    monkeypatch.setattr(story_integrity, "logger", logger)
    with pytest.raises(LLMError) as caught:
        story_integrity.validate_story_integrity(StoryDraft.model_validate(data), _spec())
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None
    assert secret not in str(logger.mock_calls) + str(caught.value) + str(caught.value.details)
    assert all(item["rule"] == "invalid_unicode" for item in logger.warning.call_args.kwargs["integrity_diagnostics"])


def test_surrogate_is_rejected_by_schema_before_integrity_gate_without_text_leak(monkeypatch):
    secret = "PRIVATE_CHILD_PHOTO_TOKEN"
    data = valid_story()
    data["pages"][0]["text"] = secret + "\ud800"
    logger = Mock()
    monkeypatch.setattr(llm, "logger", logger)
    with pytest.raises(LLMError) as caught:
        llm.parse_json_response(json.dumps(data), StoryDraft)
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert secret not in str(logger.mock_calls) + str(caught.value) + str(caught.value.details)


def test_unknown_model_field_names_never_appear_in_integrity_diagnostics(monkeypatch):
    secret = "PRIVATE_DYNAMIC_NAME"
    model = create_model(secret, **{secret: (str, ...)})
    logger = Mock()
    monkeypatch.setattr(story_integrity, "logger", logger)
    with pytest.raises(LLMError):
        story_integrity.validate_generated_text_unicode(model(**{secret: "\ufffd"}))
    assert logger.warning.call_args.kwargs["integrity_diagnostics"] == [{"field_path": "$", "rule": "invalid_unicode"}]
    assert secret not in str(logger.mock_calls)


def test_korean_drift_rejected_while_internal_english_camera_is_allowed():
    story = _story("토리가 activo하게 책을 골라요.")
    story.cover.camera = "wide shot"
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, _spec())
    story.pages[0].text = "토리가 활기차게 책을 골라요."
    story_integrity.validate_story_integrity(story, _spec())


def test_intentional_names_and_unicode_are_preserved_exactly():
    story = _story("Jose\u0301와 Lumi가 E\u0301va를 만나요.\n\tAI 이야기도 읽어요. 👨‍👩‍👧")
    spec = _spec(topic="AI 이야기 읽기", protagonist_name="José", character={"name": "Lumi"})
    before = story.model_dump_json()
    story_integrity.validate_story_integrity(story, spec, supplied_character_names=["Éva"])
    assert story.model_dump_json() == before, "The gate must not repair or normalize delivered prose"
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, spec)


def test_model_generated_name_cannot_allowlist_its_own_foreign_word():
    story = _story("activo가 뛰어가요.")
    story.characters[0].name = "activo"
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, _spec())


def test_explicit_english_lesson_quotes_are_allowed_but_mixed_narrative_is_not():
    story = _story('토리가 "Hello, friend!" 하고 인사해요.')
    lesson = _spec(topic="영어 인사 배우기")
    story_integrity.validate_story_integrity(story, lesson)
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, _spec())
    story.pages[0].text = '토리가 "Hello!" 하고 activo하게 인사해요.'
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, lesson)
    story.pages[0].text = '토리가 "오늘은 activo하게 놀자!" 하고 말해요.'
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, lesson)


def test_non_korean_and_bilingual_fields_keep_their_selected_languages():
    story = _story("José está activo hoy.")
    story.language = Language.es
    story_integrity.validate_story_integrity(story, _spec(language="es"))
    with pytest.raises(LLMError):
        story_integrity.validate_story_integrity(story, _spec(language="en"))
    assets = _assets([[], [], [], []])
    assets.pages[0].translated_text = "The friends read together."
    story_integrity.validate_generated_text_unicode(assets)
    assets.parent_guide.activities.append("읽어요.\ufffd")
    with pytest.raises(LLMError):
        story_integrity.validate_generated_text_unicode(assets)


@pytest.mark.asyncio
async def test_loaded_character_name_reaches_generation_gate(monkeypatch):
    provider = AsyncMock(return_value=_story("Lumi가 친구를 도와요.").model_dump_json())
    monkeypatch.setattr(llm, "call_llm", provider)
    loader = AsyncMock(return_value=[{"name": "Lumi", "appearance": "토끼", "personality": []}])
    monkeypatch.setattr(llm, "load_characters_from_db", loader)
    result = await llm.call_story_generation(_spec(character_id="selected-character"))
    assert result.pages[0].text == "Lumi가 친구를 도와요."
    loader.assert_awaited_once_with(["selected-character"])


@pytest.mark.asyncio
async def test_existing_retry_budget_recovers_without_repairing_invalid_prose(monkeypatch):
    provider = AsyncMock(side_effect=[
        _story("친구들이 책을 읽어\ufffd요.").model_dump_json(),
        _story("친구들이 activo하게 책을 읽어요.").model_dump_json(),
        _story().model_dump_json(),
    ])
    monkeypatch.setattr(llm, "call_llm", provider)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator.asyncio, "sleep", AsyncMock())
    result = await orchestrator.run_step(
        job_id="integrity-test", step_name="generate_story", progress=20,
        fn=lambda: llm.call_story_generation(_spec()), retries=2, timeout_sec=5, backoff=[0, 0],
    )
    assert provider.await_count == 3
    assert result.pages[0].text == "친구들과 함께 책을 읽어요."


@pytest.mark.asyncio
async def test_repeated_invalid_story_fails_before_draft_character_or_image_cost(monkeypatch):
    provider = AsyncMock(return_value=_story("친구들이 activo하게 책을 읽어요.").model_dump_json())
    monkeypatch.setattr(llm, "call_llm", provider)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(orchestrator, "moderate_input", AsyncMock(return_value=ModerationResult(is_safe=True)))
    fail = AsyncMock()
    monkeypatch.setattr(orchestrator, "mark_job_failed", fail)
    downstream = {}
    for name in ("save_story_draft", "generate_character_sheet", "generate_image_prompts", "generate_all_images"):
        downstream[name] = AsyncMock()
        monkeypatch.setattr(orchestrator, name, downstream[name])
    await orchestrator.start_book_generation("integrity-test", _spec(), "synthetic-user")
    assert provider.await_count == 3
    fail.assert_awaited_once()
    assert fail.await_args.args[1] == ErrorCode.LLM_JSON_INVALID
    assert "activo" not in str(fail.await_args)
    for operation in downstream.values():
        operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_retext_and_learning_reject_unicode_but_allow_translation(monkeypatch):
    provider = AsyncMock(return_value=json.dumps({"page": 1, "revised_text": "읽어\ufffd요."}))
    monkeypatch.setattr(llm, "call_llm", provider)
    with pytest.raises(LLMError):
        await llm.call_text_rewrite(_spec(), _story(), 1, "더 쉽게")
    provider.return_value = json.dumps({"title": "읽기", "pages": ["읽어\ufffd요."] * 4})
    with pytest.raises(LLMError):
        await llm.call_story_retext("읽기", ["읽어요."] * 4, "3-5", "ko")
    assets = _assets([[], [], [], []])
    provider.return_value = assets.model_dump_json()
    assert (await llm.call_learning_assets(_story(), Language.ko, Language.en)).target_language == Language.en
    assets.pages[0].vocab[0].example = "Read\ufffd together."
    provider.return_value = assets.model_dump_json()
    with pytest.raises(LLMError):
        await llm.call_learning_assets(_story(), Language.ko, Language.en)
