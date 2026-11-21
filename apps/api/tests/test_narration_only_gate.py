"""Narration can be enabled independently without exposing pronunciation."""
import pytest
from fastapi import HTTPException, Response

from src.core import audio_feature as gate
from src.core.config import settings
from src.routers.config import get_capabilities


@pytest.mark.asyncio
async def test_narration_only_advertises_no_pronunciation(monkeypatch):
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', True)
    monkeypatch.setattr(settings, 'tts_provider', 'google_gemini')
    monkeypatch.setattr(settings, 'google_gemini_tts_project', 'test-project-123')
    monkeypatch.setattr(settings, 'google_gemini_tts_daily_request_limit', 3)
    monkeypatch.setattr(settings, 'google_gemini_tts_monthly_request_limit', 10)
    monkeypatch.setattr(settings, 'stt_provider', 'mock')
    assert gate.audio_readiness_issues() == []
    assert gate.narration_supported()
    assert not gate.audio_supported()
    gate.require_narration_supported()
    with pytest.raises(HTTPException):
        gate.require_audio_supported()
    caps = await get_capabilities(Response())
    assert caps['narration_supported'] is True
    assert caps['audio_supported'] is False
    assert caps['narration_audio_provider'] == 'google_gemini'


def test_narration_only_fails_closed_without_budget(monkeypatch):
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', True)
    monkeypatch.setattr(settings, 'tts_provider', 'google_gemini')
    monkeypatch.setattr(settings, 'google_gemini_tts_project', 'test-project-123')
    monkeypatch.setattr(settings, 'google_gemini_tts_daily_request_limit', 0)
    monkeypatch.setattr(settings, 'google_gemini_tts_monthly_request_limit', 10)
    assert 'tts_request_budget' in gate.audio_readiness_issues()
    with pytest.raises(HTTPException):
        gate.require_narration_supported()


def test_existing_audio_mode_still_requires_stt(monkeypatch):
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', False)
    monkeypatch.setattr(settings, 'tts_provider', 'google')
    monkeypatch.setattr(settings, 'google_tts_api_key', 'test')
    monkeypatch.setattr(settings, 'stt_provider', 'mock')
    assert 'stt_provider_not_live' in gate.audio_readiness_issues()
    assert not gate.narration_supported()
