"""Secret-free private pilot backup health check; never performs a backup."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone

STATE = Path('/var/lib/ai-story-book/backup-state')
BACKUP_DIR = Path('/var/lib/ai-story-book/backups')
MAX_AGE_SECONDS = 48 * 60 * 60
MIN_FREE_BYTES = 1024 * 1024 * 1024
BACKUP_SERVICE = 'asb-backup.service'
BACKUP_TIMER = 'asb-backup.timer'
JOURNAL_INGEST_GRACE_USEC = 5_000_000
SERVICE_PROPERTIES = '--property=Result,ExecMainPID,ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic'
TIMER_PROPERTIES = '--property=ActiveState,UnitFileState'
BACKUP_FAILURE_STAGE_CODES = {
    'configuration': 1, 'backup_source': 2, 'writer_bindings': 3,
    'initialization': 4, 'source_preflight': 5, 'journal_preflight': 6,
    'guarded_backup': 7, 'destination_preflight': 20, 'local_destination_preflight': 21,
}
_BACKUP_ERROR_TYPES = {
    'AutomaticBackupError', 'BackupError', 'BackupPublishError', 'GuardError',
    'JournalError', 'JournalVerificationError', 'ScheduledBackupError',
    'BackupFenceError', 'RetryableRecoveryError', 'FileNotFoundError',
    'PermissionError', 'OSError', 'ModuleNotFoundError', 'TimeoutExpired',
}
_BACKUP_ERROR_FILES = {
    'automatic_backup.py', 'backup_external.py', 'backup_service_guard.py',
    'postgres_backup_fence.py', 'privacy_journal.py', 'privacy_journal_gcs.py',
    'privacy_journal_verify.py', 'publish_backup_gcs.py', 'run_scheduled_backup.py',
}
BACKUP_HEALTH_PROBLEM_CODES = {
    'backup_recovery_pending': 8,
    'provider_recovery_pending': 9,
    'timer_inactive': 10,
    'timer_not_enabled': 10,
    'disk_headroom_low': 11,
    'backup_timestamp_future': 12,
    'backup_stale': 13,
    'backup_record_invalid_or_missing': 14,
}
PROVIDER_MARKERS = (
    Path('/var/lib/ai-story-book/provider-rotation/recovery.json'),
    Path('/var/lib/ai-story-book/provider-rotation/docker-mutation.json'),
    Path('/var/lib/ai-story-book/provider-rotation/candidate-owner.json'),
    Path('/var/lib/ai-story-book/provider-rotation/probe-owner.json'),
    Path('/var/lib/ai-story-book/provider-install/activation.json'),
)


def _record_timestamp(record, field, *, extra_fields=()):
    if (not isinstance(record, dict) or set(record) != {'version', field, 'restore_authorized', *extra_fields}
            or type(record['version']) is not int or record['version'] != 1
            or record['restore_authorized'] is not False):
        raise ValueError('invalid record')
    timestamp = datetime.fromisoformat(record[field])
    if timestamp.tzinfo is None:
        raise ValueError('timezone missing')
    return timestamp


def recorded_failure_stage(failure, verified, *, now):
    try:
        failed_at = _record_timestamp(failure, 'failed_at', extra_fields=('stage',))
        stage = failure['stage']
        if not isinstance(stage, str) or stage not in BACKUP_FAILURE_STAGE_CODES:
            return None
        if (failed_at - now).total_seconds() > 300:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        if failed_at < _record_timestamp(verified, 'verified_at'):
            return None
    except (TypeError, ValueError, OverflowError):
        pass
    return stage


def assess(record, *, now, timer_active, timer_enabled, service_result, free_bytes, provider_recovery_pending=False,
           backup_recovery_pending=False, recorded_stage=None):
    problems = []
    if backup_recovery_pending is not False:
        problems.append('backup_recovery_pending')
    if provider_recovery_pending is not False:
        problems.append('provider_recovery_pending')
    if not timer_active:
        problems.append('timer_inactive')
    elif not timer_enabled:
        problems.append('timer_not_enabled')
    if service_result != 'success' or recorded_stage is not None:
        problems.append('last_service_failed')
    if type(free_bytes) is not int or free_bytes < MIN_FREE_BYTES:
        problems.append('disk_headroom_low')
    try:
        timestamp = _record_timestamp(record, 'verified_at')
        age = (now - timestamp).total_seconds()
        if age < -300:
            problems.append('backup_timestamp_future')
        elif age > MAX_AGE_SECONDS:
            problems.append('backup_stale')
    except (TypeError, ValueError, KeyError, OverflowError):
        problems.append('backup_record_invalid_or_missing')
    return {'status': 'ALERT' if problems else 'OK', 'problems': problems,
            'restore_authorized': False}


def read_record(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                return None
            value = os.read(fd, 4097)
            if len(value) > 4096:
                return None
            return json.loads(value)
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None


def _read_command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def systemctl(*args):
    return _read_command('systemctl', *args)


def latest_failure_diagnostic(service, journal):
    """Use only a structured failure from the current boot's last completed run."""
    try:
        pid = int(service['ExecMainPID'])
        started = int(service['ExecMainStartTimestampMonotonic'])
        finished = int(service['ExecMainExitTimestampMonotonic'])
    except (KeyError, ValueError, TypeError):
        return {}
    if pid <= 0 or not 0 < started <= finished:
        return {}
    matches = []
    for line in journal.splitlines():
        try:
            entry = json.loads(line)
            if entry.get('_SYSTEMD_UNIT') != BACKUP_SERVICE or int(entry['_PID']) != pid:
                continue
            timestamp = int(entry['__MONOTONIC_TIMESTAMP'])
            # Journald may ingest the final stdout line after the process exits.
            if not started <= timestamp <= finished + JOURNAL_INGEST_GRACE_USEC:
                continue
            outcome = json.loads(entry['MESSAGE'])
            if outcome.get('status') != 'FAILED' or outcome.get('restore_authorized') is not False:
                continue
            stage = outcome.get('stage')
            diagnostic = {}
            if isinstance(stage, str) and stage in BACKUP_FAILURE_STAGE_CODES:
                diagnostic['stage'] = stage
            error_type = outcome.get('error_type')
            location = outcome.get('error_location')
            if (isinstance(error_type, str) and error_type in _BACKUP_ERROR_TYPES
                    and isinstance(location, str)):
                filename, _, line_number = location.partition(':')
                if filename in _BACKUP_ERROR_FILES and re.fullmatch(r'[1-9][0-9]{0,5}', line_number):
                    diagnostic.update(error_type=error_type, error_location=location)
            if diagnostic:
                matches.append((timestamp, diagnostic))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return max(matches, key=lambda match: match[0])[1] if matches else {}


