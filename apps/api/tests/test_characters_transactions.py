from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.core.exceptions import InternalServerError
from src.models.dto import CharacterAppearance, CharacterClothing, CreateCharacterRequest
from src.routers.characters import create_character, create_character_from_text, delete_character


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FailingCommitDbSession:
    def __init__(self, execute_results=None):
        self._execute_results = list(execute_results or [])
        self._execute_index = 0
        self.rollback_calls = 0
        self.deleted_items = []
        self.added_items = []

    async def execute(self, _query):
        value = self._execute_results[self._execute_index]
        self._execute_index += 1
        return _FakeScalarResult(value)

    def add(self, obj):
        self.added_items.append(obj)

    async def delete(self, obj):
        self.deleted_items.append(obj)

    async def commit(self):
        raise RuntimeError("commit failed")

    async def refresh(self, _obj):
        return None

    async def rollback(self):
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_create_character_rolls_back_on_commit_failure():
    db = _FailingCommitDbSession()
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

    assert db.rollback_calls == 1
    assert len(db.added_items) == 1


@pytest.mark.asyncio
async def test_delete_character_rolls_back_on_commit_failure():
    existing_character = SimpleNamespace(
        id="char-1",
        user_key="user-12345678",
    )
    db = _FailingCommitDbSession(execute_results=[existing_character])

    with pytest.raises(InternalServerError):
        await delete_character(
            character_id="char-1",
            db=db,
            user_key="user-12345678",
        )

    assert db.rollback_calls == 1
    assert db.deleted_items == [existing_character]


@pytest.mark.asyncio
async def test_create_character_from_text_rolls_back_on_commit_failure():
    db = _FailingCommitDbSession()
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

    assert db.rollback_calls == 1
    assert len(db.added_items) == 1
