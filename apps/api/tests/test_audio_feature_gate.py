"""H1/G9: 오디오 비활성 GA 구성에서 오디오·발음 표면이 500이 아니라 명시적 미지원.

감사 확정 #2: audio_feature_enabled가 readiness에만 배선돼 있어, G9 결정대로 오디오를
끈 GA 구성에서 사용자가 낭독/발음을 탭할 때마다 500이 났다(기능 숨김도, 명시적
NOT_SUPPORTED 응답도 없음). 서버는 4xx로 명시하고, 클라이언트는 capabilities로 게이팅한다.
"""

import pytest

from src.core.config import settings


def _disable_audio(monkeypatch) -> None:
    monkeypatch.setattr(settings, "audio_feature_enabled", False)


# ───────────────────────── capabilities 노출 ─────────────────────────


@pytest.mark.asyncio
async def test_capabilities_reports_audio_unsupported_when_flag_off(client, monkeypatch):
    """G9 GA 구성(플래그 off) → 클라이언트가 오디오 UI를 숨길 수 있어야 한다."""
    _disable_audio(monkeypatch)
    r = await client.get("/v1/config/capabilities")
    assert r.status_code == 200, r.text
    assert r.json()["audio_supported"] is False


@pytest.mark.asyncio
async def test_capabilities_reports_audio_supported_when_live(client, monkeypatch):
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "google")
    monkeypatch.setattr(settings, "google_tts_api_key", "k")
    monkeypatch.setattr(settings, "stt_provider", "openai")

    r = await client.get("/v1/config/capabilities")
    assert r.status_code == 200, r.text
    assert r.json()["audio_supported"] is True


@pytest.mark.asyncio
async def test_capabilities_audio_unsupported_when_provider_not_live(client, monkeypatch):
    """플래그만 켜고 provider가 mock이면 무음 오디오 — 지원으로 광고하지 않는다(H1)."""
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "mock")
    monkeypatch.setattr(settings, "stt_provider", "mock")

    r = await client.get("/v1/config/capabilities")
    assert r.status_code == 200, r.text
    assert r.json()["audio_supported"] is False


# ───────────────────── 엔드포인트: 500 대신 명시적 4xx ─────────────────────


@pytest.mark.asyncio
async def test_page_audio_returns_not_supported_when_disabled(client, headers, monkeypatch):
    _disable_audio(monkeypatch)
    r = await client.get("/v1/books/no-such-book/pages/1/audio", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "AUDIO_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_batch_audio_returns_not_supported_when_disabled(client, headers, monkeypatch):
    _disable_audio(monkeypatch)
    r = await client.post("/v1/books/no-such-book/audio", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "AUDIO_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_pronunciation_audio_returns_not_supported_when_disabled(
    client, headers, monkeypatch
):
    _disable_audio(monkeypatch)
    r = await client.post(
        "/v1/pronunciation/evaluate-audio",
        headers=headers,
        data={"expected_text": "안녕하세요", "language": "ko"},
        files={"audio_file": ("a.m4a", b"xxxx", "audio/mp4")},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "AUDIO_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_audio_endpoints_not_gated_when_feature_live(client, headers, monkeypatch):
    """오디오가 라이브면 게이트가 정상 요청을 막지 않는다(과잉 차단 회귀 방지)."""
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "google")
    monkeypatch.setattr(settings, "google_tts_api_key", "k")
    monkeypatch.setattr(settings, "stt_provider", "openai")

    r = await client.get("/v1/books/no-such-book/pages/1/audio", headers=headers)
    # 게이트를 통과해 실제 리소스 조회까지 감(없는 책 → 404).
    assert r.status_code == 404, r.text
