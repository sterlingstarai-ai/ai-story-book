"""Failure-injection tests for the not-yet-deployed backup service guard."""

import fcntl
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def guard_module():
    path = Path(__file__).resolve().parents[3] / 'scripts' / 'backup_service_guard.py'
    spec = importlib.util.spec_from_file_location('asb_backup_service_guard_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRuntime:
    def __init__(self):
        self.state = {'asb-pilot-api': True, 'asb-pilot-worker': True}
        self.calls = []
        self.fail_start = False

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
def test_provider_rotation_marker_blocks_backup_and_restart(guard_module, tmp_path, monkeypatch, marker_kind):
    marker = tmp_path / 'provider-rotation.json'
    if marker_kind == 'regular':
        marker.write_text('invalid still fences')
    else:
        marker.symlink_to(tmp_path / 'missing')
    monkeypatch.setattr(guard_module, 'NARRATION_RECOVERY_MARKER', tmp_path / 'absent')
    monkeypatch.setattr(guard_module, 'PROVIDER_ROTATION_RECOVERY_MARKER', marker)
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
