from datetime import datetime, timezone
import importlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def signal(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('publish_backup_health')


def test_only_an_explicit_clean_check_is_healthy(signal):
    ok = '{"status":"OK","problems":[],"restore_authorized":false}'
    assert signal.measurement(SimpleNamespace(returncode=0, stdout=ok)) == 1
    for result in (SimpleNamespace(returncode=1, stdout=ok),
                   SimpleNamespace(returncode=0, stdout='not json'),
                   SimpleNamespace(returncode=0, stdout='{"status":"OK"}'),
                   SimpleNamespace(returncode=0, stdout='{"status":"OK","problems":["x"],"restore_authorized":false}')):
        assert signal.measurement(result) == 0


def test_publisher_runs_its_own_release_checker_without_writing_bytecode(signal, monkeypatch, capsys):
    assert Path(signal.CHECK) == Path(signal.__file__).resolve().with_name('check_backup_status.py')
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps({
        'status': 'OK', 'problems': [], 'restore_authorized': False,
    })))
    send = Mock(return_value=None)
    monkeypatch.setenv('PYTHONDONTWRITEBYTECODE', '0')
    monkeypatch.setattr(signal.subprocess, 'run', run)
    monkeypatch.setattr(signal, 'send', send)
    assert signal.main() == 0
    assert run.call_args.args[0] == ['/usr/bin/python3', '-B', signal.CHECK]
    assert run.call_args.kwargs['env']['PYTHONDONTWRITEBYTECODE'] == '1'
    assert run.call_args.kwargs['capture_output'] is True
    assert send.call_args.args[0] == 1
    assert json.loads(capsys.readouterr().out) == {'status': 'SIGNAL_SENT', 'healthy': True}


def test_signal_contains_only_health_and_fixed_resource(signal):
    value = signal.payload(0, datetime(2026, 11, 2, tzinfo=timezone.utc))['timeSeries'][0]
    assert value['points'][0]['value'] == {'int64Value': '0'}
    assert value['resource']['type'] == 'global'
    with pytest.raises(ValueError):
        signal.payload(True, datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        signal.payload(1, datetime.now())


def test_failure_stage_requires_explicit_unhealthy_service_result(signal):
    record = {'status': 'ALERT', 'problems': ['last_service_failed'], 'restore_authorized': False,
              'failure_stage_code': 5}

    def stage(*, code=1, **changes):
        return signal.failure_stage_code(SimpleNamespace(returncode=code, stdout=json.dumps(record | changes)))

    assert stage() == 5
    # An inconsistent checker response may report its own fixed failure,
    # but must never forward the input's claimed service stage.
    assert stage(code=0) == 18
    assert stage(problems=['backup_stale']) is None
    assert stage(problems=['backup_stale'], failure_reason_code=13) == 13
    assert stage(failure_reason_code=20) == 20
    assert stage(failure_reason_code=21) == 21
    assert stage(failure_reason_code=22, failure_stage_code=None) is None
    assert stage(failure_stage_code='arbitrary data') is None
    assert stage(failure_stage_code=True) is None
    assert stage(restore_authorized=True) == 18


@pytest.mark.parametrize(('healthy', 'reject_stage', 'expected'), [(0, False, True), (0, True, False), (1, False, None)])
def test_optional_failure_signal_keeps_primary_health_signal(signal, healthy, reject_stage, expected):
    class Monitoring:
        def __init__(self):
            self.points = []

        def open(self, req, timeout):
            if req.get_method() == 'GET':
                return BytesIO(b'{"access_token":"fixture-token"}')
            self.points.append(json.loads(req.data)['timeSeries'][0])
            if reject_stage and len(self.points) == 2:
                raise OSError('stage metric unavailable')
            reply = BytesIO()
            reply.status = 200
            return reply

    monitoring = Monitoring()
    assert signal.send(healthy, monitoring, stage_code=21) is expected
    health, *additional = monitoring.points
    assert health['metric']['type'] == signal.METRIC
    assert health['points'][0]['value'] == {'int64Value': str(healthy)}
    if healthy:
        assert additional == []
    else:
        stage, = additional
        assert stage['metric']['type'] == signal.FAILURE_METRIC
        assert stage['points'][0]['value'] == {'int64Value': '21'}
