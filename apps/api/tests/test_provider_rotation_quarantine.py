"""Provider rotation quarantine is fail-closed and never starts a container."""
import fcntl
import importlib
import configparser
from pathlib import Path

import pytest


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('provider_rotation_quarantine')
    backup = importlib.import_module('backup_service_guard')
    narration = importlib.import_module('narration_deploy_safety')
    monkeypatch.setattr(backup, 'PROVIDER_ROTATION_RECOVERY_MARKER', tmp_path / 'recovery.json')
    monkeypatch.setattr(backup, 'NARRATION_RECOVERY_MARKER', tmp_path / 'narration.json')
    monkeypatch.setattr(narration, 'PRIVACY_RECOVERY_MARKER', tmp_path / 'privacy.json')
    monkeypatch.setattr(narration, 'BACKUP_STATE', tmp_path)
    identities = dict(zip(('old_api', 'old_worker', 'new_api', 'new_worker'), (c * 64 for c in 'abcd')))
    images = {'old_api': 'sha256:' + '1' * 64, 'new_api': 'sha256:' + '1' * 64,
              'old_worker': 'sha256:' + '2' * 64, 'new_worker': 'sha256:' + '2' * 64}
    names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
             'new_api': 'asb-provider-next-api', 'new_worker': 'asb-provider-next-worker'}

    class Runtime:
        def __init__(self):
            self.items = {identities[slot]: {'id': identities[slot], 'name': name, 'image_id': images[slot],
                          'running': slot.startswith('old_'), 'restart_policy': 'no'} for slot, name in names.items()}
            self.calls = []

        def inspect(self, identifier):
            return dict(self.items[identifier])

        def disable_restart(self, identifier):
            self.calls.append(('disable', identifier))
            self.items[identifier]['restart_policy'] = 'no'

        def stop(self, identifier):
            self.calls.append(('stop', identifier))
            self.items[identifier]['running'] = False

    return module, backup, tmp_path, identities, images, Runtime()


def _arm(context):
    module, _, path, identities, images, runtime = context
    return module.arm(state_dir=path, backup_state_dir=path, identities=identities,
                      image_ids=images, runtime=runtime)


def test_quarantine_retains_durable_marker_and_never_starts(setup):
    module, _, path, _, _, runtime = setup
    assert _arm(setup)['production_authorized'] is False
    assert module.quarantine(state_dir=path, runtime=runtime)['status'] == 'ROTATION_QUARANTINED'
    assert (path / 'recovery.json').is_file()
    assert all(not item['running'] and item['restart_policy'] == 'no' for item in runtime.items.values())
    assert all(action in {'disable', 'stop'} for action, _ in runtime.calls)


@pytest.mark.parametrize('failure', ['wrong_image', 'restart_enabled', 'prior_backup', 'backup_lock'])
def test_arm_rejects_unsafe_state_before_marker_or_mutation(setup, failure):
    module, _, path, identities, images, runtime = setup
    lock = None
    if failure == 'wrong_image':
        runtime.items[identities['new_api']]['image_id'] = 'sha256:' + '3' * 64
    elif failure == 'restart_enabled':
        runtime.items[identities['old_api']]['restart_policy'] = 'unless-stopped'
    elif failure == 'prior_backup':
        (path / 'restart-required.json').write_text('{}')
    else:
        lock = (path / 'backup.lock').open('w')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(Exception):
            _arm(setup)
        assert not (path / 'recovery.json').exists()
        assert runtime.calls == []
    finally:
        if lock is not None:
            lock.close()


def test_key_only_rejects_different_candidate_image(setup):
    _, _, path, identities, images, runtime = setup
    images['new_api'] = 'sha256:' + '3' * 64
    with pytest.raises(Exception):
        _arm(setup)
    assert not (path / 'recovery.json').exists() and runtime.calls == []


def test_quarantine_does_not_touch_wrong_container_and_keeps_marker(setup):
    module, _, path, identities, _, runtime = setup
    _arm(setup)
    runtime.items[identities['new_api']]['name'] = 'unrelated-container'
    with pytest.raises(module.RotationGuardError, match='incomplete'):
        module.quarantine(state_dir=path, runtime=runtime)
    assert (path / 'recovery.json').exists()
    assert all(identifier != identities['new_api'] for _, identifier in runtime.calls)
    assert not runtime.items[identities['old_api']]['running']


def test_production_arm_is_unconditionally_blocked(setup, monkeypatch):
    module, _, path, _, _, runtime = setup
    monkeypatch.setattr(module, '_PRODUCTION_MARKER', path / 'recovery.json')
    with pytest.raises(module.RotationGuardError, match='Production rotation remains blocked'):
        _arm(setup)
    assert not (path / 'recovery.json').exists() and runtime.calls == []


def test_uninstalled_unit_orders_quarantine_before_legacy_recovery():
    root = Path(__file__).resolve().parents[3]
    unit = configparser.ConfigParser(interpolation=None)
    assert unit.read(root / 'infra/gcp-pilot/asb-provider-rotation-quarantine.service')
    assert 'docker.service' in unit['Unit']['After'].split()
    assert {'asb-backup-recover.service', 'asb-privacy-deploy-recover.service'}.issubset(
        unit['Unit']['Before'].split())
    assert unit['Service']['ExecStart'].endswith('scripts/provider_rotation_quarantine.py --recover')
