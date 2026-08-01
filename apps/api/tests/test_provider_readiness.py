"""H1: TTS/STT provider fallback 제거 + readiness 게이트(오디오 기능 플래그 하).

- _get_provider가 미지/오타 provider와 운영 mock에 raise(조용한 Mock 폴백 금지).
- 단, 부팅(모듈 임포트·싱글톤 생성)은 죽이지 않는다(lazy resolution, 핸드오프 B2).
- audio_feature_enabled=True일 때만 /health/ready가 TTS/STT 라이브 구성을 게이트(G9).
"""

import pytest

from src.core.config import settings
from src.services.tts import TTSService
from src.services.stt import STTService


# ---------------------- 프로바이더 해석 (fallback 금지) ----------------------


def test_tts_provider_resolution_raises_on_unknown(monkeypatch):
    """운영에서 미지 tts_provider는 조용한 Mock 폴백 대신 raise(H1)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "tts_provider", "bogus")
    with pytest.raises(ValueError):
        TTSService()._get_provider()


def test_tts_prod_mock_resolution_raises(monkeypatch):
    """운영에서 tts_provider=mock은 무음 오디오 서빙을 막기 위해 raise(H1)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "tts_provider", "mock")
    with pytest.raises(ValueError):
        TTSService()._get_provider()


def test_stt_provider_resolution_raises_on_unknown(monkeypatch):
    """운영에서 미지 stt_provider(오타 포함)는 raise(H1)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "stt_provider", "eleven-labs")
    with pytest.raises(ValueError):
        STTService()._get_provider()


def test_service_construction_is_lazy_and_boot_safe(monkeypatch):
    """핸드오프 B2: 미지 provider·운영 mock이라도 생성자(임포트 싱글톤)는 죽지 않는다.

    provider 해석은 지연되어 synthesize/transcribe 호출 시점에만 raise한다.
    """
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "tts_provider", "bogus")
    monkeypatch.setattr(settings, "stt_provider", "bogus")
    # 생성 자체는 예외 없이 성공해야 한다(부팅 크래시 회귀 차단).
    TTSService()
    STTService()


def test_mock_provider_allowed_in_testing(monkeypatch):
    """테스트 환경(testing=True)에서는 mock provider 허용(결정성)."""
    monkeypatch.setattr(settings, "testing", True)
    monkeypatch.setattr(settings, "tts_provider", "mock")
    monkeypatch.setattr(settings, "stt_provider", "mock")
    assert TTSService()._get_provider() is not None
    assert STTService()._get_provider() is not None


# ---------------------- readiness 게이트 (기능 플래그 하) ----------------------


@pytest.mark.asyncio
async def test_readiness_blocks_when_tts_mock_and_audio_enabled(client, monkeypatch):
    """오디오 기능 ON + 운영 + tts mock → 503 + tts_provider_not_live(H1)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "mock")
    monkeypatch.setattr(settings, "stt_provider", "openai")

    r = await client.get("/health/ready")
    assert r.status_code == 503
    # M9: 공개 /ready는 provider_keys boolean만 노출(상세 사유는 인증된 detailed에만).
    assert r.json()["services"]["provider_keys"] == "unhealthy"
    assert "missing_keys" not in r.json()
    monkeypatch.setattr(settings, "admin_api_key", "testadminkey")
    d = await client.get("/health/detailed", headers={"X-Admin-Key": "testadminkey"})
    assert "tts_provider_not_live" in d.json().get("missing_keys", [])


@pytest.mark.asyncio
async def test_readiness_blocks_when_stt_unknown_and_audio_enabled(client, monkeypatch):
    """오디오 기능 ON + 운영 + stt 오타 → 503 + stt_provider_not_live(H1)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "google")
    monkeypatch.setattr(settings, "google_tts_api_key", "k")
    monkeypatch.setattr(settings, "stt_provider", "eleven-labs")

    r = await client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["services"]["provider_keys"] == "unhealthy"
    assert "missing_keys" not in r.json()
    monkeypatch.setattr(settings, "admin_api_key", "testadminkey")
    d = await client.get("/health/detailed", headers={"X-Admin-Key": "testadminkey"})
    assert "stt_provider_not_live" in d.json().get("missing_keys", [])


@pytest.mark.asyncio
async def test_readiness_ok_when_audio_live_configured(client, monkeypatch):
    """tts=google(+key), stt=openai → 오디오 사유 없음(H1)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "google")
    monkeypatch.setattr(settings, "google_tts_api_key", "k")
    monkeypatch.setattr(settings, "stt_provider", "openai")

    r = await client.get("/health/ready")
    missing = r.json().get("missing_keys", [])
    assert "tts_provider_not_live" not in missing
    assert "tts_key" not in missing
    assert "stt_provider_not_live" not in missing


@pytest.mark.asyncio
async def test_readiness_skips_audio_gate_when_feature_disabled(client, monkeypatch):
    """G9: 오디오 기능 OFF(기본) → tts mock이어도 readiness가 오디오로 막지 않는다."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "audio_feature_enabled", False)
    monkeypatch.setattr(settings, "tts_provider", "mock")
    monkeypatch.setattr(settings, "stt_provider", "mock")

    r = await client.get("/health/ready")
    missing = r.json().get("missing_keys", [])
    assert "tts_provider_not_live" not in missing
    assert "stt_provider_not_live" not in missing
