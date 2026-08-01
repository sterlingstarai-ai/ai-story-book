"""M21 — 사진/그림 캐릭터 분석 파싱 실패 시 고정 mock('양갈래 소녀')을 성공 저장하던 fail-open 제거."""

import json

import httpx
import pytest

from src.core.config import settings
from src.services.photo_character import PhotoCharacterService


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_photo_analysis_invalid_json_raises(monkeypatch):
    """openai 프로바이더에서 비-JSON 응답은 mock으로 삼키지 않고 raise."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "k")

    async def fake_post(self, *args, **kwargs):
        return _FakeResp({"choices": [{"message": {"content": "sorry, I cannot"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    svc = PhotoCharacterService()
    with pytest.raises(json.JSONDecodeError):
        await svc.analyze_photo(b"fake-image-bytes")


@pytest.mark.asyncio
async def test_anthropic_analysis_invalid_json_raises(monkeypatch):
    """anthropic 프로바이더도 동일하게 raise."""
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_api_key", "k")

    async def fake_post(self, *args, **kwargs):
        return _FakeResp({"content": [{"text": "I cannot do that"}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    svc = PhotoCharacterService()
    with pytest.raises(json.JSONDecodeError):
        await svc.analyze_drawing(b"fake-image-bytes")


@pytest.mark.asyncio
async def test_mock_provider_still_returns_mock(monkeypatch):
    """mock 프로바이더 정상 경로는 여전히 _mock_analysis 반환(회귀 없음)."""
    monkeypatch.setattr(settings, "llm_provider", "mock")
    svc = PhotoCharacterService()
    result = await svc.analyze_photo(b"fake-image-bytes")
    assert isinstance(result, dict) and result
