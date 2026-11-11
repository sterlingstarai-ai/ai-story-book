import importlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


spec = importlib.util.spec_from_file_location(
    'provider_probe_budget', Path(__file__).resolve().parents[3] / 'scripts/provider_probe_budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


@pytest.fixture
def ledger(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / 'ledger.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE claims (claimed_at INTEGER NOT NULL)')
        db.execute('PRAGMA user_version = 1')
    path.chmod(0o600)
    return path


def test_claim_before_attempt_prevents_retry_and_clock_rollback(ledger):
    assert budget.claim(ledger, now=1_000_000)
    assert not budget.claim(ledger, now=1_000_001)
    with pytest.raises(budget.ProbeBudgetError):
        budget.claim(ledger, now=999_999)
    assert budget.claim(ledger, now=1_064_800)


def test_monthly_cap_and_expiration(ledger):
    for slot in range(41):
        assert budget.claim(ledger, now=1_000_000 + slot * 18 * 3600)
    assert not budget.claim(ledger, now=1_000_000 + 41 * 18 * 3600)
    assert budget.claim(ledger, now=1_000_000 + 31 * 86400)


def test_partial_refresh_does_not_consume_the_last_claim(ledger):
    start = 1_000_000
    interval = 18 * 3600
    for slot in range(40):
        assert budget.claim(ledger, now=start + slot * interval)
    with pytest.raises(budget.ProbeFollowupUnavailable):
        budget.claim(ledger, now=start + 40 * interval, require_next_interval=True)
    assert budget.claim(ledger, now=start + 40 * interval)
    assert not budget.claim(ledger, now=start + 41 * interval)


def test_concurrent_claims_cannot_exceed_limit(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: budget.claim(ledger, now=1_000_000), range(8)))
    assert sum(claims) == 1


def test_missing_or_insecure_ledger_fails_closed(ledger):
    ledger.chmod(0o644)
    with pytest.raises(budget.ProbeBudgetError):
        budget.claim(ledger, now=1_000_000)
    ledger.unlink()
    with pytest.raises(budget.ProbeBudgetError):
        budget.claim(ledger, now=1_000_000)


@pytest.mark.parametrize(('reason', 'expected'), [
    ('quota_exhausted', 'REQUIRED'),
    ('credentials_rejected', 'UNAVAILABLE'),
])
@pytest.mark.parametrize('image_model', ['gpt-image-2', 'gpt-image-2.6-flare'])
def test_refresh_can_recover_quota_before_observation_expires(monkeypatch, capsys, reason, expected, image_model):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    settings = SimpleNamespace(
        testing=False, provider_observation_ttl_seconds=86400,
        llm_provider='openai', llm_model='gpt-5.6-sol', image_provider='openai',
        image_model=image_model, audio_feature_enabled=False,
    )
    state = {'status': 'unavailable', 'observations': [
        {'kind': 'llm', 'reason': reason, 'status': 'unavailable'},
        {'kind': 'image', 'status': 'healthy'},
    ]}
    monkeypatch.setitem(sys.modules, 'src.core.config', SimpleNamespace(settings=settings))
    monkeypatch.setitem(sys.modules, 'src.services.provider_runtime',
                        SimpleNamespace(provider_runtime_status=AsyncMock(return_value=state)))
    exec(runner._CHECK, {})
    assert capsys.readouterr().out.strip() == expected


