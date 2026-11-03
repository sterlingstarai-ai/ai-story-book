from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def status(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('check_backup_status')


def test_backup_health_requires_fresh_valid_success(status):
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    record = {'version': 1, 'verified_at': now.isoformat(), 'restore_authorized': False}
    def check(value=record, **kw):
        args = {'timer_active': True, 'service_result': 'success', 'free_bytes': status.MIN_FREE_BYTES}
        args.update(kw)
        return status.assess(value, now=now, **args)
    assert check()['status'] == 'OK'
    assert 'backup_stale' in check(dict(record, verified_at=(now - timedelta(hours=49)).isoformat()))['problems']
    assert 'backup_timestamp_future' in check(dict(record, verified_at=(now + timedelta(minutes=6)).isoformat()))['problems']
    assert 'backup_record_invalid_or_missing' in check(dict(record, restore_authorized=True))['problems']
    assert 'backup_record_invalid_or_missing' in check(dict(record, version=True))['problems']
    assert check(None)['status'] == 'ALERT'
    assert check(timer_active=False, service_result='exit-code', free_bytes=1)['problems'] == [
        'timer_inactive', 'last_service_failed', 'disk_headroom_low']


def test_success_record_is_private_and_readable(status, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    runner = importlib.import_module('run_scheduled_backup')
    runner.record_success(tmp_path)
    path = tmp_path / 'last-verified-backup.json'
    assert path.stat().st_mode & 0o077 == 0
    assert status.read_record(path)['restore_authorized'] is False
    path.chmod(0o644)
    assert status.read_record(path) is None
    path.unlink()
    path.symlink_to(tmp_path / 'missing')
    assert status.read_record(path) is None


def test_health_checks_backup_filesystem_as_well_as_state(status, tmp_path, monkeypatch):
    state = tmp_path / 'state'
    output = tmp_path / 'backup-volume' / 'backups'
    state.mkdir()
    output.mkdir(parents=True)

    def fake_usage(path):
        free = status.MIN_FREE_BYTES - 1 if path == output else status.MIN_FREE_BYTES * 2
        return type('Usage', (), {'free': free})()

    monkeypatch.setattr(status.shutil, 'disk_usage', fake_usage)
    assert status.backup_free_bytes(state, output) == status.MIN_FREE_BYTES - 1
    output.rmdir()
    assert status.backup_free_bytes(state, output) == status.MIN_FREE_BYTES * 2
    output.symlink_to(tmp_path / 'missing')
    assert status.backup_free_bytes(state, output) == 0
