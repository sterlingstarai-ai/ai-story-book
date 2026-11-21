from unittest.mock import AsyncMock, patch

import pytest

from src.core.exceptions import InternalServerError
from src.models.dto import CharacterAppearance, CharacterClothing, CreateCharacterRequest
from src.routers.characters import create_character, create_character_from_text, delete_character


@pytest.mark.asyncio
async def test_create_character_rolls_back_on_commit_failure(db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
    rollback = AsyncMock(wraps=db.rollback)
    monkeypatch.setattr(db, "rollback", rollback)
    request = CreateCharacterRequest(
        name="토리",
        master_description="용감한 토끼 캐릭터",
        appearance=CharacterAppearance(
            age_visual="5세",
            face="둥근 얼굴",
            hair="없음",
            skin="갈색 털",
            body="통통함",
        ),
        clothing=CharacterClothing(
            top="티셔츠",
            bottom="바지",
            shoes="운동화",
            accessories="없음",
        ),
        personality_traits=["용감함"],
        visual_style_notes="cartoon",
    )

    with pytest.raises(InternalServerError):
        await create_character(request=request, db=db, user_key="user-12345678")

    db.commit.assert_awaited_once()
    rollback.assert_awaited_once()
    assert not db.new


@pytest.mark.asyncio
async def test_delete_character_rolls_back_on_commit_failure(db_session, monkeypatch, valid_character):
    from src.models.db import Character, StoragePurgeTask
    from sqlalchemy import select

    existing = Character(id="char-1", user_key="user-12345678", **valid_character)
    db_session.add(existing)
    await db_session.commit()
    monkeypatch.setattr(db_session, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
    rollback = AsyncMock(wraps=db_session.rollback)
    monkeypatch.setattr(db_session, "rollback", rollback)
    with pytest.raises(InternalServerError):
        await delete_character(character_id="char-1", db=db_session, user_key="user-12345678")
    rollback.assert_awaited_once()
    assert await db_session.get(Character, "char-1") is not None
    assert not list((await db_session.scalars(select(StoragePurgeTask))).all())


@pytest.mark.asyncio
async def test_create_character_from_text_rolls_back_on_commit_failure(monkeypatch, db_session):
    monkeypatch.setattr("src.routers.characters.consume_generation_budget", AsyncMock())
    db = db_session
    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
    rollback = AsyncMock(wraps=db.rollback)
    monkeypatch.setattr(db, "rollback", rollback)
    mock_character_data = {
        "name": "토리",
        "master_description": "5살 귀여운 토끼 캐릭터",
        "appearance": {
            "age_visual": "5세",
            "face": "둥근 얼굴",
            "hair": "없음",
            "skin": "갈색 털",
            "body": "통통한 체형",
        },
        "clothing": {
            "top": "줄무늬 티셔츠",
            "bottom": "바지",
            "shoes": "운동화",
            "accessories": "없음",
        },
        "personality_traits": ["호기심 많은"],
        "visual_style_notes": "cartoon",
    }

    with patch(
        "src.routers.characters.photo_character_service.create_character_from_text",
        new=AsyncMock(return_value=mock_character_data),
    ):
        with pytest.raises(InternalServerError):
            await create_character_from_text(
                name="토리",
                age="5살",
                traits="호기심 많은",
                style="cartoon",
                db=db,
                user_key="user-12345678",
            )

    db.commit.assert_awaited_once()
    rollback.assert_awaited_once()
    assert not db.new
