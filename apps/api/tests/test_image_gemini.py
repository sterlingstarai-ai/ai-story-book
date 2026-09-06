"""Gemini 응답 파싱 + 승인된 캐릭터 일러스트 레퍼런스 해석 테스트."""

import base64
import types

import pytest

from src.core.config import settings
from src.core.exceptions import APIError, AuthorizationError
from src.models.db import Character, UserConsent
from src.services.image import _extract_gemini_image
from src.services.orchestrator import _resolve_face_reference


def test_extract_gemini_image_snake_case():
    raw = b"\x89PNG_fake_bytes"
    b64 = base64.b64encode(raw).decode()
    result = {
        "candidates": [
            {"content": {"parts": [{"inline_data": {"mime_type": "image/png", "data": b64}}]}}
        ]
    }
    data, mime = _extract_gemini_image(result)
    assert data == raw
    assert mime == "image/png"


def test_extract_gemini_image_camel_case():
    raw = b"jpeg_fake"
    b64 = base64.b64encode(raw).decode()
    result = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/jpeg", "data": b64}}]}}
        ]
    }
    data, mime = _extract_gemini_image(result)
    assert data == raw
    assert mime == "image/jpeg"


def test_extract_gemini_image_missing():
    assert _extract_gemini_image({"candidates": []})[0] is None
    assert _extract_gemini_image({})[0] is None


async def _approved_character(db, *, character_id, user_key):
    avatar_url = (
        f"{settings.s3_public_url.rstrip('/')}/characters/{character_id}/avatars/v2/portrait.png"
    )
    character = Character(
        id=character_id,
        name="동화 주인공",
        master_description="동화 주인공 설명입니다",
        appearance={},
        clothing={},
        personality_traits=[],
        user_key=user_key,
        from_photo=True,
        # A legacy source must never win over the parent's approved illustration.
        source_image_url=f"https://legacy.example/{character_id}/original.jpg",
        avatar_status="approved",
        avatar_version=2,
        avatar_url=avatar_url,
    )
    db.add(character)
    return character


def _photo_consent(user_key):
    return UserConsent(
        user_key=user_key, privacy=True, photos=True,
        data_processing=True, granted=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["mock", "gemini"])
async def test_resolve_face_reference_approved_avatar_is_provider_agnostic(
    db_session, monkeypatch, provider
):
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    character = await _approved_character(
        db_session, character_id="provider-avatar", user_key="uk-provider"
    )
    db_session.add(_photo_consent("uk-provider"))
    await db_session.commit()
    spec = types.SimpleNamespace(character_id=character.id, character_ids=None)
    assert await _resolve_face_reference(spec, "uk-provider") == character.avatar_url


@pytest.mark.asyncio
async def test_resolve_face_reference_no_characters(monkeypatch):
    monkeypatch.setattr(settings, "image_provider", "gemini")
    spec = types.SimpleNamespace(character_id=None, character_ids=None)
    assert await _resolve_face_reference(spec, "uk-any") is None


@pytest.mark.asyncio
async def test_resolve_face_reference_returns_owned_approved_avatar(db_session, monkeypatch):
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    character = await _approved_character(
        db_session, character_id="char-face-ref", user_key="uk-face-ref"
    )
    db_session.add_all([
        _photo_consent("uk-face-ref"),
        Character(
            id="char-text-ref", name="텍스트", master_description="동화 주인공 설명입니다",
            appearance={}, clothing={}, personality_traits=[], user_key="uk-face-ref",
            from_photo=False,
        ),
    ])
    await db_session.commit()
    photo_spec = types.SimpleNamespace(character_id=character.id, character_ids=None)
    reference = await _resolve_face_reference(photo_spec, "uk-face-ref")
    assert reference == character.avatar_url
    assert reference != character.source_image_url
    text_spec = types.SimpleNamespace(character_id="char-text-ref", character_ids=None)
    assert await _resolve_face_reference(text_spec, "uk-face-ref") is None
    # IDOR is a fail-closed error, never a silent text-only fallback.
    with pytest.raises(AuthorizationError):
        await _resolve_face_reference(photo_spec, "uk-attacker")


@pytest.mark.asyncio
async def test_resolve_face_reference_rejects_multiple_photo_characters(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    for character_id in ["mc-A", "mc-B"]:
        await _approved_character(db_session, character_id=character_id, user_key="uk-multi")
    db_session.add(_photo_consent("uk-multi"))
    await db_session.commit()
    # One reference cannot preserve two photo-derived people. Neither ordering
    # may silently discard the second character.
    for character_ids in [["mc-A", "mc-B"], ["mc-B", "mc-A"]]:
        spec = types.SimpleNamespace(character_id=None, character_ids=character_ids)
        with pytest.raises(APIError) as error:
            await _resolve_face_reference(spec, "uk-multi")
        assert error.value.error_code == "AVATAR_MULTIPLE_REFERENCES_UNSUPPORTED"
