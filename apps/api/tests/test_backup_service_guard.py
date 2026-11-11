"""Failure-injection tests for the not-yet-deployed backup service guard."""

import fcntl
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def guard_module(monkeypatch):
    path = Path(__file__).resolve().parents[3] / 'scripts' / 'backup_service_guard.py'
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('asb_backup_service_guard_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRuntime:
    def __init__(self):
        self.state = {'asb-pilot-api': True, 'asb-pilot-worker': True}
        self.calls = []
        self.fail_start = False
        self.live = True

    def running(self, name):
        return self.state[name]

    def stop(self, name):
        self.calls.append(('stop', name))
        self.state[name] = False

    def start(self, name):
        self.calls.append(('start', name))
        if self.fail_start and name == 'asb-pilot-worker':
            raise RuntimeError('synthetic failure')
        self.state[name] = True

    def reload_proxy(self):
        self.calls.append(('reload', 'asb-pilot-nginx'))

    def verify_recovery(self):
        self.calls.append(('probe', 'api-and-worker'))
        if not self.live:
            raise RuntimeError('synthetic liveness failure')


def test_backup_runs_only_after_idle_check_and_services_are_restarted(guard_module, tmp_path):
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)

    def check_idle():
        assert runtime.state == {'asb-pilot-api': False, 'asb-pilot-worker': True}

    def backup():
        assert not any(runtime.state.values())
        assert (tmp_path / 'restart-required.json').exists()
        return 'synthetic-result'

    assert guard.run(verify_idle=check_idle, backup=backup) == 'synthetic-result'
    assert runtime.calls == [('stop', 'asb-pilot-api'), ('stop', 'asb-pilot-worker'),
                             ('start', 'asb-pilot-worker'), ('start', 'asb-pilot-api'),
                             ('probe', 'api-and-worker'),
                             ('reload', 'asb-pilot-nginx')]
    assert all(runtime.state.values())
    assert not (tmp_path / 'restart-required.json').exists()


@pytest.mark.parametrize('fail_stage', ['idle', 'backup'])
def test_failure_restores_services_and_never_hides_the_failure(guard_module, tmp_path, fail_stage):
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    called = []

    def idle():
        if fail_stage == 'idle':
            raise ValueError('not idle')

    def backup():
        called.append(True)
        raise ValueError('backup failed')

    with pytest.raises(ValueError):
        guard.run(verify_idle=idle, backup=backup)
    assert all(runtime.state.values())
    assert bool(called) == (fail_stage == 'backup')
    assert not (tmp_path / 'restart-required.json').exists()


def test_restart_failure_keeps_durable_marker_and_later_recovery_succeeds(guard_module, tmp_path):
    runtime = FakeRuntime()
    runtime.fail_start = True
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    with pytest.raises(guard_module.GuardError, match='marker retained'):
        guard.run(verify_idle=lambda: None, backup=lambda: None)
    marker = tmp_path / 'restart-required.json'
    assert json.loads(marker.read_text()) == guard_module._MARKER
    assert runtime.state['asb-pilot-api'] is True
    runtime.fail_start = False
    assert guard.recover() is True
    assert all(runtime.state.values()) and not marker.exists()


def test_interrupted_marker_write_leaves_no_recovery_marker_or_service_changes(guard_module, monkeypatch, tmp_path):
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    marker = tmp_path / 'restart-required.json'

    def failed_dump(_value, output, **_kwargs):
        output.write('{"version":')
        output.flush()
        assert not marker.exists()
        raise OSError('synthetic interruption')

    with monkeypatch.context() as patch:
        patch.setattr(guard_module.json, 'dump', failed_dump)
        with pytest.raises(guard_module.GuardError):
            guard.run(verify_idle=lambda: None, backup=lambda: pytest.fail('backup ran'))

    assert all(runtime.state.values()) and not runtime.calls
    assert not marker.exists() and not list(tmp_path.glob('.restart-required-*'))
    assert guard.recover() is False
    assert guard.run(verify_idle=lambda: None, backup=lambda: 'next backup') == 'next backup'


def test_marker_publication_does_not_replace_an_existing_recovery_file(guard_module, tmp_path):
    guard = guard_module.BackupServiceGuard(tmp_path, FakeRuntime())
    marker = tmp_path / 'restart-required.json'
    marker.write_text('previous recovery state')

    with pytest.raises(guard_module.GuardError, match='already exists'):
        guard._write_marker()

    assert marker.read_text() == 'previous recovery state'
    assert not list(tmp_path.glob('.restart-required-*'))


def test_proxy_reload_failure_keeps_recovery_marker(guard_module, tmp_path):
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    def fail_reload():
        raise RuntimeError('synthetic failure')
    runtime.reload_proxy = fail_reload
    with pytest.raises(guard_module.GuardError, match='Proxy reload failed'):
        guard.run(verify_idle=lambda: None, backup=lambda: None)
    assert all(runtime.state.values())
    assert (tmp_path / 'restart-required.json').exists()


