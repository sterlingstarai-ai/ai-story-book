"""An approved portrait keeps its complete identity across books without AI redesign."""

import json
from unittest.mock import AsyncMock

import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError
from src.core.exceptions import APIError, AuthorizationError
from src.models.db import Character, UserConsent
from src.models.dto import BookSpec, StoryDraft
from src.services import llm, orchestrator
from tests.test_llm_schema_diagnostics import valid_story


async def _approved(db, valid_character, user_key, *, source_kind="photo"):
    character = Character(
        id="z-approved-character", user_key=user_key, from_photo=True,
        avatar_status="approved", avatar_version=2, avatar_source_kind=source_kind,
        avatar_url=settings.s3_public_url + "/characters/z-approved-character/avatars/v2/portrait.png",
        distinctive_features=["round glasses", "freckles"], **valid_character,
    )
    db.add_all([character, UserConsent(
        user_key=user_key, privacy=True, data_processing=True, granted=True, photos=True,
    )])
    await db.commit()
    return character


def _spec(character_id, **overrides):
    return BookSpec.model_validate({
        "topic": "친구들과 함께 책 읽기", "target_age": "7-9", "style": "watercolor",
        "page_count": 4, "character_id": character_id, **overrides,
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["photo", "drawing"])
async def test_new_books_reuse_entire_approved_character_without_llm_redesign(
    db_session, valid_character, user_key, monkeypatch, source_kind,
):
    character = await _approved(db_session, valid_character, user_key, source_kind=source_kind)
    provider = AsyncMock(side_effect=AssertionError("An approved character must not be redesigned"))
    monkeypatch.setattr(llm, "call_character_sheet_generation", provider)
    story = StoryDraft.model_validate(valid_story())
    first = await orchestrator.generate_character_sheet(_spec(character.id), story, user_key=user_key)
    second = await orchestrator.generate_character_sheet(
        _spec(character.id, topic="우주를 여행하는 이야기", style="3d"), story, user_key=user_key,
    )
    expected = {**valid_character, "character_id": character.id,
                "distinctive_features": character.distinctive_features}
    assert first.model_dump() == second.model_dump() == expected
    await db_session.refresh(character)
    assert character.avatar_version == 2 and character.avatar_status == "approved"
    assert character.clothing == valid_character["clothing"]
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["preview", "foreign_owner", "missing_owner", "revoked"])
async def test_unapproved_or_unauthorized_identity_never_falls_back_to_llm(
    db_session, valid_character, user_key, monkeypatch, condition,
):
    character = await _approved(db_session, valid_character, user_key)
    owner = user_key
    if condition == "preview":
        character.avatar_status = "preview"
        await db_session.commit()
    elif condition == "foreign_owner":
        owner = "99999999-9999-4999-8999-999999999999"
    elif condition == "missing_owner":
        owner = None
    else:
        from sqlalchemy import update

        monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
        await db_session.execute(update(UserConsent).values(photos=False))
        await db_session.commit()
    provider = AsyncMock(side_effect=AssertionError("No replacement character may be invented"))
    monkeypatch.setattr(llm, "call_character_sheet_generation", provider)
    with pytest.raises((APIError, AuthorizationError)):
        await orchestrator.generate_character_sheet(
            _spec(character.id), StoryDraft.model_validate(valid_story()), user_key=owner,
        )
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_saved_identity_fails_without_provider_or_private_diagnostics(
    db_session, valid_character, user_key, monkeypatch,
):
    character = await _approved(db_session, valid_character, user_key)
    private = "PRIVATE_CHILD_CHARACTER_DATA"
    character.clothing = {"top": private * 10}
    await db_session.commit()
    provider = AsyncMock(side_effect=AssertionError("Invalid stored identity must not be reimagined"))
    monkeypatch.setattr(llm, "call_character_sheet_generation", provider)
    with pytest.raises(LLMError) as caught:
        await orchestrator.generate_character_sheet(
            _spec(character.id), StoryDraft.model_validate(valid_story()), user_key=user_key,
        )
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert private not in str(caught.value) + str(caught.value.details)
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_story_receives_fixed_details_and_preserves_primary_selection_order(
    db_session, valid_character, user_key, monkeypatch,
):
    character = await _approved(db_session, valid_character, user_key)
    companion = Character(id="a-companion", user_key=user_key,
                          **{**valid_character, "name": "친구"})
    db_session.add(companion)
    await db_session.commit()
    spec = _spec(character.id, character_ids=[character.id, companion.id])
    loaded = await llm.load_characters_from_db(spec.character_ids)
    assert [item["name"] for item in loaded] == [character.name, companion.name]
    assert loaded[0]["appearance_details"] == valid_character["appearance"]
    assert loaded[0]["clothing"] == valid_character["clothing"]
    assert loaded[0]["identity_locked"] is True
    assert loaded[1]["identity_locked"] is False
    provider = AsyncMock(return_value=json.dumps(valid_story(), ensure_ascii=False))
    monkeypatch.setattr(llm, "call_llm", provider)
    await llm.call_story_generation(spec)
    system, prompt = provider.await_args.args
    assert "Only the scene, actions, poses and expressions may change" in system
    for section in ("appearance", "clothing"):
        for value in valid_character[section].values():
            assert value in prompt
    assert "round glasses" in prompt and "freckles" in prompt
    assert character.avatar_url not in prompt and "source_image_url" not in prompt


@pytest.mark.asyncio
async def test_text_character_path_still_generates_its_sheet(db_session, valid_character, user_key, monkeypatch):
    character = Character(id="text-character", user_key=user_key, **valid_character)
    db_session.add(character)
    await db_session.commit()
    sentinel = object()
    provider = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(llm, "call_character_sheet_generation", provider)
    spec, story = _spec(character.id), StoryDraft.model_validate(valid_story())
    assert await orchestrator.generate_character_sheet(spec, story, user_key=user_key) is sentinel
    provider.assert_awaited_once_with(spec, story)
