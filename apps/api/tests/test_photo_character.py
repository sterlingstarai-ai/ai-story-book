"""M21 — 사진/그림 캐릭터 분석 파싱 실패 시 고정 mock('양갈래 소녀')을 성공 저장하던 fail-open 제거."""

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError
from src.services.photo_character import PhotoCharacterService


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_photo_analysis_invalid_json_raises(monkeypatch):
    """openai 프로바이더에서 비-JSON 응답은 mock으로 삼키지 않고 raise."""
    from tests.test_photo_provider_boundary import live_configuration
    live_configuration(monkeypatch)
    monkeypatch.setattr(settings, "photo_analysis_model", "gpt-4o")

    async def fake_post(self, *args, **kwargs):
        return _FakeResp({"choices": [{"finish_reason": "stop", "message": {"content": "sorry, I cannot"}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    svc = PhotoCharacterService()
    with pytest.raises(LLMError) as caught:
        await svc.analyze_photo(b"fake-image-bytes")
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert "sorry, I cannot" not in str(caught.value)


@pytest.mark.asyncio
async def test_anthropic_analysis_invalid_json_raises(monkeypatch):
    """anthropic 프로바이더도 동일하게 raise."""
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_api_key", "k")

    async def fake_post(self, *args, **kwargs):
        return _FakeResp({"content": [{"type": "text", "text": "I cannot do that"}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    svc = PhotoCharacterService()
    with pytest.raises(LLMError) as caught:
        await svc._analyze_with_anthropic("ZmFrZQ==", "Analyze the drawing")
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert "I cannot do that" not in str(caught.value)


@pytest.mark.asyncio
async def test_mock_provider_still_returns_mock(monkeypatch):
    """mock 프로바이더 정상 경로는 여전히 _mock_analysis 반환(회귀 없음)."""
    monkeypatch.setattr(settings, "llm_provider", "mock")
    svc = PhotoCharacterService()
    result = await svc.analyze_photo(b"fake-image-bytes")
    assert isinstance(result, dict) and result
