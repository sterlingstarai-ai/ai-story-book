"""Gemini 얼굴 보존 이미지 생성 — 응답 파싱 + 얼굴 레퍼런스 해석 테스트."""

import base64
import types

import pytest

from src.core.config import settings
from src.models.db import Character
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


@pytest.mark.asyncio
async def test_resolve_face_reference_non_gemini_skips(monkeypatch):
    monkeypatch.setattr(settings, "image_provider", "mock")
    spec = types.SimpleNamespace(character_id="any", character_ids=None)
    assert await _resolve_face_reference(spec) is None


@pytest.mark.asyncio
async def test_resolve_face_reference_no_characters(monkeypatch):
    monkeypatch.setattr(settings, "image_provider", "gemini")
    spec = types.SimpleNamespace(character_id=None, character_ids=None)
    assert await _resolve_face_reference(spec) is None


@pytest.mark.asyncio
async def test_resolve_face_reference_returns_photo_url(db_session, monkeypatch):
    # db_session 의존 → 테이블 생성 보장(app AsyncSessionLocal 과 동일 test.db)
    monkeypatch.setattr(settings, "image_provider", "gemini")
    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        session.add(
            Character(
                id="char-face-ref",
                name="아이",
                master_description="동화 주인공 설명입니다",
                appearance={},
                clothing={},
                personality_traits=[],
                user_key="uk-face-ref",
                from_photo=True,
                source_image_url="https://cdn.example/characters/char-face-ref/photo.jpg",
            )
        )
        session.add(
            Character(
                id="char-text-ref",
                name="텍스트",
                master_description="동화 주인공 설명입니다",
                appearance={},
                clothing={},
                personality_traits=[],
                user_key="uk-face-ref",
                from_photo=False,
            )
        )
        await session.commit()

    photo_spec = types.SimpleNamespace(character_id="char-face-ref", character_ids=None)
    assert (
        await _resolve_face_reference(photo_spec)
        == "https://cdn.example/characters/char-face-ref/photo.jpg"
    )

    text_spec = types.SimpleNamespace(character_id="char-text-ref", character_ids=None)
    assert await _resolve_face_reference(text_spec) is None
