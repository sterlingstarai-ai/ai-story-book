"""Staged narration mode is pinned without inspecting real containers."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_pilot_adapter')
    adapter = module.NarrationPilotAdapter.__new__(module.NarrationPilotAdapter)
    adapter.identities = {name: name for name in ('old_api', 'old_worker', 'new_api', 'new_worker')}
    adapter.expected_google_project = 'test-project-123'
    adapter.expected_daily_limit = 3
    adapter.expected_monthly_limit = 10
    adapter.expected_narration_only = False
    base = ['UNRELATED=unchanged', 'AUDIO_FEATURE_ENABLED=false']
    staged = ['UNRELATED=unchanged', 'AUDIO_FEATURE_ENABLED=true', 'TTS_PROVIDER=google_gemini',
              'GOOGLE_GEMINI_TTS_PROJECT=test-project-123', 'GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT=3',
              'GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT=10']
    def item(env):
        return {'Config': {'Env': env}, 'Mounts': [], 'HostConfig': {'NetworkMode': 'isolated'}}
    items = {key: item(list(base if key.startswith('old_') else staged)) for key in adapter.identities}
    adapter._full_inspect = lambda identifier: items[identifier]
    return module, adapter, items


def test_legacy_mode_accepts_absent_flag(sample):
    _, adapter, _ = sample
    adapter._verify_configurations()


@pytest.mark.parametrize('value', ['true', 1, None])
def test_constructor_requires_boolean_mode(sample, monkeypatch, value):
    module, _, _ = sample
    monkeypatch.setattr(module, '_validate_ids', lambda ids: ids)
    with pytest.raises(module.PilotAdapterError, match='explicitly boolean'):
        module.NarrationPilotAdapter(
            runtime=None, identities={}, image_ids={}, backup_arguments={},
            expected_google_project='test-project-123', expected_daily_limit=3,
            expected_monthly_limit=10, proxy_id='a' * 64, proxy_image_id='sha256:' + 'b' * 64,
            expected_proxy_config_sha256='c' * 64, expected_monitor_manifest_sha256='d' * 64,
            expected_narration_only=value,
        )


def test_narration_only_requires_explicit_match_on_both_containers(sample):
    module, adapter, items = sample
    adapter.expected_narration_only = True
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=true')
    adapter._verify_configurations()
    items['new_worker']['Config']['Env'][-1] = 'AUDIO_NARRATION_ONLY_ENABLED=false'
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


def test_mode_is_not_silently_enabled(sample):
    module, adapter, items = sample
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=true')
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


@pytest.mark.parametrize('value', ['1', 'yes', '', 'false ', 'TRUE-ish'])
def test_mode_rejects_ambiguous_values(sample, value):
    module, adapter, items = sample
    items['new_api']['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=' + value)
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


def test_unrelated_environment_cannot_change(sample):
    module, adapter, items = sample
    adapter.expected_narration_only = True
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=true')
    items['new_api']['Config']['Env'][0] = 'UNRELATED=changed'
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


def test_matching_configuration_does_not_authorize_release(sample):
    module, adapter, _ = sample
    adapter.expected_narration_only = True
    names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
             'new_api': 'asb-narration-next-api', 'new_worker': 'asb-narration-next-worker'}
    adapter.image_ids = {}
    adapter.controls = SimpleNamespace(verify_pinned_images=lambda *_: None)
    adapter.runtime = SimpleNamespace(inspect=lambda ident: {
        'id': ident, 'name': names[ident], 'running': ident.startswith('old_'), 'restart_policy': 'no',
    })
    adapter._ids = lambda _: None
    adapter._verify_configurations = lambda: None
    adapter._verify_monitor_precedes_candidate = lambda: None
    adapter._verify_proxy = lambda: None
    with pytest.raises(module.PilotAdapterError, match='guards are not yet implemented'):
        adapter.preflight(adapter.identities)