@pytest.mark.parametrize('slow_check_seconds', [30, 61])
def test_observation_startup_has_a_bounded_budget_without_spending(monkeypatch, ledger, slow_check_seconds):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    identifier, image = 'a' * 64, 'sha256:' + 'b' * 64

    def docker(*args, data=None, timeout=20):
        if args[0] == 'inspect':
            return json.dumps({'Id': identifier, 'Image': image, 'Name': '/asb-pilot-api',
                               'Running': True}).encode()
        assert data == runner._CHECK
        assert timeout <= 60
        if slow_check_seconds > timeout:
            raise subprocess.TimeoutExpired('observation-check', timeout)
        return b'FRESH_AUDIO\n'

    claim = Mock(side_effect=AssertionError('fresh observations must not spend a claim'))
    monkeypatch.setattr(runner, 'docker', docker)
    monkeypatch.setattr(runner, 'claim', claim)
    monkeypatch.setattr(runner, 'assert_no_narration_recovery', lambda: None)
    if slow_check_seconds <= 60:
        assert runner.refresh(image, ledger, ledger.parent, execute=True) == 'OBSERVATIONS_FRESH'
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            runner.refresh(image, ledger, ledger.parent, execute=True)
    claim.assert_not_called()


@pytest.mark.parametrize(('openai_age', 'expected'), [
    (5 * 3600, 'REQUIRED_TTS'),
    (5 * 3600 + 1, 'REQUIRED_TTS_WITH_OPENAI'),
])
@pytest.mark.parametrize(('tts_reason', 'tts_status'), [
    ('no_recent_observation', 'unverified'),
    ('credentials_unavailable', 'unverified'),
    ('credentials_rejected', 'unavailable'),
])
@pytest.mark.parametrize('tts_provider', ['google_gemini', 'openai_realtime'])
def test_refresh_tts_only_requires_runway_until_next_claim(monkeypatch, capsys, openai_age, expected,
                                                          tts_reason, tts_status, tts_provider):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    now = 1_000_000
    monkeypatch.setattr(time, 'time', lambda: now)
    settings = SimpleNamespace(
        testing=False, provider_observation_ttl_seconds=86400,
        llm_provider='openai', llm_model='gpt-5.6-sol', image_provider='openai',
        image_model='gpt-image-2', audio_feature_enabled=True,
        tts_provider=tts_provider, audio_narration_only_enabled=True,
    )
    observations = [
        {'kind': 'llm', 'status': 'healthy', 'observed_at': now},
        {'kind': 'image', 'status': 'healthy', 'observed_at': now - openai_age},
        {'kind': 'tts', 'status': tts_status, 'reason': tts_reason},
    ]
    monkeypatch.setitem(sys.modules, 'src.core.config', SimpleNamespace(settings=settings))
    monkeypatch.setitem(sys.modules, 'src.core.rate_limit', SimpleNamespace(
        rate_limiter=SimpleNamespace(close=AsyncMock())))
    monkeypatch.setitem(sys.modules, 'src.services.provider_runtime', SimpleNamespace(
        provider_runtime_status=AsyncMock(return_value={'observations': observations})))
    exec(runner._CHECK, {})
    if tts_provider == 'openai_realtime' and tts_reason == 'credentials_rejected':
        expected = 'UNAVAILABLE'
    assert capsys.readouterr().out.strip() == expected


@pytest.mark.parametrize('tts_provider', ['google_gemini', 'openai_realtime', 'openai'])
def test_refresh_synthesizes_only_with_an_eligible_configured_adapter(monkeypatch, capsys, tts_provider):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    settings = SimpleNamespace(audio_feature_enabled=True, audio_narration_only_enabled=True,
                               tts_provider=tts_provider)
    synthesize = AsyncMock(return_value=b'synthetic audio')
    provider = SimpleNamespace(synthesize=synthesize)
    close = AsyncMock()
    monkeypatch.setitem(sys.modules, 'src.core.config', SimpleNamespace(settings=settings))
    monkeypatch.setitem(sys.modules, 'src.core.rate_limit', SimpleNamespace(rate_limiter=SimpleNamespace(close=close)))
    monkeypatch.setitem(sys.modules, 'src.services.tts', SimpleNamespace(tts_service=SimpleNamespace(provider=provider)))
    monkeypatch.setitem(sys.modules, 'src.services.provider_runtime', SimpleNamespace(
        provider_runtime_status=AsyncMock(return_value={'observations': [{'kind': 'tts', 'status': 'healthy'}]})))
    exec(runner._TTS_PROBE, {})
    if tts_provider == 'openai':
        assert capsys.readouterr().out.strip() == 'TTS_FAILED'
        synthesize.assert_not_awaited()
    else:
        assert capsys.readouterr().out.strip() == 'TTS_VERIFIED'
        synthesize.assert_awaited_once_with('작은 별이 반짝였어요.', language='ko', style='natural')
        close.assert_awaited_once()


