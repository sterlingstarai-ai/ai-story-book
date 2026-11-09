from datetime import datetime, timedelta, timezone
import importlib
import json
import os
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
        args = {'timer_active': True, 'timer_enabled': True,
                'service_result': 'success', 'free_bytes': status.MIN_FREE_BYTES}
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


def test_backup_record_reader_does_not_wait_on_a_pipe(status, tmp_path):
    path = tmp_path / 'last-scheduled-failure.json'
    os.mkfifo(path, 0o600)
    assert status.read_record(path) is None


def test_recorded_failure_survives_reboot_until_a_new_verified_backup(status, tmp_path, monkeypatch, capsys):
    runner = importlib.import_module('run_scheduled_backup')
    monkeypatch.setattr(status, 'STATE', tmp_path)
    monkeypatch.setattr(status, 'backup_free_bytes', lambda *_: status.MIN_FREE_BYTES)
    monkeypatch.setattr(status, 'provider_recovery_pending', lambda: False)
    service_result = 'success'
    monkeypatch.setattr(status, 'systemctl', lambda _, unit, *__: (
        'ActiveState=active\nUnitFileState=enabled' if unit == status.BACKUP_TIMER else f'Result={service_result}'
    ))
    runner.record_success(tmp_path)
    runner.record_failure(tmp_path, 'journal_preflight')
    failure = tmp_path / 'last-scheduled-failure.json'
    assert failure.stat().st_mode & 0o077 == 0
    assert set(status.read_record(failure)) == {'version', 'failed_at', 'stage', 'restore_authorized'}
    assert status.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['problems'] == ['last_service_failed']
    assert result['failure_reason_code'] == 6
    assert result['restore_authorized'] is False
    service_result = 'timeout'
    monkeypatch.setattr(status, '_read_command', lambda *_: '')
    assert status.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['failure_reason_code'] == 16 and 'failure_stage' not in result
    service_result = 'success'
    runner.record_success(tmp_path)
    assert status.main() == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'OK'


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


@pytest.mark.parametrize(('unit_file_state', 'expected_problem'), [
    ('enabled', None),
    ('enabled-runtime', 'timer_not_enabled'),
    ('disabled', 'timer_not_enabled'),
    ('', 'timer_not_enabled'),
])
def test_active_backup_timer_must_also_start_at_boot(
    status, monkeypatch, capsys, unit_file_state, expected_problem,
):
    def systemctl(command, unit, *_):
        if unit == 'asb-backup.timer':
            return f'ActiveState=active\nUnitFileState={unit_file_state}' if command == 'show' else 'active'
        return 'Result=success'

    monkeypatch.setattr(status, 'systemctl', systemctl)
    monkeypatch.setattr(status, 'backup_free_bytes', lambda *_: status.MIN_FREE_BYTES)
    monkeypatch.setattr(status, 'provider_recovery_pending', lambda: False)
    monkeypatch.setattr(status, '_recovery_marker_pending', lambda _: False)
    monkeypatch.setattr(status, 'read_record', lambda _: {
        'version': 1, 'verified_at': datetime.now(timezone.utc).isoformat(), 'restore_authorized': False,
    })

    assert status.main() == int(expected_problem is not None)
    result = json.loads(capsys.readouterr().out)
    assert result['problems'] == ([expected_problem] if expected_problem else [])
    assert result.get('failure_reason_code') == (10 if expected_problem else None)


def test_health_stays_unhealthy_until_interrupted_backup_recovers(status, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status, 'STATE', tmp_path)
    monkeypatch.setattr(status, 'backup_free_bytes', lambda *_: status.MIN_FREE_BYTES)
    monkeypatch.setattr(status, 'provider_recovery_pending', lambda: False)
    monkeypatch.setattr(status, 'systemctl', lambda _, unit, *__: (
        'ActiveState=active\nUnitFileState=enabled' if unit == status.BACKUP_TIMER else 'Result=success'
    ))
    record = tmp_path / 'last-verified-backup.json'
    record.write_text(json.dumps({
        'version': 1, 'verified_at': datetime.now(timezone.utc).isoformat(), 'restore_authorized': False,
    }))
    record.chmod(0o600)
    marker = tmp_path / 'restart-required.json'
    marker.write_text('partial marker after a simulated interruption')
    assert status.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['problems'] == ['backup_recovery_pending']
    assert result['restore_authorized'] is False

    marker.unlink()
    marker.symlink_to(tmp_path / 'missing')
    assert status.main() == 1
    assert json.loads(capsys.readouterr().out)['problems'] == ['backup_recovery_pending']

    marker.unlink()
    assert status.main() == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'OK'


@pytest.mark.parametrize(('stage', 'code'), [
    ('destination_preflight', 20), ('local_destination_preflight', 21), (None, 15),
])
def test_health_reports_only_a_failure_from_the_last_backup_process(status, monkeypatch, capsys, stage, code):
    fields = ('Result=exit-code\nExecMainPID=42\nExecMainStartTimestampMonotonic=9000000\n'
              'ExecMainExitTimestampMonotonic=10000000')

    def entry(stage, *, timestamp=10_000_100, pid='42', unit='asb-backup.service', authorized=False,
              diagnostic=None):
        return json.dumps({'_PID': pid, '_SYSTEMD_UNIT': unit, '__MONOTONIC_TIMESTAMP': str(timestamp),
                           'MESSAGE': json.dumps({'status': 'FAILED', 'restore_authorized': authorized,
                                                  **({'stage': stage} if stage else {}),
                                                  **(diagnostic or {}), 'details': 'private diagnostic data'})})

    legacy = {'error_type': 'JournalError', 'error_location': 'privacy_journal.py:42'}
    journal = '\n'.join((entry('configuration', timestamp=8_999_999), entry('guarded_backup', pid='41'),
                         entry('backup_source', unit='other.service'), entry('initialization', authorized=True),
                         entry('unknown'), entry('guarded_backup', timestamp=15_000_001),
                         'malformed entry', entry(stage, diagnostic=legacy),
                         entry(None, timestamp=10_000_101,
                               diagnostic=legacy | {'error_location': '/private/secret.py:22'}),
                         entry(None, timestamp=10_000_102,
                               diagnostic=legacy | {'error_type': 'InjectedError'})))
    monkeypatch.setattr(status, 'backup_free_bytes', lambda *_: status.MIN_FREE_BYTES)
    monkeypatch.setattr(status, 'provider_recovery_pending', lambda: False)
    monkeypatch.setattr(status, 'read_record', lambda _: None)

    def read_journal(*args):
        assert args[:3] == ('journalctl', '--boot', '--unit=asb-backup.service')
        return journal

    monkeypatch.setattr(status, '_read_command', read_journal)
    for snapshots, matches in (([fields, fields], True),
                               ([fields, fields.replace('PID=42', 'PID=43')], False)):
        replies = iter(['ActiveState=active\nUnitFileState=enabled', *snapshots])
        monkeypatch.setattr(status, 'systemctl', lambda *_: next(replies))
        assert status.main() == 1
        output = capsys.readouterr().out
        result = json.loads(output)
        assert result['status'] == 'ALERT'
        assert result.get('failure_stage') == (stage if matches else None)
        assert result.get('failure_stage_code') == (code if matches and stage else None)
        assert result['failure_reason_code'] == (code if matches else 15)
        assert result.get('failure_error_type') == (legacy['error_type'] if matches else None)
        assert result.get('failure_error_location') == (legacy['error_location'] if matches else None)
        assert 'private diagnostic data' not in output
