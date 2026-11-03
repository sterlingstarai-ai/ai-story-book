"""Synthetic provider responses; never call OpenAI or use real credentials."""
import base64
import io
import json
import sys
import warnings
from pathlib import Path

import httpx
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import check_new_openai_key as tool  # noqa: E402

KEY = 'sk-' + 'testonly' * 4


def _text(value='{"ok":true}'):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
        'status': 'completed', 'content': [{'type': 'output_text', 'text': value}]}]}


def _image():
    data = io.BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(data, format='PNG')
    return {'data': [{'b64_json': base64.b64encode(data.getvalue()).decode()}]}


def test_both_validated_without_exposing_response_or_key():
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        assert request.headers['authorization'] == 'Bearer ' + KEY
        return httpx.Response(200, json=_text() if len(seen) == 1 else _image())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = tool.probe(client, KEY)
    assert [url for url, _ in seen] == [tool.TEXT_URL, tool.IMAGE_URL]
    assert seen[0][1]['store'] is False
    assert result['status'] == 'BOTH_MODELS_VERIFIED_IN_ISOLATION'
    assert not result['production_changed'] and not result['production_readiness_verified']
    assert not result['credential_freshness_verified']
    assert KEY not in json.dumps(result)


def test_text_denial_does_not_trigger_image():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, json={'secret': KEY})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = tool.probe(client, KEY)
    assert len(calls) == 1 and result['status'] == 'TEXT_FAILED'
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize('text', ['{"ok":1}', '{"ok":false}', 'not json'])
def test_text_requires_boolean_true(text):
    with pytest.raises(tool.ProbeFailure):
        tool._check_text(_text(text))


def test_image_rejects_bad_data_and_probe_never_reports_readiness():
    with pytest.raises(tool.ProbeFailure):
        tool._check_image({'data': [{'b64_json': base64.b64encode(b'not-image').decode()}]})


def test_noninteractive_live_request_fails_before_prompt(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(tool.getpass, 'getpass', lambda *_: pytest.fail('must not prompt'))
    assert tool.main(['--allow-billable-requests']) == 1
    assert 'INTERACTIVE_TERMINAL_REQUIRED' in capsys.readouterr().out


def test_refuses_visible_input_fallback(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)

    def unsafe_prompt(*_args):
        warnings.warn('echo would be enabled', tool.getpass.GetPassWarning)
        pytest.fail('must refuse before reading')

    monkeypatch.setattr(tool.getpass, 'getpass', unsafe_prompt)
    assert tool.main(['--allow-billable-requests']) == 1
    assert 'PROBE_FAILED' in capsys.readouterr().out
