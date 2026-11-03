"""Read-only pilot inspection never prints or approves credentials."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import inspect_pilot_provider_rotation as tool  # noqa: E402

API = 'sha256:' + 'a' * 64
WORKER = 'sha256:' + 'b' * 64
SECRET = 'test-only-secret-never-emit'


def _item(name, image, **changes):
    values = {
        'LLM_PROVIDER': 'openai', 'LLM_MODEL': 'test-llm', 'LLM_API_KEY': SECRET,
        'IMAGE_PROVIDER': 'openai', 'IMAGE_MODEL': 'test-image', 'IMAGE_API_KEY': SECRET,
        'PHOTO_PROCESSING_ENABLED': 'true', 'PHOTO_ANALYSIS_API_KEY': SECRET,
        'AUDIO_FEATURE_ENABLED': 'false',
    }
    values.update(changes)
    return {'Name': '/' + name, 'Image': image, 'State': {'Running': True},
            'Config': {'Env': [f'{name}={value}' for name, value in values.items()]}}


def test_success_is_secret_free_and_never_approves_replacement():
    records = {'asb-pilot-api': _item('asb-pilot-api', API),
               'asb-pilot-worker': _item('asb-pilot-worker', WORKER)}
    result = tool.inspect_bindings(API, WORKER, inspect=records.__getitem__)
    assert result['api_worker_bindings_match'] is True
    assert result['llm_and_image_use_same_key'] is True
    assert result['photo_enabled'] and result['photo_key_configured'] and result['photo_uses_llm_key']
    assert not result['credential_validity_verified']
    assert not result['apply_authorized'] and not result['rollback_verified']
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize('mutation', ['image', 'stopped', 'credential', 'duplicate', 'missing'])
def test_rejects_mismatch_without_credential_output(mutation):
    records = {'asb-pilot-api': _item('asb-pilot-api', API),
               'asb-pilot-worker': _item('asb-pilot-worker', WORKER)}
    worker = records['asb-pilot-worker']
    if mutation == 'image':
        worker['Image'] = API
    elif mutation == 'stopped':
        worker['State']['Running'] = False
    elif mutation == 'credential':
        worker['Config']['Env'] = [item.replace(SECRET, 'other-secret') for item in worker['Config']['Env']]
    elif mutation == 'duplicate':
        worker['Config']['Env'].append('LLM_API_KEY=other-secret')
    else:
        worker['Config']['Env'] = [item for item in worker['Config']['Env'] if not item.startswith('LLM_API_KEY=')]
    with pytest.raises(tool.InspectionError) as error:
        tool.inspect_bindings(API, WORKER, inspect=records.__getitem__)
    assert SECRET not in str(error.value)


def test_docker_errors_are_suppressed(monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(tool.subprocess, 'run', fail)
    assert tool.main(['--inspect', '--api-image', API, '--worker-image', WORKER]) == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert json.loads(output.out)['apply_authorized'] is False
