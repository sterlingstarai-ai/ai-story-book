"""Narration adapter contract: actual audio or a sanitized failure, never mock silence."""

import json

import httpx
import pytest

from src.core.config import settings
from src.core.audio_feature import audio_readiness_issues
from src.services.tts import OpenAITTSProvider, TTSService


@pytest.mark.asyncio
async def test_openai_narration_payload_and_bytes(monkeypatch):
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-secret")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, content=b"ID3-test-audio", headers={"content-type": "audio/mpeg"}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    result = await OpenAITTSProvider().synthesize(
        "별빛이 반짝였어요.", language="ko", speaking_rate=0.9
    )
    assert result == b"ID3-test-audio"
    payload = json.loads(requests[0].content)
    assert payload["input"] == "별빛이 반짝였어요."
    assert payload["speed"] == 0.9
    assert payload["response_format"] == "mp3"
    assert "expressively" in payload["instructions"]
    assert "exactly as written" in payload["instructions"]
    assert "Do not add introductions" in payload["instructions"]
    assert "test-secret" not in str(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,content_type",
    [(429, "application/json"), (200, "application/json"), (200, "audio/mpeg")],
)
async def test_openai_narration_rejects_failure_or_empty(monkeypatch, status, content_type):
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-secret")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    status, content=b"", headers={"content-type": content_type}
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(ValueError):
        await OpenAITTSProvider().synthesize("Hello")


@pytest.mark.asyncio
async def test_openai_narration_missing_key_and_oversize_fail_before_network(monkeypatch):
    monkeypatch.setattr(settings, "openai_tts_api_key", None)
    with pytest.raises(ValueError, match="not configured"):
        await OpenAITTSProvider().synthesize("Hello")
    with pytest.raises(ValueError, match="4096"):
        await OpenAITTSProvider().synthesize("a" * 4097)


def test_openai_narration_readiness_requires_explicit_key(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_api_key", None)
    assert "tts_key" in audio_readiness_issues()
    monkeypatch.setattr(settings, "openai_tts_api_key", "test")
    assert "tts_key" not in audio_readiness_issues()


@pytest.mark.asyncio
@pytest.mark.parametrize("age", ["3-5", "5-7", "7-9", "adult", None, "unknown"])
async def test_narration_uses_natural_speed_without_changing_story(monkeypatch, age):
    async def allow(_kind):
        return None

    class CaptureProvider:
        async def synthesize(self, text, voice, *, language, speaking_rate):
            assert text == "페이지 1의 비밀을 찾아요."
            assert speaking_rate == 1.0
            return b"audio"

    monkeypatch.setattr("src.services.tts.require_daily_generation_budget", allow)
    service = TTSService()
    service._provider = CaptureProvider()
    assert await service.synthesize_page("페이지 1의 비밀을 찾아요.", target_age=age) == b"audio"
