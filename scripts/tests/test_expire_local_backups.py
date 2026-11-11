from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from scripts.expire_local_backups import expire


def write_record(path, data):
    path.touch(mode=0o600)
    path.write_text(json.dumps(data))


@pytest.fixture
def backup_environment(tmp_path):
    backup = tmp_path / 'backup'
    state = tmp_path / 'state'
    backup.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    (state / 'backup.lock').touch(mode=0o600)
    now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    write_record(state / 'last-verified-backup.json', {
        'version': 1, 'verified_at': now.isoformat(), 'restore_authorized': False,
    })
    return backup, state, now


def add_backup(backup, now, days):
    folder = backup / f'external-{days:08d}'
    folder.mkdir(mode=0o700)
    stamp = now - timedelta(days=days)
    write_record(folder / 'manifest.json', {
        'format_version': 1, 'created_at': stamp.isoformat(), 'database': {'file': 'database.dump'},
    })
    os.utime(folder, (stamp.timestamp(), stamp.timestamp()))
    return folder


def test_only_expired_finalized_sets_are_removed(backup_environment):
    backup, state, now = backup_environment
    fresh = [add_backup(backup, now, days) for days in (1, 3)]
    expired = add_backup(backup, now, 31)
    other = backup / '.partial-external-00000031'
    other.mkdir(mode=0o700)

    assert expire(backup, state, now=now) == {'retention_days': 30, 'eligible': 1, 'removed': 0}
    assert expired.exists()
    assert expire(backup, state, execute=True, now=now)['removed'] == 1
    assert not expired.exists()
    assert other.exists() and all(folder.exists() for folder in fresh)


def test_retention_halts_when_verified_copy_is_stale_or_recovery_pending(backup_environment):
    backup, state, now = backup_environment
    for days in (1, 2, 31):
        add_backup(backup, now, days)
    with pytest.raises(ValueError, match='recent remotely verified'):
        expire(backup, state, execute=True, now=now + timedelta(days=3))

    (state / 'restart-required.json').touch(mode=0o600)
    with pytest.raises(ValueError, match='recovery is pending'):
        expire(backup, state, execute=True, now=now)
    assert len(list(backup.iterdir())) == 3
