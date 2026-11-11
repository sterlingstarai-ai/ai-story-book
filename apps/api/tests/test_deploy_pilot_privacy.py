"""Recovery after any interrupted two-container swap."""
import importlib.util
import fcntl
import itertools
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("deploy_pilot_privacy", SCRIPTS / "deploy_pilot_privacy.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def recovery_probes(monkeypatch):
    events = []

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def verify_recovery(self):
            events.append('worker-and-api')

        def verify_api_upstream(self):
            events.append('api-upstream')

        def reload_proxy(self):
            events.append('proxy-tls')

    monkeypatch.setattr(m, 'DockerRuntime', Runtime)
    monkeypatch.setattr(m, '_verify_original_ready', lambda deadline: events.append('ready'))
    return events


@pytest.mark.parametrize("stages", itertools.product(range(3), repeat=2))
@pytest.mark.parametrize("staging_running", [False, True])
def test_partial_swap_rollback(tmp_path, monkeypatch, recovery_probes, stages, staging_running):
    monkeypatch.setattr(m, "STATE", tmp_path)
    monkeypatch.setattr(m, "MARKER", tmp_path / "rollback.json")
    monkeypatch.setattr(m, "BACKUP_STATE", tmp_path)
    old = {m.API: "a" * 64, m.WORKER: "b" * 64}
    new = {m.API: "c" * 64, m.WORKER: "d" * 64}
    state = {}
    for name, stage in zip((m.API, m.WORKER), stages):
        state[old[name]] = {"name": name if stage == 0 else m.OLD[name], "running": False}
        state[new[name]] = {"name": name if stage == 2 else m.NEXT[name],
                            "running": staging_running or stage == 2}
    m.MARKER.write_text(json.dumps({"version": 1, "old": old, "new": new}))

    def identify(value):
        return value if value in state else next((key for key, item in state.items() if item["name"] == value), None)

    def inspect(value, fmt):
        if fmt == '{{.Id}}':
            return identify(value)
        item = state[identify(value)]
        return "/" + item["name"] if fmt == "{{.Name}}" else str(item["running"]).lower()

    def docker(*args):
        if args[0] == "stop":
            state[identify(args[-1])]["running"] = False
        elif args[0] == "start":
            state[identify(args[-1])]["running"] = True
        elif args[0] == "rename":
            state[identify(args[1])]["name"] = args[2]
        return ""

    monkeypatch.setattr(m, "exists", lambda value: identify(value) is not None)
    monkeypatch.setattr(m, "inspect", inspect)
    monkeypatch.setattr(m, "docker", docker)
    assert m.rollback()
    assert not m.MARKER.exists()
    assert all(state[old[name]] == {"name": name, "running": True} for name in old)
    assert all(state[new[name]] == {"name": m.NEXT[name], "running": False} for name in new)
    assert recovery_probes == ['api-upstream', 'proxy-tls', 'worker-and-api', 'ready']


@pytest.fixture
def rollback_state(tmp_path, monkeypatch, recovery_probes):
    monkeypatch.setattr(m, 'STATE', tmp_path)
    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    old = {m.API: 'a' * 64, m.WORKER: 'b' * 64}
    new = {m.API: 'c' * 64, m.WORKER: 'd' * 64}
    marker = {'version': 1, 'old': old, 'new': new}
    m.MARKER.write_text(json.dumps(marker))
    state = {old[name]: {'name': m.OLD[name], 'running': False} for name in old}
    state.update({new[name]: {'name': name, 'running': True} for name in new})

    def identify(value):
        return value if value in state else next((key for key, item in state.items() if item['name'] == value), None)

    def inspect(value, fmt):
        identifier = identify(value)
        if fmt == '{{.Id}}':
            return identifier
        item = state[identifier]
        return '/' + item['name'] if fmt == '{{.Name}}' else str(item['running']).lower()

    def docker(*args):
        if args[0] in ('start', 'stop'):
            state[identify(args[-1])]['running'] = args[0] == 'start'
        elif args[0] == 'rename':
            state[identify(args[1])]['name'] = args[2]
        return ''

    monkeypatch.setattr(m, 'exists', lambda value: identify(value) is not None)
    monkeypatch.setattr(m, 'inspect', inspect)
    monkeypatch.setattr(m, 'docker', docker)
    return marker, state, recovery_probes


@pytest.mark.parametrize('failure', ['start', 'identity', 'running', 'api', 'worker', 'proxy', 'ready'])
def test_rollback_retains_marker_until_every_original_probe_passes(monkeypatch, rollback_state, failure):
    marker, _state, events = rollback_state
    real_docker, real_inspect = m.docker, m.inspect

    def docker(*args):
        if failure == 'start' and args[0] == 'start':
            raise RuntimeError('startup failed')
        return real_docker(*args)

    def inspect(value, fmt):
        if value == m.API and fmt == '{{.Id}}' and failure == 'identity':
            return 'e' * 64
        if value == m.API and fmt == '{{.State.Running}}' and failure == 'running':
            return 'false'
        return real_inspect(value, fmt)

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def verify_recovery(self):
            if failure == 'worker':
                raise RuntimeError('worker failed')

        def verify_api_upstream(self):
            if failure == 'api':
                raise RuntimeError('API failed')

        def reload_proxy(self):
            if failure == 'proxy':
                raise RuntimeError('proxy failed')

    def ready(deadline):
        if failure == 'ready':
            raise RuntimeError('readiness failed')

    monkeypatch.setattr(m, 'DockerRuntime', Runtime)
    monkeypatch.setattr(m, 'docker', docker)
    monkeypatch.setattr(m, 'inspect', inspect)
    monkeypatch.setattr(m, '_verify_original_ready', ready)
    with pytest.raises(RuntimeError):
        m.rollback()
    assert json.loads(m.MARKER.read_text()) == marker
    assert events == []


@pytest.mark.parametrize('body,code', [(b'{"status":"healthy"}', b'200'),
                                      (b'{"status":"healthy"}', b'302'),
                                      (b'{"status":"alive"}', b'200'),
                                      (b'[]', b'200'), (b'invalid', b'200')])
def test_original_readiness_requires_local_tls_exact_200_and_healthy(monkeypatch, body, code):
    times = iter([0, 0, 2])
    monkeypatch.setattr(m, 'time', SimpleNamespace(monotonic=lambda: next(times, 2), sleep=lambda seconds: None))
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=body + b'\n' + code)

    monkeypatch.setattr(m.subprocess, 'run', run)
    if code == b'200' and body == b'{"status":"healthy"}':
        m._verify_original_ready(1)
    else:
        with pytest.raises(RuntimeError, match='marker retained'):
            m._verify_original_ready(1)
    argv, options = calls[0]
    assert '--insecure' not in argv and '-k' not in argv
    assert argv[argv.index('--connect-to') + 1] == '35.209.174.246:443:127.0.0.1:443'
    assert argv[-1] == 'https://35.209.174.246/health/ready'
    assert options['check'] is True


