"""Offline update orchestration checks; these never touch systemd or a VM."""
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def updater(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    mod = importlib.import_module('update_privacy_purge_monitor')
    root = tmp_path / 'monitor'
    units = tmp_path / 'units'
    root.mkdir(mode=0o700)
    units.mkdir()
    (root / 'release').mkdir()
    (root / 'current').symlink_to('release')
    source = tmp_path / 'candidate'
    source.mkdir()
    files = {}
    for name in mod.UNITS:
        path = units / name
        path.write_bytes(name.encode())
        files[f'infra/gcp-pilot/{name}'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / 'installation.json').write_text(json.dumps({'version': 1, 'units': {
        name: files[f'infra/gcp-pilot/{name}'] for name in mod.UNITS}}))
    # Production ownership and manifest checks have separate tests; here the
    # filesystem is synthetic and only update/rollback sequencing is exercised.
    orig_lstat = Path.lstat
    def root_lstat(path, *args, **kwargs):
        value = orig_lstat(path, *args, **kwargs)
        if path == root:
            return SimpleNamespace(st_mode=value.st_mode, st_uid=0)
        return value
    orig_fstat = os.fstat
    def root_fstat(fd):
        value = orig_fstat(fd)
        return SimpleNamespace(st_mode=value.st_mode, st_uid=0)
    monkeypatch.setattr(Path, 'lstat', root_lstat)
    monkeypatch.setattr(mod.os, 'fstat', root_fstat)
    monkeypatch.setattr(mod, 'ROOT', root)
    monkeypatch.setattr(mod, 'UNIT_DIR', units)
    fake_python = tmp_path / 'synthetic-python'
    fake_python.write_text('#!/bin/sh\nexit 0\n')
    fake_python.chmod(0o700)
    monkeypatch.setattr(mod, 'PYTHON', fake_python)
    monkeypatch.setattr(mod, 'require_root', lambda: None)
    monkeypatch.setattr(mod, 'require_pilot_vm', lambda: None)
    monkeypatch.setattr(mod, 'checked_file', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'bundle_check', lambda *args: files)
    monkeypatch.setattr(mod, '_validate_installed_release', lambda *args: files)
    monkeypatch.setattr(mod, 'config_paths', lambda: {
        'ASB_PURGE_MONITOR_ENV_FILE': Path('/synthetic/env'),
        'ASB_PURGE_MONITOR_CA_FILE': Path('/synthetic/ca')})
    monkeypatch.setattr(mod, '_active_state', lambda unit: 'active' if unit.endswith('.timer') else 'inactive')
    args = SimpleNamespace(bundle=source, manifest_sha256='b' * 64, expected_current_sha256='a' * 64,
                           reuse_existing_target=None)
    return mod, root, args


def test_atomic_switch_and_restore_on_service_failure(updater, monkeypatch):
    mod, root, args = updater
    calls = []
    def fake_run(*command):
        calls.append(command)
        if command == ('systemctl', 'start', mod.UNITS[0]) and len([
                c for c in calls if c == command]) == 1:
            raise RuntimeError('synthetic service failure')
    monkeypatch.setattr(mod, 'run', fake_run)
    with pytest.raises(RuntimeError):
        mod.update(args)
    assert os.readlink(root / 'current') == 'release'
    assert ('systemctl', 'start', mod.UNITS[1]) in calls
    assert (root / ('release-' + 'b' * 64)).exists()


def test_success_preserves_original_release_and_restarts_timer(updater, monkeypatch):
    mod, root, args = updater
    calls = []
    monkeypatch.setattr(mod, 'run', lambda *command: calls.append(command))
    assert mod.update(args) == 'MONITOR_BUNDLE_SWITCHED'
    assert os.readlink(root / 'current') == 'release-' + 'b' * 64
    assert (root / 'release').is_dir()
    assert ('systemctl', 'stop', mod.UNITS[1]) in calls
    assert ('systemctl', 'start', mod.UNITS[1]) in calls
