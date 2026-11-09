"""Gemini TTS provider boundaries, without credentials or provider calls."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import google.auth
from google.auth.credentials import Credentials
import httpx
import pytest

from src.core.config import settings
from src.services.tts import GeminiCloudTTSProvider

# A structural MPEG-2 Layer III frame at 24 kHz and 32 kbps lasts 24 ms.
_FRAME = bytes.fromhex("fff344c4") + bytes(92)
_NORMAL_AUDIO = _FRAME * 100


class _Credential:
    token = "fixture-token"

    def refresh(self, _request):
        pass


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _ExpiringCredential(Credentials):
    def __init__(self, number):
        super().__init__()
        self.number = number
        self.refreshes = 0

    def refresh(self, _request):
        self.refreshes += 1
        self.token = f"fixture-token-{self.number}"
        self.expiry = _utc_now() + timedelta(hours=1)


@pytest.fixture
def expiring_adc(monkeypatch):
    credentials = []

    def discover(**_):
        credential = _ExpiringCredential(len(credentials) + 1)
        credentials.append(credential)
        return credential, None

    monkeypatch.setattr(google.auth, "default", discover)
    return credentials


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
        return httpx.Response(200, json={"audioContent": base64.b64encode(_NORMAL_AUDIO).decode()})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    for style, voice in [("natural", "Kore"), ("animated", "Puck"), ("bedtime", "Kore")]:
        assert await GeminiCloudTTSProvider().synthesize("토리가 웃었어요.", voice, style=style) == _NORMAL_AUDIO
    assert gemini.await_count == 3
    payloads = [json.loads(request.content) for request in requests]
    assert all(p["input"]["text"] == "토리가 웃었어요." for p in payloads)
    assert len({p["input"]["prompt"] for p in payloads}) == 3
    assert [p["voice"]["name"] for p in payloads] == ["Kore", "Puck", "Kore"]
    assert all(p["voice"]["modelName"] == "gemini-2.5-flash-tts" for p in payloads)
    assert all(r.headers["x-goog-user-project"] == "test-project-123" for r in requests)


@pytest.mark.asyncio
async def test_gemini_shares_adc_refresh_across_pages_and_renews_on_context_change(gemini, expiring_adc, monkeypatch):
    headers = []

    def handler(request):
        headers.append((request.headers["Authorization"], request.headers["x-goog-user-project"]))
        return httpx.Response(200, json={"audioContent": base64.b64encode(_NORMAL_AUDIO).decode()})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    provider = GeminiCloudTTSProvider()
    audio = await asyncio.gather(*(provider.synthesize("작은 별이 반짝였어요.") for _ in range(12)))

    assert audio == [_NORMAL_AUDIO] * 12
    assert headers == [("Bearer fixture-token-1", "test-project-123")] * 12
    assert [credential.refreshes for credential in expiring_adc] == [1]
    assert gemini.await_count == 12

    expiring_adc[0].expiry = _utc_now() + timedelta(seconds=30)
    assert await provider.synthesize("작은 별이 반짝였어요.") == _NORMAL_AUDIO
    assert headers[-1] == ("Bearer fixture-token-2", "test-project-123")

    monkeypatch.setattr(settings, "google_gemini_tts_project", "new-project-456")
    assert await provider.synthesize("작은 별이 반짝였어요.") == _NORMAL_AUDIO
    assert headers[-1] == ("Bearer fixture-token-3", "new-project-456")

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fictional/new-adc.json")
    assert await provider.synthesize("작은 별이 반짝였어요.") == _NORMAL_AUDIO
    assert headers[-1] == ("Bearer fixture-token-4", "new-project-456")
    assert [credential.refreshes for credential in expiring_adc] == [1, 1, 1, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", [401, 403])
async def test_gemini_rejection_evicts_token_without_retrying_synthesis(gemini, expiring_adc, monkeypatch, denial):
    tokens = []

    def handler(request):
        tokens.append(request.headers["Authorization"])
        if len(tokens) == 1:
            return httpx.Response(denial, json={})
        return httpx.Response(200, json={"audioContent": base64.b64encode(_NORMAL_AUDIO).decode()})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    provider = GeminiCloudTTSProvider()
    with pytest.raises(ValueError, match=str(denial)):
        await provider.synthesize("테스트")
    assert tokens == ["Bearer fixture-token-1"]
    assert gemini.await_count == 1
    assert await provider.synthesize("테스트") == _NORMAL_AUDIO
    assert tokens == ["Bearer fixture-token-1", "Bearer fixture-token-2"]
    assert len(expiring_adc) == gemini.await_count == 2


@pytest.mark.asyncio
async def test_gemini_auth_discovery_and_refresh_share_one_deadline(gemini, monkeypatch):
    from src.services import tts

    clock = 100
    timeouts = []

    def http_request(*_args, timeout, **_kwargs):
        nonlocal clock
        timeouts.append(timeout)
        clock += 16

    def discover(*, request, **_kwargs):
        request("https://fixture.invalid", timeout=5)
        return credential, None

    class SlowCredential:
        def refresh(self, request):
            request("https://fixture.invalid", timeout=120)
            request("https://fixture.invalid", timeout=120)

    credential = SlowCredential()
    monkeypatch.setattr(tts, "monotonic", lambda: clock)
    monkeypatch.setattr(google.auth, "default", discover)
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda: http_request)

    with pytest.raises(ValueError, match="credentials unavailable"):
        await GeminiCloudTTSProvider().synthesize("작은 별이 반짝였어요.")
    assert timeouts == [5, 4]
    gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_gemini_old_rejection_cannot_evict_replacement_token(gemini, expiring_adc, monkeypatch):
    first_request = asyncio.Event()
    first_response = asyncio.Event()
    tokens = []

    async def handler(request):
        tokens.append(request.headers["Authorization"])
        if len(tokens) == 1:
            first_request.set()
            await first_response.wait()
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"audioContent": base64.b64encode(_NORMAL_AUDIO).decode()})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    provider = GeminiCloudTTSProvider()
    pending = asyncio.create_task(provider.synthesize("테스트"))
    try:
        await asyncio.wait_for(first_request.wait(), timeout=5)
        expiring_adc[0].expiry = _utc_now() - timedelta(seconds=1)
        assert await provider.synthesize("테스트") == _NORMAL_AUDIO
    finally:
        first_response.set()
        with pytest.raises(ValueError, match="401"):
            await pending
    assert await provider.synthesize("테스트") == _NORMAL_AUDIO
    assert tokens == ["Bearer fixture-token-1", "Bearer fixture-token-2", "Bearer fixture-token-2"]
    assert len(expiring_adc) == 2 and gemini.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content", [
    (403, {}), (200, {}), (200, {"audioContent": "not-valid!"}),
    (200, {"audioContent": base64.b64encode(b"ID3demo").decode()}),
    (200, {"audioContent": base64.b64encode(_FRAME[:-1]).decode()}),
    (200, {"audioContent": base64.b64encode(_FRAME * 1746).decode()}),  # 41.904 s for a short sentence
])
async def test_gemini_rejects_provider_error_and_bad_audio(gemini, monkeypatch, status, content):
    from src.services import provider_runtime

    monkeypatch.setattr(settings, 'tts_provider', 'google_gemini')
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(provider_runtime, '_LOCAL_OBSERVATIONS', {})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=content)), **kw))
    with pytest.raises(ValueError):
        await GeminiCloudTTSProvider().synthesize("테스트", style="natural")
    state = await provider_runtime.provider_runtime_status(include_photo=False, include_audio=True)
    observation = next(item for item in state['observations'] if item['kind'] == 'tts')
    assert observation['reason'] == ('credentials_rejected' if status == 403 else 'invalid_response')


def test_gemini_mp3_allows_tagged_audio_and_longer_pages():
    from src.services.tts import _validate_gemini_mp3

    tagged_audio = bytes.fromhex("49443304000000000000") + _FRAME * 1746 + b"TAG" + bytes(125)
    _validate_gemini_mp3(tagged_audio, "어린 토끼가 숲속에서 엄마와 함께 긴 산책을 했어요. " * 3)


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


@pytest.mark.asyncio
async def test_gemini_adc_failure_invalidates_old_success_without_spending_budget(gemini, monkeypatch):
    from src.services import provider_runtime as runtime

    monkeypatch.setattr(settings, 'tts_provider', 'google_gemini')
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', True)
    monkeypatch.setattr(settings, 'stt_provider', 'mock')
    monkeypatch.setattr(runtime, '_LOCAL_OBSERVATIONS', {})
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'audioContent': base64.b64encode(_NORMAL_AUDIO).decode()})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    provider = GeminiCloudTTSProvider()
    assert await provider.synthesize('토리가 웃었어요.') == _NORMAL_AUDIO
    assert (await runtime.provider_runtime_status(include_audio=True))['status'] == 'healthy'

    with monkeypatch.context() as failure:
        def unavailable(**_):
            raise RuntimeError('sensitive fixture error')

        failure.setattr(google.auth, 'default', unavailable)
        with pytest.raises(ValueError, match='credentials unavailable'):
            await provider.synthesize('토리가 웃었어요.')
    state = await runtime.provider_runtime_status(include_audio=True)
    assert state['status'] == 'unverified'
    assert state['observations'][0]['reason'] == 'credentials_unavailable'
    assert gemini.await_count == len(requests) == 1

    assert await provider.synthesize('토리가 웃었어요.') == _NORMAL_AUDIO
    assert (await runtime.provider_runtime_status(include_audio=True))['status'] == 'healthy'
    assert gemini.await_count == len(requests) == 2


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