def test_running_but_unresponsive_services_keep_recovery_marker(guard_module, tmp_path):
    runtime = FakeRuntime()
    runtime.live = False
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    marker = tmp_path / 'restart-required.json'
    with pytest.raises(guard_module.GuardError, match='Service liveness check failed'):
        guard.run(verify_idle=lambda: None, backup=lambda: None)
    assert all(runtime.state.values()) and marker.exists()
    assert ('reload', 'asb-pilot-nginx') not in runtime.calls

    runtime.live = True
    assert guard.recover() is True
    assert not marker.exists()
    assert guard.recover() is False


@pytest.mark.parametrize('outcome, attempts', [
    ('recovered', 2), ('late_recovery', 4), ('fenced', 1), ('failed', 6),
])
def test_recovery_command_retries_only_while_unfenced(guard_module, monkeypatch, tmp_path, capsys, outcome, attempts):
    runtime = FakeRuntime()
    runtime.live = False
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    guard._write_marker()
    marker = tmp_path / 'restart-required.json'
    fence = tmp_path / 'provider-rotation.json'
    clock = 0
    sleeps = []

    def sleep(seconds):
        nonlocal clock
        assert marker.exists()
        sleeps.append(seconds)
        # A transition can take the shared lock between recovery attempts.
        fd = guard._locked()
        try:
            if outcome == 'fenced':
                fence.write_text('synthetic transition')
            elif outcome == 'recovered' or (outcome == 'late_recovery' and len(sleeps) == 3):
                runtime.live = True
        finally:
            guard_module.os.close(fd)
        clock += seconds

    def docker(*, deadline):
        assert deadline == guard_module.RECOVERY_COMMAND_SECONDS
        return runtime

    monkeypatch.setattr(guard_module, 'DockerRuntime', docker)
    monkeypatch.setattr(guard_module, 'time', SimpleNamespace(monotonic=lambda: clock, sleep=sleep))
    monkeypatch.setattr(guard_module, 'PROVIDER_ROTATION_RECOVERY_MARKER', fence)
    monkeypatch.setattr(guard_module, 'NARRATION_RECOVERY_MARKER', tmp_path / 'absent')
    code = guard_module.main(['--recover', '--state-dir', str(tmp_path)])
    success = outcome in ('recovered', 'late_recovery')
    assert code == (0 if success else 1)
    assert json.loads(capsys.readouterr().out)['status'] == ('RECOVERED' if success else 'RECOVERY_FAILED')
    assert marker.exists() is not success
    assert runtime.calls.count(('probe', 'api-and-worker')) == attempts
    sleep_count = attempts if outcome == 'fenced' else attempts - 1
    assert sleeps == list(guard_module.RECOVERY_RETRY_DELAYS_SECONDS[:sleep_count])


