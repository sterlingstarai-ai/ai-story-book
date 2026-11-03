"""Quarantine an interrupted narration deployment; never authorizes deployment.

The release orchestrator must arm the marker before schema or container changes,
disable automatic restarts on the four recorded containers while switching,
and install a boot-time recovery unit before using this primitive. This module
does not provide those controls and cannot alone make a live deployment safe.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess


class NarrationSafetyError(RuntimeError):
    pass


_SLOTS = {
    'old_api': {'asb-pilot-api', 'asb-pilot-api-before-narration'},
    'old_worker': {'asb-pilot-worker', 'asb-pilot-worker-before-narration'},
    'new_api': {'asb-pilot-api', 'asb-narration-next-api'},
    'new_worker': {'asb-pilot-worker', 'asb-narration-next-worker'},
}
PRIVACY_RECOVERY_MARKER = Path('/var/lib/ai-story-book/privacy-deploy/rollback.json')
BACKUP_STATE = Path('/var/lib/ai-story-book/backup-state')


def _assert_shared_paths(path, backup_path):
    # Recovery components must agree on one marker and one coordination lock.
    # This check prevents a seemingly successful release using a private lock
    # or a marker that the installed backup recovery never observes.
    import backup_service_guard
    if (path / 'narration-recovery.json' != backup_service_guard.NARRATION_RECOVERY_MARKER
            or backup_path != BACKUP_STATE):
        raise NarrationSafetyError('Recovery and backup coordination paths do not match')


def _private_directory(directory):
    path = Path(directory)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise NarrationSafetyError('Invalid private recovery directory')
    return path


def _validate_ids(ids):
    if (not isinstance(ids, dict) or set(ids) != set(_SLOTS)
            or any(not isinstance(x, str) or not re.fullmatch('[0-9a-f]{64}', x) for x in ids.values())
            or len(set(ids.values())) != len(ids)):
        raise NarrationSafetyError('Invalid recorded container identities')
    return dict(ids)


def arm(directory, ids, *, backup_state_dir):
    """Arm while holding the same lock as backup and old deployment recovery."""
    from backup_service_guard import PROVIDER_ROTATION_RECOVERY_MARKER
    path = _private_directory(directory)
    identities = _validate_ids(ids)
    backup_path = _private_directory(backup_state_dir)
    _assert_shared_paths(path, backup_path)
    lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    lock_fd = os.open(backup_path / 'backup.lock', lock_flags, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for pending in (backup_path / 'restart-required.json', PRIVACY_RECOVERY_MARKER,
                        PROVIDER_ROTATION_RECOVERY_MARKER):
            try:
                pending.lstat()
            except FileNotFoundError:
                continue
            raise NarrationSafetyError('Prior backup or privacy recovery is pending')
        _write_marker(path, identities)
    except OSError:
        raise NarrationSafetyError('Backup or recovery is active') from None
    finally:
        os.close(lock_fd)


def _write_marker(path, identities):
    """Durably record exact identities without overwriting an existing marker."""
    marker = path / 'narration-recovery.json'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(marker, flags, 0o600)
    except OSError:
        raise NarrationSafetyError('Recovery marker already exists or is inaccessible') from None
    with os.fdopen(fd, 'w') as stream:
        json.dump({'version': 1, 'containers': identities}, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    dir_fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class DockerRuntime:
    def _run(self, *args):
        try:
            return subprocess.run(['docker', *args], check=True, capture_output=True,
                                  text=True, timeout=90).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise NarrationSafetyError('Container operation failed') from None

    def inspect(self, identifier):
        try:
            raw = json.loads(self._run('inspect', identifier))
            item = raw[0]
            return {'id': item['Id'], 'name': item['Name'].lstrip('/'),
                    'image_id': item['Image'],
                    'running': item['State']['Running'],
                    'restart_policy': item['HostConfig']['RestartPolicy']['Name']}
        except (ValueError, KeyError, TypeError, IndexError):
            raise NarrationSafetyError('Container identity cannot be confirmed') from None

    def disable_restart(self, identifier):
        self._run('update', '--restart=no', identifier)

    def enable_restart(self, identifier):
        self._run('update', '--restart=unless-stopped', identifier)

    def stop(self, identifier):
        self._run('stop', '--time', '60', identifier)


def quarantine(directory, runtime):
    """Stop only pre-recorded, identity-checked pilot containers; keep marker.

    Stop and restart-policy failures are reported after attempting all four.
    No code path starts an older image or changes the database.
    """
    path = _private_directory(directory)
    lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    lock_fd = os.open(path / 'narration-recovery.lock', lock_flags, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = path / 'narration-recovery.json'
        fd = os.open(marker, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise NarrationSafetyError('Invalid recovery marker')
            payload = os.read(fd, 4097)
            if len(payload) > 4096:
                raise NarrationSafetyError('Invalid recovery marker')
        finally:
            os.close(fd)
        try:
            data = json.loads(payload)
            if not isinstance(data, dict) or set(data) != {'version', 'containers'} or type(data['version']) is not int or data['version'] != 1:
                raise ValueError('invalid marker')
            identities = _validate_ids(data['containers'])
        except (ValueError, TypeError, KeyError):
            raise NarrationSafetyError('Invalid recovery marker') from None
        # A missing or foreign container must not prevent us from quarantining
        # the other identity-checked containers. Never touch an unverified ID.
        confirmed = []
        failed = False
        for slot, identifier in identities.items():
            try:
                item = runtime.inspect(identifier)
                if (item.get('id') != identifier or item.get('name') not in _SLOTS[slot]
                        or type(item.get('running')) is not bool):
                    failed = True
                    continue
                confirmed.append(identifier)
            except Exception:
                failed = True
        for identifier in confirmed:
            try:
                runtime.disable_restart(identifier)
            except Exception:
                failed = True
            try:
                if runtime.inspect(identifier)['running']:
                    runtime.stop(identifier)
                final = runtime.inspect(identifier)
                if final.get('running') is not False or final.get('restart_policy') != 'no':
                    failed = True
            except Exception:
                failed = True
        if failed:
            raise NarrationSafetyError('Quarantine incomplete; recovery marker retained')
        return {'status': 'QUARANTINED', 'restore_authorized': False}
    except (OSError, json.JSONDecodeError):
        raise NarrationSafetyError('Recovery marker unavailable') from None
    finally:
        os.close(lock_fd)


def recover_if_armed(directory, runtime):
    """No-op when not armed; a corrupt or symlink marker still fails closed."""
    import backup_service_guard
    path = Path(directory)
    if path / 'narration-recovery.json' != backup_service_guard.NARRATION_RECOVERY_MARKER:
        raise NarrationSafetyError('Recovery marker path does not match')
    try:
        path.lstat()
    except FileNotFoundError:
        return {'status': 'NO_RECOVERY_NEEDED', 'restore_authorized': False}
    except OSError:
        raise NarrationSafetyError('Recovery directory unavailable') from None
    _private_directory(path)
    try:
        (path / 'narration-recovery.json').lstat()
    except FileNotFoundError:
        return {'status': 'NO_RECOVERY_NEEDED', 'restore_authorized': False}
    except OSError:
        raise NarrationSafetyError('Recovery marker unavailable') from None
    return quarantine(path, runtime)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true', required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(recover_if_armed(args.state_dir, DockerRuntime()), sort_keys=True))
        return 0
    except NarrationSafetyError:
        print(json.dumps({'status': 'MANUAL_INTERVENTION_REQUIRED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
