"""Test interrupted deployment quarantine without live user containers."""
import importlib
import fcntl
import configparser
from pathlib import Path

import pytest


@pytest.fixture
def safety(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_deploy_safety')
    backup = importlib.import_module('backup_service_guard')
    monkeypatch.setattr(module, 'BACKUP_STATE', tmp_path)
    monkeypatch.setattr(backup, 'NARRATION_RECOVERY_MARKER', tmp_path / 'narration-recovery.json')
    return module


class Runtime:
    def __init__(self, ids):
        names = ['asb-pilot-api-before-narration', 'asb-pilot-worker-before-narration',
                 'asb-pilot-api', 'asb-pilot-worker']
        self.items = {identifier: {'id': identifier, 'name': name, 'running': True, 'restart_policy': 'always'}
                      for identifier, name in zip(ids.values(), names)}
        self.disabled = []
        self.stopped = []
        self.fail_disable = None

    def inspect(self, identifier):
        return dict(self.items[identifier])

    def disable_restart(self, identifier):
        self.disabled.append(identifier)
        if identifier == self.fail_disable:
            raise RuntimeError('synthetic failure')
        self.items[identifier]['restart_policy'] = 'no'

    def stop(self, identifier):
        self.stopped.append(identifier)
        self.items[identifier]['running'] = False


def ids():
    return dict(zip(['old_api', 'old_worker', 'new_api', 'new_worker'],
                    [x * 64 for x in 'abcd']))


def test_recovery_stops_recorded_containers_never_starts_old(safety, tmp_path):
    identities = ids()
    safety.arm(tmp_path, identities, backup_state_dir=tmp_path)
    runtime = Runtime(identities)
    assert safety.quarantine(tmp_path, runtime) == {'status': 'QUARANTINED', 'restore_authorized': False}
    assert set(runtime.disabled) == set(identities.values())
    assert set(runtime.stopped) == set(identities.values())
    assert (tmp_path / 'narration-recovery.json').exists()
    assert safety.quarantine(tmp_path, runtime)['status'] == 'QUARANTINED'


def test_unexpected_identity_is_untouched_while_other_containers_stop(safety, tmp_path):
    identities = ids()
    safety.arm(tmp_path, identities, backup_state_dir=tmp_path)
    runtime = Runtime(identities)
    runtime.items[identities['new_api']]['name'] = 'someone-elses-app'
    with pytest.raises(safety.NarrationSafetyError):
        safety.quarantine(tmp_path, runtime)
    assert identities['new_api'] not in runtime.disabled
    assert identities['new_api'] not in runtime.stopped
    assert set(runtime.stopped) == set(identities.values()) - {identities['new_api']}
    assert (tmp_path / 'narration-recovery.json').exists()


@pytest.mark.parametrize('foreign', [False, True])
def test_recovery_checks_and_stops_recorded_proxy_first(safety, tmp_path, foreign):
    identities = ids()
    proxy = {'id': 'f' * 64, 'image_id': 'sha256:' + '1' * 64}
    safety._write_marker(tmp_path, identities, proxy=proxy)
    runtime = Runtime(identities)
    runtime.items[proxy['id']] = {**proxy, 'name': 'asb-pilot-nginx', 'running': True,
                                  'restart_policy': 'unless-stopped'}
    if foreign:
        runtime.items[proxy['id']]['image_id'] = 'sha256:' + '2' * 64
        with pytest.raises(safety.NarrationSafetyError, match='incomplete'):
            safety.quarantine(tmp_path, runtime)
        assert proxy['id'] not in runtime.stopped
    else:
        assert safety.quarantine(tmp_path, runtime)['status'] == 'QUARANTINED'
        assert runtime.stopped[0] == proxy['id']
    assert set(identities.values()) <= set(runtime.stopped)


def test_partial_restart_policy_failure_stops_others_and_retains_marker(safety, tmp_path):
    identities = ids()
    safety.arm(tmp_path, identities, backup_state_dir=tmp_path)
    runtime = Runtime(identities)
    runtime.fail_disable = identities['old_api']
    with pytest.raises(safety.NarrationSafetyError, match='Quarantine incomplete'):
        safety.quarantine(tmp_path, runtime)
    assert set(runtime.stopped) == set(identities.values())
    assert (tmp_path / 'narration-recovery.json').exists()


def test_silent_restart_policy_failure_is_detected(safety, tmp_path):
    identities = ids()
    safety.arm(tmp_path, identities, backup_state_dir=tmp_path)
    runtime = Runtime(identities)
    runtime.disable_restart = lambda identifier: None
    with pytest.raises(safety.NarrationSafetyError, match='Quarantine incomplete'):
        safety.quarantine(tmp_path, runtime)
    assert set(runtime.stopped) == set(identities.values())
    assert (tmp_path / 'narration-recovery.json').exists()


def test_marker_rejects_duplicate_or_overwrite(safety, tmp_path):
    identities = ids()
    identities['new_api'] = identities['old_api']
    with pytest.raises(safety.NarrationSafetyError):
        safety.arm(tmp_path, identities, backup_state_dir=tmp_path)
    safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)
    with pytest.raises(safety.NarrationSafetyError):
        safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)