def test_recovery_deadline_limits_subprocess_time(guard_module, monkeypatch):
    clock = 100
    timeouts = []

    def run(_command, **kwargs):
        timeouts.append(kwargs['timeout'])
        return SimpleNamespace(stdout='true')

    monkeypatch.setattr(guard_module, 'time', SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(guard_module.subprocess, 'run', run)
    runtime = guard_module.DockerRuntime(deadline=105)
    assert runtime.running('asb-pilot-worker') is True
    assert timeouts == [5]
    clock = 105
    with pytest.raises(guard_module.GuardError, match='time budget exhausted'):
        runtime.start('asb-pilot-worker')
    assert timeouts == [5]


def test_unexpected_worker_response_does_not_prove_recovery(guard_module, monkeypatch):
    clock = 0

    def sleep(seconds):
        nonlocal clock
        clock += seconds

    def run(command, *, timeout):
        assert 0 < timeout <= (30 if command[1] == 'asb-pilot-worker' else 8)
        if command[0] == 'inspect':
            return 'expected-worker'
        if command[1] == 'asb-pilot-nginx':
            return '{"status":"alive"}'
        return '{"celery@wrong-worker":{"ok":"pong"}}'

    runtime = guard_module.DockerRuntime()
    monkeypatch.setattr(runtime, '_run', run)
    monkeypatch.setattr(guard_module, 'time', SimpleNamespace(monotonic=lambda: clock, sleep=sleep))
    with pytest.raises(guard_module.GuardError, match='expected worker did not respond'):
        runtime.verify_recovery()
    assert clock == 30


@pytest.mark.parametrize('timeout', [0, 301, True])
def test_invalid_container_startup_budget_is_rejected(guard_module, timeout):
    with pytest.raises(ValueError, match='startup budget'):
        guard_module.DockerRuntime(startup_timeout_seconds=timeout)


@pytest.mark.parametrize(('new_worker', 'route_live'), [(True, True), (False, True), (True, False)])
def test_proxy_reload_requires_new_workers_and_a_live_route(guard_module, monkeypatch, new_worker, route_live):
    clock = 0
    calls = []

    def sleep(seconds):
        nonlocal clock
        clock += seconds

    def run(command, *, timeout):
        if command[0] == 'inspect':
            return 'true'
        if command[2] == 'nginx':
            calls.append('reload')
            return ''
        calls.append('pgrep')
        if new_worker and clock >= 0.5:
            return '43'
        return '42\n43' if new_worker and clock > 0 else '42'

    runtime = guard_module.DockerRuntime()
    monkeypatch.setattr(runtime, '_run', run)
    def check_proxy(remaining):
        assert remaining > 0
        calls.append('https')
        return route_live and clock >= 0.75

    monkeypatch.setattr(runtime, '_proxy_is_live', check_proxy)
    monkeypatch.setattr(guard_module, 'time', SimpleNamespace(monotonic=lambda: clock, sleep=sleep))
    if new_worker and route_live:
        runtime.reload_proxy()
        assert calls == ['pgrep', 'reload', 'pgrep', 'pgrep', 'pgrep', 'https', 'https']
    else:
        message = 'did not serve API liveness' if new_worker else 'did not start a new worker'
        with pytest.raises(guard_module.GuardError, match=message):
            runtime.reload_proxy()
        assert ('https' in calls) is new_worker
        assert clock == 10


@pytest.mark.parametrize(('response', 'expected'), [
    (b'{"status":"alive"}\n200', True),
    (b'{"status":"alive"}\n302', False),
    (b'{"status":"alive"}\n503', False),
    (b'{"status":"degraded"}\n200', False),
    (b'not the API\n200', False),
    (None, False),
])
def test_proxy_liveness_probe_verifies_tls_route_and_response(guard_module, monkeypatch, response, expected):
    def run(command, **options):
        identity = guard_module._PILOT_PROXY_TLS_IDENTITY
        assert command[-1] == f'https://{identity}/health/live'
        assert command[command.index('--connect-to') + 1] == f'{identity}:443:127.0.0.1:443'
        assert not {'-k', '--insecure', '-L', '--location'}.intersection(command)
        assert options['timeout'] == 2.0
        if response is None:
            raise guard_module.subprocess.CalledProcessError(60, command)
        return SimpleNamespace(stdout=response)

    monkeypatch.setattr(guard_module.subprocess, 'run', run)
    assert guard_module.DockerRuntime()._proxy_is_live(2.0) is expected


def test_corrupt_marker_and_parallel_run_do_not_start_or_stop_services(guard_module, tmp_path):
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    marker = tmp_path / 'restart-required.json'
    marker.write_text('{bad')
    with pytest.raises(guard_module.GuardError, match='invalid'):
        guard.recover()
    assert runtime.calls == [] and marker.exists()
    marker.unlink()
    fd = open(tmp_path / 'backup.lock', 'w')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(guard_module.GuardError, match='Another backup'):
            guard.run(verify_idle=lambda: None, backup=lambda: None)
    finally:
        fd.close()
    assert runtime.calls == []


@pytest.mark.parametrize('marker_kind', ['regular', 'dangling_symlink'])
def test_narration_marker_blocks_backup_and_automatic_restart(guard_module, tmp_path, monkeypatch, marker_kind):
    marker = tmp_path / 'narration-recovery.json'
    if marker_kind == 'regular':
        marker.write_text('invalid still fences')
    else:
        marker.symlink_to(tmp_path / 'missing')
    monkeypatch.setattr(guard_module, 'NARRATION_RECOVERY_MARKER', marker)
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    with pytest.raises(guard_module.GuardError, match='automatic restart blocked'):
        guard.run(verify_idle=lambda: None, backup=lambda: None)
    assert runtime.calls == []
    (tmp_path / 'restart-required.json').write_text(json.dumps(guard_module._MARKER))
    runtime.state = {'asb-pilot-api': False, 'asb-pilot-worker': False}
    with pytest.raises(guard_module.GuardError, match='automatic restart blocked'):
        guard.recover()
    assert runtime.calls == [] and (tmp_path / 'restart-required.json').exists()


@pytest.mark.parametrize('marker_kind', ['regular', 'dangling_symlink'])
@pytest.mark.parametrize('record_name', ['recovery.json', 'docker-mutation.json'])
def test_provider_rotation_marker_blocks_backup_and_restart(
    guard_module, tmp_path, monkeypatch, marker_kind, record_name,
):
    marker = tmp_path / record_name
    if marker_kind == 'regular':
        marker.write_text('invalid still fences')
    else:
        marker.symlink_to(tmp_path / 'missing')
    monkeypatch.setattr(guard_module, 'NARRATION_RECOVERY_MARKER', tmp_path / 'absent')
    monkeypatch.setattr(guard_module, 'PROVIDER_ROTATION_RECOVERY_MARKER', tmp_path / 'recovery.json')
    runtime = FakeRuntime()
    guard = guard_module.BackupServiceGuard(tmp_path, runtime)
    with pytest.raises(guard_module.GuardError, match='automatic restart blocked'):
        guard.run(verify_idle=lambda: None, backup=lambda: None)
    assert runtime.calls == []
    (tmp_path / 'restart-required.json').write_text(json.dumps(guard_module._MARKER))
    runtime.state = {'asb-pilot-api': False, 'asb-pilot-worker': False}
    with pytest.raises(guard_module.GuardError, match='automatic restart blocked'):
        guard.recover()
    assert runtime.calls == [] and (tmp_path / 'restart-required.json').exists()
