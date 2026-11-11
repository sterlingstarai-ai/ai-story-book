"""Expire finalized local copies after a fresh backup has been verified remotely."""

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat


def private(path, file_type):
    info = path.lstat()
    if not file_type(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Expected an owner-only regular file or directory')
    return info


def read_record(path):
    private(path, stat.S_ISREG)
    with path.open('rb') as source:
        data = source.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('Backup metadata is too large')
    return json.loads(data)


def expire(backup_dir, state_dir, *, execute=False, now=None):
    now = now or datetime.now(timezone.utc)
    private(backup_dir, stat.S_ISDIR)
    private(state_dir, stat.S_ISDIR)
    lock = state_dir / 'backup.lock'
    private(lock, stat.S_ISREG)
    with lock.open('rb') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.path.lexists(state_dir / 'restart-required.json'):
            raise ValueError('Backup recovery is pending')
        record = read_record(state_dir / 'last-verified-backup.json')
        verified = datetime.fromisoformat(record['verified_at'])
        if (record['version'] != 1 or record['restore_authorized'] is not False
                or not timedelta(0) <= now - verified <= timedelta(days=2)):
            raise ValueError('A recent remotely verified backup is required')

        sets = []
        for folder in backup_dir.iterdir():
            if not re.fullmatch(r'external-[a-z0-9_]{8}', folder.name):
                continue
            folder_info = private(folder, stat.S_ISDIR)
            manifest = read_record(folder / 'manifest.json')
            if manifest['format_version'] != 1 or manifest['database']['file'] != 'database.dump':
                raise ValueError('Unrecognized finalized backup format')
            created = datetime.fromisoformat(manifest['created_at'])
            modified = datetime.fromtimestamp(folder_info.st_mtime, timezone.utc)
            sets.append((max(created, modified), folder))

        cutoff = now - timedelta(days=30)
        sets.sort(reverse=True)
        candidates = [folder for stamp, folder in sets[2:] if stamp <= cutoff]
        if candidates and (len(sets) < 2 or sets[1][0] <= cutoff):
            raise ValueError('Two local backups inside the retention window are required')
        if execute:
            if not shutil.rmtree.avoids_symlink_attacks:
                raise ValueError('Safe recursive removal is unavailable')
            for folder in candidates:
                shutil.rmtree(folder)
        return {'retention_days': 30, 'eligible': len(candidates),
                'removed': len(candidates) if execute else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        result = expire(Path('/var/lib/ai-story-book/backups'), Path('/var/lib/ai-story-book/backup-state'),
                        execute=args.execute)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SystemExit(f'Local backup retention skipped ({type(exc).__name__})') from None
    print(json.dumps(result))


if __name__ == '__main__':
    main()