def test_arm_rejects_concurrent_backup_or_pending_restart(safety, tmp_path, monkeypatch):
    with (tmp_path / 'backup.lock').open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(safety.NarrationSafetyError, match='Backup or recovery'):
            safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)
    (tmp_path / 'restart-required.json').write_text('{}')
    with pytest.raises(safety.NarrationSafetyError, match='Prior backup'):
        safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)
    assert not (tmp_path / 'narration-recovery.json').exists()
    (tmp_path / 'restart-required.json').unlink()
    privacy = tmp_path / 'privacy-rollback.json'
    monkeypatch.setattr(safety, 'PRIVACY_RECOVERY_MARKER', privacy)
    privacy.write_text('{}')
    with pytest.raises(safety.NarrationSafetyError, match='privacy recovery'):
        safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)


@pytest.mark.parametrize('kind', ['regular', 'dangling_symlink'])
def test_arm_rejects_pending_provider_rotation(safety, tmp_path, monkeypatch, kind):
    import backup_service_guard
    marker = tmp_path / 'provider-recovery.json'
    if kind == 'regular':
        marker.write_text('invalid still fences')
    else:
        marker.symlink_to(tmp_path / 'missing')
    monkeypatch.setattr(backup_service_guard, 'PROVIDER_ROTATION_RECOVERY_MARKER', marker)
    monkeypatch.setattr(safety, 'PRIVACY_RECOVERY_MARKER', tmp_path / 'absent')
    with pytest.raises(safety.NarrationSafetyError, match='recovery is pending'):
        safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)
    assert not (tmp_path / 'narration-recovery.json').exists()


def test_arm_rejects_private_lock_or_unobserved_marker(safety, tmp_path, monkeypatch):
    import backup_service_guard

    other = tmp_path / 'other'
    other.mkdir(mode=0o700)
    with pytest.raises(safety.NarrationSafetyError, match='paths do not match'):
        safety.arm(tmp_path, ids(), backup_state_dir=other)
    monkeypatch.setattr(backup_service_guard, 'NARRATION_RECOVERY_MARKER', other / 'narration-recovery.json')
    with pytest.raises(safety.NarrationSafetyError, match='paths do not match'):
        safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)


def test_boot_recovery_no_marker_is_inert_but_symlink_fails(safety, tmp_path):
    runtime = Runtime(ids())
    assert safety.recover_if_armed(tmp_path, runtime)['status'] == 'NO_RECOVERY_NEEDED'
    assert runtime.stopped == []
    (tmp_path / 'narration-recovery.json').symlink_to(tmp_path / 'missing')
    with pytest.raises(safety.NarrationSafetyError):
        safety.recover_if_armed(tmp_path, runtime)
    assert runtime.stopped == []