@pytest.mark.parametrize(('openai_older', 'refresh_now', 'monthly_tight'), [
    (False, False, False), (True, False, False), (False, True, False), (False, False, True),
])
def test_narration_refresh_preserves_budget_and_verifies_result(monkeypatch, ledger, openai_older, refresh_now,
                                                               monthly_tight):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    identifier, image = 'a' * 64, 'sha256:' + 'b' * 64
    inspect = json.dumps({'Id': identifier, 'Image': image, 'Name': '/asb-pilot-api', 'Running': True}).encode()
    status = b'REQUIRED_TTS_WITH_OPENAI\n' if openai_older else b'REQUIRED_TTS\n'
    if monthly_tight:
        start = 1_000_000
        interval = 18 * 3600
        for slot in range(40):
            assert budget.claim(ledger, now=start + slot * interval)
        monkeypatch.setattr(time, 'time', lambda: start + 40 * interval)
    refresh_openai = openai_older or refresh_now or monthly_tight
    responses = [inspect, status]
    if refresh_openai:
        responses.append(b'PROVIDER_PROBE_OK\n')
    responses += [b'TTS_VERIFIED\n', b'FRESH_AUDIO\n', inspect, status]
    docker = Mock(side_effect=responses)
    source = Mock(return_value=b'pinned OpenAI probe')
    monkeypatch.setattr(runner, 'docker', docker)
    monkeypatch.setattr(runner, '_source', source)
    monkeypatch.setattr(runner, 'assert_no_narration_recovery', lambda: None)

    assert runner.refresh(image, ledger, ledger.parent, execute=True, refresh_now=refresh_now) == 'PROBE_VERIFIED'
    assert runner.refresh(image, ledger, ledger.parent, execute=True,
                          refresh_now=refresh_now) == 'PROBE_REQUIRED_BUDGET_DEFERRED'
    payloads = [call.kwargs['data'] for call in docker.call_args_list if 'data' in call.kwargs]
    assert payloads == [runner._CHECK] + ([b'pinned OpenAI probe'] if refresh_openai else []) + [
        runner._TTS_PROBE, runner._CHECK, runner._CHECK,
    ]
    assert source.call_count == (2 if openai_older or refresh_now else int(monthly_tight))
    with sqlite3.connect(ledger) as db:
        assert db.execute('SELECT COUNT(*) FROM claims').fetchone() == (41 if monthly_tight else 1,)


@pytest.mark.parametrize('status', [b'REQUIRED_TTS\n', b'REQUIRED_TTS_WITH_OPENAI\n'])
def test_candidate_bootstrap_spends_only_its_narration_claim(monkeypatch, tmp_path, status):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    identifier, image = 'a' * 64, 'sha256:' + 'b' * 64
    inspect = json.dumps({'Id': identifier, 'Image': image, 'Name': '/asb-narration-next-api',
                          'Running': True, 'Restart': 'no'}).encode()
    docker = Mock(side_effect=[inspect, status, b'TTS_VERIFIED\n', b'FRESH_AUDIO\n'])
    claim = Mock(return_value=True)
    monkeypatch.setattr(runner, 'docker', docker)
    monkeypatch.setattr(runner, 'claim', claim)
    ledger = tmp_path / 'narration.sqlite'
    runner.bootstrap_isolated_narration(identifier, image, ledger)
    claim.assert_called_once_with(ledger)
    assert [call.kwargs['data'] for call in docker.call_args_list[1:]] == [
        runner._CHECK, runner._TTS_PROBE, runner._CHECK]
