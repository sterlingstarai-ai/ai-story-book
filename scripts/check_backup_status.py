"""Secret-free private pilot backup health check; never performs a backup."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from datetime import datetime, timezone

STATE = Path('/var/lib/ai-story-book/backup-state')
BACKUP_DIR = Path('/var/lib/ai-story-book/backups')
MAX_AGE_SECONDS = 48 * 60 * 60
MIN_FREE_BYTES = 1024 * 1024 * 1024
PROVIDER_MARKERS = (
    Path('/var/lib/ai-story-book/provider-rotation/recovery.json'),
    Path('/var/lib/ai-story-book/provider-rotation/docker-mutation.json'),
    Path('/var/lib/ai-story-book/provider-rotation/candidate-owner.json'),
    Path('/var/lib/ai-story-book/provider-rotation/probe-owner.json'),
    Path('/var/lib/ai-story-book/provider-install/activation.json'),
)


def assess(record, *, now, timer_active, service_result, free_bytes, provider_recovery_pending=False):
    problems = []
    if provider_recovery_pending is not False:
        problems.append('provider_recovery_pending')
    if not timer_active:
        problems.append('timer_inactive')
    if service_result != 'success':
        problems.append('last_service_failed')
    if type(free_bytes) is not int or free_bytes < MIN_FREE_BYTES:
        problems.append('disk_headroom_low')
    try:
        if (not isinstance(record, dict) or set(record) != {'version', 'verified_at', 'restore_authorized'}
                or type(record['version']) is not int or record['version'] != 1
                or record['restore_authorized'] is not False):
            raise ValueError('invalid record')
        timestamp = datetime.fromisoformat(record['verified_at'])
        if timestamp.tzinfo is None:
            raise ValueError('timezone missing')
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
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
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


def systemctl(*args):
    try:
        result = subprocess.run(['systemctl', *args], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


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


def provider_recovery_pending(paths=PROVIDER_MARKERS):
    """Report a marker or an unreadable state; reveal no marker contents."""
    for path in paths:
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            continue
        except OSError:
            return True
    return False


def main():
    free = backup_free_bytes(STATE, BACKUP_DIR)
    timer = systemctl('is-active', 'asb-backup.timer') == 'active'
    service = systemctl('show', 'asb-backup.service', '--property=Result', '--value')
    result = assess(read_record(STATE / 'last-verified-backup.json'), now=datetime.now(timezone.utc),
                    timer_active=timer, service_result=service, free_bytes=free,
                    provider_recovery_pending=provider_recovery_pending())
    print(json.dumps(result, sort_keys=True))
    return 1 if result['problems'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