def failure_reason_code(problems, service_result, stage):
    """Prioritize recovery and preconditions over a previous run's diagnosis."""
    for problem, code in BACKUP_HEALTH_PROBLEM_CODES.items():
        if problem in problems and code <= 11:
            return code
    if 'last_service_failed' in problems:
        if stage is not None:
            return BACKUP_FAILURE_STAGE_CODES[stage]
        if not service_result:
            return 19
        if service_result == 'timeout':
            return 16
        if service_result in {'signal', 'core-dump', 'oom-kill'}:
            return 17
        return 15
    return next(BACKUP_HEALTH_PROBLEM_CODES[problem] for problem in problems)


def backup_free_bytes(state_dir, output_dir):
    """Check both filesystems, including a separately mounted backup directory."""
    try:
        # Before the first backup the output directory may not exist. Check
        # the filesystem of the nearest existing parent, without following a
        # dangling or final-component symlink.
        candidate = output_dir
        while not candidate.exists():
            if candidate.is_symlink() or candidate == candidate.parent:
                return 0
            candidate = candidate.parent
        if candidate.is_symlink() or not candidate.is_dir():
            return 0
        return min(shutil.disk_usage(state_dir).free, shutil.disk_usage(candidate).free)
    except OSError:
        return 0


def _recovery_marker_pending(path):
    """Report a marker or an unreadable state; reveal no marker contents."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def provider_recovery_pending(paths=PROVIDER_MARKERS):
    return any(_recovery_marker_pending(path) for path in paths)


def main():
    free = backup_free_bytes(STATE, BACKUP_DIR)
    timer_fields = systemctl('show', BACKUP_TIMER, TIMER_PROPERTIES)
    timer = dict(line.split('=', 1) for line in timer_fields.splitlines() if '=' in line)
    fields = systemctl('show', BACKUP_SERVICE, SERVICE_PROPERTIES)
    service = dict(line.split('=', 1) for line in fields.splitlines() if '=' in line)
    now = datetime.now(timezone.utc)
    verified = read_record(STATE / 'last-verified-backup.json')
    recorded_stage = recorded_failure_stage(read_record(STATE / 'last-scheduled-failure.json'), verified, now=now)
    service_result = service.get('Result') or None
    result = assess(verified, now=now,
                    timer_active=timer.get('ActiveState') == 'active',
                    timer_enabled=timer.get('UnitFileState') == 'enabled',
                    service_result=service_result, free_bytes=free, recorded_stage=recorded_stage,
                    provider_recovery_pending=provider_recovery_pending(),
                    backup_recovery_pending=_recovery_marker_pending(STATE / 'restart-required.json'))
    diagnostic = {}
    service_changed = False
    if 'last_service_failed' in result['problems'] and service_result not in (None, 'success'):
        journal = _read_command('journalctl', '--boot', f'--unit={BACKUP_SERVICE}', '--lines=80',
                                '--output=json', '--output-fields=MESSAGE,__MONOTONIC_TIMESTAMP,_SYSTEMD_UNIT,_PID',
                                '--no-pager')
        diagnostic = latest_failure_diagnostic(service, journal)
        if (diagnostic or recorded_stage) and fields != systemctl('show', BACKUP_SERVICE, SERVICE_PROPERTIES):
            service_changed = True
            diagnostic = {}
    stage = diagnostic.get('stage')
    if not service_changed and stage is None and service_result in (None, 'success', 'exit-code'):
        stage = recorded_stage
    if stage:
        result['failure_stage'] = stage
        result['failure_stage_code'] = BACKUP_FAILURE_STAGE_CODES[stage]
    if 'error_type' in diagnostic:
        result['failure_error_type'] = diagnostic['error_type']
        result['failure_error_location'] = diagnostic['error_location']
    if result['problems']:
        result['failure_reason_code'] = failure_reason_code(
            result['problems'], service_result, stage
        )
    print(json.dumps(result, sort_keys=True))
    return 1 if result['problems'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