def test_worker_failure_restores_proxy_first_and_preserves_rollback_marker(monkeypatch, rollback_state):
    marker, _state, events = rollback_state

    class Runtime:
        def __init__(self, **_kwargs):
            pass

        def verify_api_upstream(self):
            events.append('api-upstream')

        def reload_proxy(self):
            events.append('proxy-tls')

        def verify_recovery(self):
            events.append('worker-failed')
            raise RuntimeError('worker failed')

    monkeypatch.setattr(m, 'DockerRuntime', Runtime)
    with pytest.raises(RuntimeError, match='worker failed'):
        m.rollback()
    assert events == ['api-upstream', 'proxy-tls', 'worker-failed']
    assert json.loads(m.MARKER.read_text()) == marker


def test_recovery_import_does_not_import_scheduled_backup():
    source = f'''import builtins, runpy
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'run_scheduled_backup':
        raise RuntimeError('backup imports forbidden during recovery')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
runpy.run_path({str(SCRIPTS / 'deploy_pilot_privacy.py')!r}, run_name='recovery_import_only')
'''
    subprocess.run([sys.executable, '-c', source], check=True,
                   cwd=SCRIPTS, capture_output=True, timeout=10)


def test_missing_pinned_journal_fails_before_container_mutation(monkeypatch, rollback_state):
    marker, state, _events = rollback_state
    marker['config_journal_sha256'] = 'f' * 64
    m.MARKER.write_text(json.dumps(marker))
    before = {key: dict(value) for key, value in state.items()}
    with pytest.raises(RuntimeError, match='journal is missing'):
        m.rollback()
    assert state == before and m.MARKER.exists()