def test_boot_unit_orders_before_existing_recoveries():
    unit = Path(__file__).resolve().parents[3] / 'infra/gcp-pilot/asb-narration-quarantine.service'
    parser = configparser.ConfigParser(interpolation=None)
    assert parser.read(unit)
    assert 'docker.service' in parser['Unit']['After'].split()
    assert {'asb-backup-recover.service', 'asb-privacy-deploy-recover.service'} <= set(parser['Unit']['Before'].split())
    assert '--recover --state-dir /var/lib/ai-story-book/narration-deploy' in parser['Service']['ExecStart']


def test_boot_recovery_waits_for_deployment_lock(safety, tmp_path):
    import os
    from backup_service_guard import BackupServiceGuard

    runtime = Runtime(ids())
    safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)
    fd = BackupServiceGuard(tmp_path, runtime)._locked()
    try:
        with pytest.raises(safety.NarrationSafetyError, match='owns the recovery lock'):
            safety.recover_if_armed(tmp_path, runtime)
        assert runtime.stopped == []
    finally:
        os.close(fd)
    assert safety.recover_if_armed(tmp_path, runtime)['status'] == 'QUARANTINED'


def test_marker_is_not_visible_if_write_fails_before_publication(safety, tmp_path, monkeypatch):
    def fail_fsync(_fd):
        raise OSError('fixture disk failure')

    monkeypatch.setattr(safety.os, 'fsync', fail_fsync)
    with pytest.raises(safety.NarrationSafetyError):
        safety.arm(tmp_path, ids(), backup_state_dir=tmp_path)
    assert not (tmp_path / 'narration-recovery.json').exists()
    assert {entry.name for entry in tmp_path.iterdir()} == {'backup.lock'}


@pytest.mark.parametrize('stages', [('media', 'media'), ('narration', 'narration'), ('media', 'narration')])
def test_boot_resumes_only_published_generation(safety, tmp_path, stages):
    identities = ids()
    images = {slot: 'sha256:' + 'a' * 64 for slot in identities}
    proxy = {'id': 'f' * 64, 'image_id': 'sha256:' + 'f' * 64}
    runtime = Runtime(identities)
    for slot, identifier in identities.items():
        runtime.items[identifier].update(running=False, restart_policy='no', image_id=images[slot])
    for role, stage in zip(('api', 'worker'), stages):
        slot = 'old_' + role
        runtime.items[identities[slot]]['name'] = safety._RETIRED_NAMES[stage][slot]
    runtime.items[proxy['id']] = {**proxy, 'name': 'asb-pilot-nginx', 'running': False, 'restart_policy': 'no'}
    started = []

    def run(command, *args):
        if command == 'start':
            started.append(args[0])
            runtime.items[args[0]]['running'] = True
        if command == 'inspect':
            return 'worker-host'
        if 'celery' in args:
            return '{"celery@worker-host":{"ok":"pong"}}'
        return ''

    runtime._run = run
    runtime.enable_restart = lambda identifier: runtime.items[identifier].update(restart_policy='unless-stopped')
    safety._write_marker(tmp_path, identities, proxy=proxy)
    safety._write_marker(tmp_path, identities, proxy=proxy, published_images=images)
    if stages[0] != stages[1]:
        # Docker may have already restarted the proxy before the recovery unit.
        runtime.items[proxy['id']].update(running=True, restart_policy='unless-stopped')
        with pytest.raises(safety.NarrationSafetyError, match='did not complete'):
            safety.recover_if_armed(tmp_path, runtime)
        assert not started
        assert runtime.stopped == [proxy['id']]
        assert runtime.items[proxy['id']]['restart_policy'] == 'no'
        assert (tmp_path / 'narration-recovery.json').is_file()
        return
    assert safety.recover_if_armed(tmp_path, runtime)['status'] == 'PUBLISHED_RELEASE_RECOVERED'
    assert started == [identities['new_api'], identities['new_worker'], proxy['id']]
    assert not (tmp_path / 'narration-recovery.json').exists()
