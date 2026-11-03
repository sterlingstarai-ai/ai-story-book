import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return (importlib.import_module('check_privacy_purge_queue'),
            importlib.import_module('publish_privacy_purge_health'))


def test_runtime_source_binding_allows_stopped_containers_but_rejects_mismatch(modules):
    check, _ = modules
    source = 'postgresql+psycopg://user:synthetic-secret@db.example:5432/storybook'

    class Runtime:
        def __init__(self, urls):
            self.urls = urls

        def _run(self, command, timeout):
            return json.dumps(['DATABASE_URL=' + value for value in self.urls[command[-1]]])

    same = {'asb-pilot-api': [source], 'asb-pilot-worker': [source]}
    check.check_live_source_binding(Runtime(same), source)
    for runtime in (Runtime({**same, 'asb-pilot-worker': []}),
                    Runtime({**same, 'asb-pilot-worker': [source.replace('/storybook', '/other')]}),
                    Runtime({**same, 'asb-pilot-worker': [source, source]})):
        with pytest.raises(ValueError) as error:
            check.check_live_source_binding(runtime, source)
        assert 'synthetic-secret' not in str(error.value)
    with pytest.raises(ValueError):
        check.source_identity(source + '?host=other.example')
    with pytest.raises(ValueError):
        check.source_identity(source + '?options=-csearch_path%3Dother')


def test_binary_metric_never_treats_failed_or_ambiguous_check_as_healthy(modules):
    _, publish = modules
    def measure(value, code=0):
        return publish.measurement(SimpleNamespace(returncode=code, stdout=json.dumps(value)))
    assert measure({'status': 'OK', 'restore_authorized': False}) == 1
    assert measure({'status': 'OK', 'restore_authorized': 0}) == 0
    assert measure({'status': 'ALERT', 'restore_authorized': False}) == 0
    assert measure({'status': 'OK', 'restore_authorized': False}, 1) == 0
    assert measure({'status': 'OK', 'restore_authorized': False, 'user': 'sensitive'}) == 0
    with pytest.raises(ValueError):
        publish.check_command({})


def test_cloud_signal_contains_only_binary_metric_and_no_queue_details(modules):
    _, publish = modules

    class Response:
        status = 200

        def __init__(self, body=b'{}'):
            self.body = io.BytesIO(body)

        def read(self, *args):
            return self.body.read(*args)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Opener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout):
            self.requests.append(request)
            return Response(b'{"access_token":"synthetic-token"}' if len(self.requests) == 1 else b'{}')

    opener = Opener()
    publish.send(0, opener)
    body = json.loads(opener.requests[1].data)
    point = body['timeSeries'][0]
    assert point['metric'] == {'type': publish.METRIC}
    assert point['points'][0]['value'] == {'int64Value': '0'}
    assert 'sensitive-user' not in json.dumps(body) and 'sensitive-target' not in json.dumps(body)


def test_local_candidate_is_new_private_and_excludes_runtime_configuration(modules, monkeypatch, tmp_path, capsys):
    builder = importlib.import_module('build_privacy_purge_monitor_bundle')
    source_root = tmp_path / 'source'
    api_source = source_root / 'apps/api/src'
    api_source.mkdir(parents=True)
    (api_source / '__init__.py').write_text('# synthetic\n')
    for item in builder.FILES:
        path = source_root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic\n')
    monkeypatch.setattr(builder, 'ROOT', source_root)
    output = tmp_path / 'candidate'
    assert builder.main(['--output', str(output)]) == 0
    assert json.loads(capsys.readouterr().out)['installed'] is False
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['runtime_configuration_copied'] is False
    assert set(manifest['files']) == {'apps/api/src/__init__.py', *builder.FILES}
    assert output.stat().st_mode & 0o777 == 0o700
    marker = output / 'keep'
    marker.write_text('existing')
    assert builder.main(['--output', str(output)]) == 1
    assert marker.read_text() == 'existing'
    (api_source / '.env').write_text('synthetic-only')
    assert builder.main(['--output', str(tmp_path / 'secret-candidate')]) == 1
    assert not (tmp_path / 'secret-candidate').exists()
