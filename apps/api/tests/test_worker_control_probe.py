"""The lightweight operator probe must reject busy, missing and foreign workers."""

from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.mark.parametrize('condition', ['idle', 'busy', 'missing', 'foreign', 'extra', 'duplicate'])
@pytest.mark.parametrize('namespace', ['', 'private_fixture'])
@pytest.mark.parametrize('paired', [False, True])
def test_control_probe_keeps_identity_idle_and_privacy_boundaries(monkeypatch, capsys, condition, namespace, paired):
    path = Path(__file__).resolve().parents[3] / 'scripts/worker_control_probe.py'
    spec = importlib.util.spec_from_file_location('worker_control_probe_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    applications = []

    class App:
        def __init__(self, _name, *, broker):
            assert broker == 'redis://fixture-only/1'
            self.conf = SimpleNamespace(broker_transport_options={})
            self.closed = False
            applications.append(self)

        def connection_for_read(self):
            return nullcontext()

        def close(self):
            self.closed = True

    class Control:
        def __init__(self, *, app):
            self.app = app

        def broadcast(self, kind, *, connection, reply, timeout):
            assert connection is None and reply is True and timeout == 3
            expected = {'ok': 'pong'} if kind == 'ping' else []
            if condition == 'busy' and kind != 'ping':
                expected = [{'private_task_argument': 'must-never-be-printed'}]
            if condition == 'missing':
                return []
            node = 'celery@foreign' if condition == 'foreign' else f'celery@{socket.gethostname()}'
            replies = [{node: expected}]
            if condition == 'duplicate':
                return replies * 2
            return replies + [{'celery@extra': expected}] if condition == 'extra' else replies

    celery = ModuleType('celery')
    celery.Celery = App
    control = ModuleType('celery.app.control')
    control.Control = Control
    monkeypatch.setitem(sys.modules, 'celery', celery)
    monkeypatch.setitem(sys.modules, 'celery.app.control', control)
    monkeypatch.setenv('CELERY_BROKER_URL', 'redis://fixture-only/1')
    monkeypatch.setenv('CELERY_REDIS_NAMESPACE', namespace)
    source = module.worker_control_source(
        ('ping', 'active', 'reserved', 'scheduled'), timeout=3,
        expected_hostnames=(socket.gethostname(), 'extra') if paired else None,
    )
    assert 'src.worker' not in source
    exec(compile(source, '<fixed worker probe>', 'exec'), {})
    output = capsys.readouterr().out
    assert 'private_task_argument' not in output and 'fixture-only' not in output
    assert json.loads(output) == {
        name: condition == 'extra' if paired else (
            condition == 'idle' or (name == 'ping' and condition == 'busy')
        )
        for name in ('ping', 'active', 'reserved', 'scheduled')
    }
    assert applications[0].closed
    assert applications[0].conf.broker_transport_options == (
        {'global_keyprefix': namespace + ':broker:'} if namespace else {}
    )
