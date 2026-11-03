"""Gemini TTS provider boundaries, without credentials or provider calls."""

import base64
import json
from unittest.mock import AsyncMock

import google.auth
import httpx
import pytest

from src.core.config import settings
from src.services.tts import GeminiCloudTTSProvider


class _Credential:
    token = "fixture-token"

    def refresh(self, _request):
        pass


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "google_gemini_tts_project", "test-project-123")
    monkeypatch.setattr(google.auth, "default", lambda **_: (_Credential(), "test-project-123"))
    budget = AsyncMock()
    monkeypatch.setattr("src.services.tts.require_gemini_tts_request_budget", budget)
    return budget


@pytest.mark.asyncio
async def test_gemini_styles_and_voices_preserve_text(gemini, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"audioContent": base64.b64encode(b"ID3demo").decode()})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    for style, voice in [("natural", "Kore"), ("animated", "Puck"), ("bedtime", "Kore")]:
        assert await GeminiCloudTTSProvider().synthesize("토리가 웃었어요.", voice, style=style) == b"ID3demo"
    assert gemini.await_count == 3
    payloads = [json.loads(request.content) for request in requests]
    assert all(p["input"]["text"] == "토리가 웃었어요." for p in payloads)
    assert len({p["input"]["prompt"] for p in payloads}) == 3
    assert [p["voice"]["name"] for p in payloads] == ["Kore", "Puck", "Kore"]
    assert all(p["voice"]["modelName"] == "gemini-2.5-flash-tts" for p in payloads)
    assert all(r.headers["x-goog-user-project"] == "test-project-123" for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content", [(403, {}), (200, {}), (200, {"audioContent": "not-valid!"}),
                                             (200, {"audioContent": base64.b64encode(b"not-audio").decode()})])
async def test_gemini_rejects_provider_error_and_bad_audio(gemini, monkeypatch, status, content):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=content)), **kw))
    with pytest.raises(ValueError):
        await GeminiCloudTTSProvider().synthesize("테스트", style="natural")


@pytest.mark.asyncio
async def test_gemini_rejects_unknown_voice_oversize_and_credentials(gemini, monkeypatch):
    with pytest.raises(ValueError):
        await GeminiCloudTTSProvider().synthesize("hello", voice="unknown")
    with pytest.raises(ValueError):
        await GeminiCloudTTSProvider().synthesize("가" * 1400)
    monkeypatch.setattr(google.auth, "default", lambda **_: (_ for _ in ()).throw(RuntimeError("sensitive")))
    with pytest.raises(ValueError, match="credentials unavailable") as error:
        await GeminiCloudTTSProvider().synthesize("hello")
    assert "sensitive" not in str(error.value)


def test_gemini_capabilities_require_explicit_project(monkeypatch):
    from src.core.audio_feature import narration_style_selection_supported, audio_readiness_issues
    monkeypatch.setattr(settings, "tts_provider", "google_gemini")
    monkeypatch.setattr(settings, "google_gemini_tts_project", None)
    assert "tts_project" in audio_readiness_issues()
    monkeypatch.setattr(settings, "google_gemini_tts_project", "invalid project")
    assert "tts_project" in audio_readiness_issues()
    monkeypatch.setattr(settings, "google_gemini_tts_project", "test-project-123")
    monkeypatch.setattr("src.core.audio_feature.audio_supported", lambda: True)
    assert narration_style_selection_supported()


@pytest.mark.asyncio
async def test_gemini_page_voice_style_are_separate_and_cached(db_session, monkeypatch):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from src.core.rate_limit import rate_limiter
    from src.models.db import NarrationVariant
    from src.routers.books import get_page_audio
    from src.services.storage import storage_service
    from src.services.tts import tts_service
    from tests.test_audio_completion import _narration_book
    from tests.test_narration_voices import _LockRedis

    book, _, _ = await _narration_book(db_session)
    monkeypatch.setattr(settings, "tts_provider", "google_gemini")
    monkeypatch.setattr(settings, "google_gemini_tts_project", "test-project-123")
    monkeypatch.setattr(settings, "generation_access_mode", "open")
    monkeypatch.setattr("src.routers.books.require_audio_supported", lambda: None)
    monkeypatch.setattr("src.core.audio_feature.audio_supported", lambda: True)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=_LockRedis()))
    synth = AsyncMock(return_value=b"ID3demo")
    monkeypatch.setattr(tts_service, "synthesize_page", synth)
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(side_effect=lambda _data, key, **_: "https://cdn.example.com/" + key))

    async def get(voice, style):
        return await get_page_audio(book.id, 1, language="en", voice=voice, style=style,
                                    db=db_session, user_key=book.user_key, profile_id=None)

    first = await get("warm", "animated")
    assert await get("warm", "animated") == first
    second = await get("deep", "animated")
    assert first != second
    assert [call.kwargs["voice"] for call in synth.await_args_list] == ["Kore", "Puck"]
    rows = (await db_session.scalars(select(NarrationVariant))).all()
    assert len(rows) == 2 and all(row.provider == "google_gemini" for row in rows)
