import importlib
import importlib.util
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
def test_refresh_can_recover_quota_before_observation_expires(monkeypatch, capsys, reason, expected):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    settings = SimpleNamespace(
        testing=False, provider_observation_ttl_seconds=86400,
        llm_provider='openai', llm_model='gpt-5.6-sol', image_provider='openai',
        image_model='gpt-image-2', audio_feature_enabled=False,
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


def test_candidate_bootstrap_spends_only_its_narration_claim(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_pilot_provider_refresh')
    identifier, image = 'a' * 64, 'sha256:' + 'b' * 64
    inspect = json.dumps({'Id': identifier, 'Image': image, 'Name': '/asb-narration-next-api',
                          'Running': True, 'Restart': 'no'}).encode()
    docker = Mock(side_effect=[inspect, b'REQUIRED_TTS\n', b'TTS_VERIFIED\n', b'FRESH_AUDIO\n'])
    claim = Mock(return_value=True)
    monkeypatch.setattr(runner, 'docker', docker)
    monkeypatch.setattr(runner, 'claim', claim)
    ledger = tmp_path / 'narration.sqlite'
    runner.bootstrap_isolated_narration(identifier, image, ledger)
    claim.assert_called_once_with(ledger)
    assert [call.kwargs['data'] for call in docker.call_args_list[1:]] == [
        runner._CHECK, runner._TTS_PROBE, runner._CHECK]