@pytest.fixture
def journal_env(tmp_path, monkeypatch):
    import deployment_config_journal as journal_module
    import os

    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    paths = (private / 'provider-refresh.env', private / 'pilot.env')
    old = {path: f'OLD_SYNTHETIC={index}\n'.encode() for index, path in enumerate(paths)}
    new = {path: f'NEW_SYNTHETIC={index}\n'.encode() for index, path in enumerate(paths)}
    for path, data in old.items():
        path.write_bytes(data)
        path.chmod(0o600)
    monkeypatch.setattr(journal_module, 'ENV_PATHS', paths)
    monkeypatch.setattr(journal_module, '_ROOT_UID', os.geteuid())
    return m.DeploymentConfigJournal(tmp_path / 'config-journal'), old, new


def test_boot_rollback_restores_partial_config_before_original_verification(
        monkeypatch, rollback_state, journal_env):
    marker, _state, events = rollback_state
    journal, old, new = journal_env
    pin = journal.prepare(new)
    # A crash after the first atomic env write, while the second is still old.
    first = list(new)[0]
    first.write_bytes(new[first])
    marker['config_journal_sha256'] = pin
    m.MARKER.write_text(json.dumps(marker))

    def verify(deadline):
        assert m.MARKER.exists() and journal.path.exists()
        assert all(path.read_bytes() == data for path, data in old.items())
        events.append('verified-with-journal-retained')

    monkeypatch.setattr(m, '_verify_original_ready', verify)
    assert m.rollback()
    assert not m.MARKER.exists() and not journal.directory.exists()
    assert events == ['api-upstream', 'proxy-tls', 'worker-and-api', 'verified-with-journal-retained']


def test_failed_original_probe_preserves_journal_and_allows_retry(monkeypatch, rollback_state, journal_env):
    marker, _state, _events = rollback_state
    journal, old, new = journal_env
    pin = journal.prepare(new)
    journal.apply(new, expected_sha256=pin)
    marker['config_journal_sha256'] = pin
    m.MARKER.write_text(json.dumps(marker))

    def failed(deadline):
        raise RuntimeError('synthetic original startup failure')

    monkeypatch.setattr(m, '_verify_original_ready', failed)
    with pytest.raises(RuntimeError):
        m.rollback()
    assert m.MARKER.exists() and journal.path.exists()
    assert all(path.read_bytes() == data for path, data in old.items())
    monkeypatch.setattr(m, '_verify_original_ready', lambda deadline: None)
    assert m.rollback()
    assert not m.MARKER.exists() and not journal.directory.exists()


def test_boot_without_marker_discards_committed_journal_without_restoring(rollback_state, journal_env):
    _marker, _state, events = rollback_state
    journal, _old, new = journal_env
    pin = journal.prepare(new)
    journal.apply(new, expected_sha256=pin)
    m.MARKER.unlink()
    assert m.rollback() is False
    assert not journal.directory.exists() and events == []
    assert all(path.read_bytes() == data for path, data in new.items())


def test_old_recovery_does_not_restart_while_narration_marker_exists(tmp_path, monkeypatch):
    import backup_service_guard

    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    monkeypatch.setattr(backup_service_guard, 'NARRATION_RECOVERY_MARKER', tmp_path / 'narration-recovery.json')
    m.MARKER.write_text('{}')
    backup_service_guard.NARRATION_RECOVERY_MARKER.write_text('invalid still fences')
    calls = []
    monkeypatch.setattr(m, 'docker', lambda *args: calls.append(args))
    with pytest.raises(backup_service_guard.GuardError, match='automatic restart blocked'):
        m.rollback()
    assert calls == [] and m.MARKER.exists()


def test_old_recovery_does_not_restart_during_provider_rotation(tmp_path, monkeypatch):
    import backup_service_guard

    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    monkeypatch.setattr(backup_service_guard, 'NARRATION_RECOVERY_MARKER', tmp_path / 'absent')
    monkeypatch.setattr(backup_service_guard, 'PROVIDER_ROTATION_RECOVERY_MARKER', tmp_path / 'provider-rotation.json')
    m.MARKER.write_text('{}')
    backup_service_guard.PROVIDER_ROTATION_RECOVERY_MARKER.write_text('invalid still fences')
    calls = []
    monkeypatch.setattr(m, 'docker', lambda *args: calls.append(args))
    with pytest.raises(backup_service_guard.GuardError, match='automatic restart blocked'):
        m.rollback()
    assert calls == [] and m.MARKER.exists()


def test_old_recovery_requires_shared_backup_lock(tmp_path, monkeypatch):
    import backup_service_guard

    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    m.MARKER.write_text('{}')
    with (tmp_path / 'backup.lock').open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(backup_service_guard.GuardError, match='Another backup'):
            m.rollback()
    assert m.MARKER.exists()
