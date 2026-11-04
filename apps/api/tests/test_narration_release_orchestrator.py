"""Failure injection for the unbound, non-production release choreography."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    release = importlib.import_module('narration_release_orchestrator')
    backup = importlib.import_module('backup_service_guard')
    safety = importlib.import_module('narration_deploy_safety')
    monkeypatch.setattr(backup, 'NARRATION_RECOVERY_MARKER', tmp_path / 'narration-recovery.json')
    monkeypatch.setattr(safety, 'BACKUP_STATE', tmp_path)
    monkeypatch.setattr(release, 'PRIVACY_RECOVERY_MARKER', tmp_path / 'privacy-rollback.json')
    return release


SLOTS = ['old_api', 'old_worker', 'new_api', 'new_worker']
IMAGES = {slot: 'sha256:' + 'e' * 64 for slot in SLOTS}
STEPS = ['preflight', 'disable_restart', 'stop_and_drain', 'backup_and_restore_verify',
         'migrate', 'start_isolated', 'verify_isolated', 'publish',
         'verify_published', 'enable_new_restart']


class Runtime:
    def __init__(self, ids):
        names = ['asb-pilot-api-before-narration', 'asb-pilot-worker-before-narration',
                 'asb-pilot-api', 'asb-pilot-worker']
        self.items = {value: {'id': value, 'name': name, 'image_id': 'sha256:' + 'e' * 64,
                              'running': True, 'restart_policy': 'always'}
                      for value, name in zip(ids.values(), names)}
        self.disabled = []

    def inspect(self, identifier):
        return dict(self.items[identifier])

    def disable_restart(self, identifier):
        self.disabled.append(identifier)
        self.items[identifier]['restart_policy'] = 'no'

    def stop(self, identifier):
        self.items[identifier]['running'] = False


class Operations:
    def __init__(self, fail=None, runtime=None):
        self.fail = fail
        self.runtime = runtime
        self.calls = []

    def __getattr__(self, name):
        if name not in STEPS:
            raise AttributeError(name)

        def call(*_args):
            self.calls.append(name)
            if name == self.fail:
                raise KeyboardInterrupt('synthetic process interruption')
            if name == 'stop_and_drain' and self.runtime:
                for slot in ('old_api', 'old_worker'):
                    self.runtime.items[_args[0][slot]]['running'] = False
            if name == 'disable_restart' and self.runtime:
                for item in self.runtime.items.values():
                    item['restart_policy'] = 'no'
            return True
        return call


@pytest.mark.parametrize('failure', STEPS)
def test_failure_never_falls_back_to_old_image(modules, tmp_path, failure):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    ops = Operations(failure, runtime)
    with pytest.raises(KeyboardInterrupt):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                        runtime=runtime, operations=ops)
    assert ops.calls == STEPS[:STEPS.index(failure) + 1]
    if failure in {'preflight', 'disable_restart'}:
        assert not (tmp_path / 'narration-recovery.json').exists()
        assert runtime.disabled == []
    else:
        assert (tmp_path / 'narration-recovery.json').exists()
        assert set(runtime.disabled) == set(ids.values())
        assert all(not item['running'] for item in runtime.items.values())


def test_success_removes_marker_only_after_all_checks(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    ops = Operations(runtime=runtime)
    result = modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                             runtime=runtime, operations=ops)
    assert result == {'status': 'RELEASE_SEQUENCE_COMPLETED', 'restore_authorized': False}
    assert ops.calls == STEPS
    assert not (tmp_path / 'narration-recovery.json').exists()


def test_restart_is_enabled_only_after_published_checks_and_marker_removal(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))

    class MarkerCheckingOperations(Operations):
        def stop_and_drain(self, identities):
            assert (tmp_path / 'narration-recovery.json').is_file()
            assert all(item['restart_policy'] == 'no' for item in self.runtime.items.values())
            return super().__getattr__('stop_and_drain')(identities)

        def publish(self):
            assert (tmp_path / 'narration-recovery.json').is_file()
            self.calls.append('publish')
            return True

        def verify_published(self):
            assert (tmp_path / 'narration-recovery.json').is_file()
            self.calls.append('verify_published')
            return True

        def enable_new_restart(self, _ids):
            assert not (tmp_path / 'narration-recovery.json').exists()
            self.calls.append('enable_new_restart')
            return True

    runtime = Runtime(ids)
    ops = MarkerCheckingOperations(runtime=runtime)
    modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                    runtime=runtime, operations=ops)
    assert ops.calls == STEPS


@pytest.mark.parametrize('failure_call', [2, 3])
def test_directory_fsync_failure_retains_marker_and_quarantines(modules, tmp_path, monkeypatch, failure_call):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    real_fsync = modules.os.fsync
    calls = 0

    def fail_once(fd):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError('synthetic directory fsync failure')
        return real_fsync(fd)

    monkeypatch.setattr(modules.os, 'fsync', fail_once)
    with pytest.raises(OSError):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                        runtime=runtime, operations=Operations(runtime=runtime))
    assert (tmp_path / 'narration-recovery.json').exists()
    assert set(runtime.disabled) == set(ids.values())
    assert all(not item['running'] for item in runtime.items.values())


def test_adapter_cannot_self_attest_disabled_restart(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    ops = Operations(runtime=runtime)
    ops.disable_restart = lambda _ids: ops.calls.append('disable_restart') or True
    with pytest.raises(modules.NarrationReleaseError, match='Restart policy is unsafe'):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                        runtime=runtime, operations=ops)
    assert ops.calls == STEPS[:STEPS.index('disable_restart') + 1]
    assert not (tmp_path / 'narration-recovery.json').exists()
    assert all(item['running'] for item in runtime.items.values())


def test_adapter_cannot_self_attest_old_containers_stopped(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    ops = Operations(runtime=runtime)
    ops.stop_and_drain = lambda _ids: ops.calls.append('stop_and_drain') or True
    with pytest.raises(modules.NarrationReleaseError, match='still running or unverified'):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids,
                        image_ids=IMAGES, runtime=runtime, operations=ops)
    assert ops.calls == STEPS[:STEPS.index('stop_and_drain') + 1]
    assert (tmp_path / 'narration-recovery.json').is_file()
    assert all(not item['running'] for item in runtime.items.values())


def test_restart_reenabled_before_publish_verification_is_quarantined(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)

    class UnsafeOperations(Operations):
        def verify_published(self):
            self.calls.append('verify_published')
            runtime.items[ids['new_api']]['restart_policy'] = 'always'
            return True

    ops = UnsafeOperations(runtime=runtime)
    with pytest.raises(modules.NarrationReleaseError, match='Restart policy is unsafe'):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                        runtime=runtime, operations=ops)
    assert 'enable_new_restart' not in ops.calls
    assert (tmp_path / 'narration-recovery.json').is_file()
    assert all(not item['running'] for item in runtime.items.values())


def test_production_marker_is_blocked_before_any_runtime_mutation(modules, tmp_path, monkeypatch):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    ops = Operations(runtime=runtime)
    monkeypatch.setattr(modules, 'PRODUCTION_MARKER', tmp_path / 'narration-recovery.json')
    with pytest.raises(modules.NarrationReleaseError, match='Production narration release is blocked'):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                        runtime=runtime, operations=ops)
    assert ops.calls == []
    assert runtime.disabled == []
    assert not (tmp_path / 'narration-recovery.json').exists()


@pytest.mark.parametrize('failure, changed_names, rollback', [
    ('backup_and_restore_verify', False, True), ('publish', False, True), ('publish', True, False),
])
def test_storage_detach_recovers_original_only_before_publication(
        modules, tmp_path, monkeypatch, failure, changed_names, rollback):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    ops = Operations(failure, runtime)
    ops._publication_started = changed_names
    called = []
    ops.resume_original_storage_before_publication = lambda: not called.append(True)
    monkeypatch.setattr(modules, 'PRODUCTION_MARKER', tmp_path / 'narration-recovery.json')
    monkeypatch.setattr(modules, '_require_production_detach', lambda *_: None)
    with pytest.raises(KeyboardInterrupt):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids, image_ids=IMAGES,
                        runtime=runtime, operations=ops)
    assert bool(called) is rollback
    assert (tmp_path / 'narration-recovery.json').exists() is not rollback


def test_unexpected_image_is_rejected_before_marker_or_callbacks(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)
    runtime.items[ids['old_api']]['image_id'] = 'sha256:' + 'f' * 64
    ops = Operations(runtime=runtime)
    with pytest.raises(RuntimeError, match='differs from the reviewed image'):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids,
                        image_ids=IMAGES, runtime=runtime, operations=ops)
    assert ops.calls == []
    assert runtime.disabled == []
    assert not (tmp_path / 'narration-recovery.json').exists()


def test_unverified_queue_drain_preserves_worker_and_marker(modules, tmp_path):
    ids = dict(zip(SLOTS, [x * 64 for x in 'abcd']))
    runtime = Runtime(ids)

    class PendingQueue(Operations):
        def stop_and_drain(self, identities):
            self.runtime.stop(identities['old_api'])
            raise modules.WorkerDrainUnverified('accepted work remains')

    with pytest.raises(modules.WorkerDrainUnverified):
        modules.release(state_dir=tmp_path, backup_state_dir=tmp_path, identities=ids,
                        image_ids=IMAGES, runtime=runtime, operations=PendingQueue(runtime=runtime))

    assert (tmp_path / 'narration-recovery.json').is_file()
    assert not runtime.items[ids['old_api']]['running']
    assert runtime.items[ids['old_worker']]['running']
    assert runtime.items[ids['old_worker']]['restart_policy'] == 'no'
