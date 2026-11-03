"""Quarantine a credential rotation after interruption; never deploy a key.

Arming the real pilot remains explicitly blocked until the boot unit and the
legacy recovery guards have been independently installed and verified. This
tool never reads, writes, prints, revokes or starts a credential. A successful
recovery keeps the marker in place and never starts either generation.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat

import backup_service_guard as backup
import narration_deploy_safety as narration
_PRODUCTION_MARKER = Path('/var/lib/ai-story-book/provider-rotation/recovery.json')
_SLOTS = {
    'old_api': {'asb-pilot-api', 'asb-pilot-api-before-provider'},
    'old_worker': {'asb-pilot-worker', 'asb-pilot-worker-before-provider'},
    'new_api': {'asb-pilot-api', 'asb-provider-next-api'},
    'new_worker': {'asb-pilot-worker', 'asb-provider-next-worker'},
}


class RotationGuardError(RuntimeError):
    pass


def _absent(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise RotationGuardError('Recovery state is unavailable') from None
    raise RotationGuardError('Another recovery is pending')


def _write_marker(path, identities):
    marker = path / 'recovery.json'
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump({'version': 1, 'containers': identities}, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        directory = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise RotationGuardError('Recovery marker could not be persisted') from None


def arm(*, state_dir, backup_state_dir, identities, image_ids, runtime):
    """Arm under the backup lock after all four exact containers have restart=no.

    Production arming is blocked. The inspected image IDs, not a caller's
    success flag, must match. Existing recovery markers prevent arming. Callers
    are responsible for stopping admission and all writers; arming is not a
    deployment authorization.
    """
    path = narration._private_directory(state_dir)
    backup_path = narration._private_directory(backup_state_dir)
    if path / 'recovery.json' != backup.PROVIDER_ROTATION_RECOVERY_MARKER or backup_path != narration.BACKUP_STATE:
        raise RotationGuardError('Recovery and backup coordination paths do not match')
    if path / 'recovery.json' == _PRODUCTION_MARKER:
        raise RotationGuardError('Production rotation remains blocked pending boot and ingress verification')
    identities = narration._validate_ids(identities)
    if (not isinstance(image_ids, dict) or set(image_ids) != set(identities)
            or any(not isinstance(value, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value)
                   for value in image_ids.values())
            or image_ids['old_api'] != image_ids['new_api']
            or image_ids['old_worker'] != image_ids['new_worker']):
        raise RotationGuardError('Pinned image identities are invalid')
    guard = backup.BackupServiceGuard(backup_path, runtime)
    fd = guard._locked()
    try:
        for marker in (path / 'recovery.json', path / 'docker-mutation.json', backup.NARRATION_RECOVERY_MARKER,
                       narration.PRIVACY_RECOVERY_MARKER, backup_path / 'restart-required.json'):
            _absent(marker)
        for slot, identifier in identities.items():
            item = runtime.inspect(identifier)
            if (item.get('id') != identifier or item.get('name') not in _SLOTS[slot]
                    or item.get('image_id') != image_ids[slot]
                    or item.get('restart_policy') != 'no'
                    or item.get('running') is not slot.startswith('old_')):
                raise RotationGuardError('Container identity or restart policy is unsafe')
        _write_marker(path, identities)
        return {'status': 'ROTATION_QUARANTINE_ARMED', 'production_authorized': False}
    finally:
        os.close(fd)


def quarantine(*, state_dir, runtime):
    """Stop and disarm all verified recorded containers; keep the marker."""
    path = narration._private_directory(state_dir)
    if path / 'recovery.json' != backup.PROVIDER_ROTATION_RECOVERY_MARKER:
        raise RotationGuardError('Recovery marker path does not match')
    lock = os.open(path / 'recovery.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = path / 'recovery.json'
        fd = os.open(marker, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise RotationGuardError('Invalid recovery marker')
            raw = os.read(fd, 4097)
            if len(raw) > 4096:
                raise RotationGuardError('Invalid recovery marker')
        finally:
            os.close(fd)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {'version', 'containers'} or type(data['version']) is not int or data['version'] != 1:
                raise ValueError('invalid marker')
            identities = narration._validate_ids(data['containers'])
        except (ValueError, TypeError, KeyError):
            raise RotationGuardError('Invalid recovery marker') from None
        failed = False
        confirmed = []
        for slot, identifier in identities.items():
            try:
                item = runtime.inspect(identifier)
                if (item.get('id') != identifier or item.get('name') not in _SLOTS[slot]
                        or type(item.get('running')) is not bool):
                    raise ValueError('identity mismatch')
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
                item = runtime.inspect(identifier)
                if item.get('running') is not False or item.get('restart_policy') != 'no':
                    failed = True
            except Exception:
                failed = True
        if failed:
            raise RotationGuardError('Rotation quarantine incomplete; marker retained')
        return {'status': 'ROTATION_QUARANTINED', 'production_authorized': False}
    except OSError:
        raise RotationGuardError('Recovery state unavailable') from None
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true', required=True)
    args = parser.parse_args()
    del args
    path = _PRODUCTION_MARKER.parent
    try:
        try:
            path.lstat()
        except FileNotFoundError:
            print(json.dumps({'status': 'NO_RECOVERY_NEEDED', 'production_authorized': False}))
            return 0
        narration._private_directory(path)
        mutation = path / 'docker-mutation.json'
        try:
            mutation.lstat()
        except FileNotFoundError:
            mutation_pending = False
        else:
            mutation_pending = True
        try:
            _PRODUCTION_MARKER.lstat()
        except FileNotFoundError:
            if mutation_pending:
                raise RotationGuardError('Docker mutation outcome remains unresolved')
            print(json.dumps({'status': 'NO_RECOVERY_NEEDED', 'production_authorized': False}))
            return 0
        result = quarantine(state_dir=path, runtime=narration.DockerRuntime())
        if mutation_pending:
            raise RotationGuardError('Docker mutation outcome remains unresolved')
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'status': 'RECOVERY_FAILED', 'production_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
