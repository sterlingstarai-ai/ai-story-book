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
import tempfile
import time


class NarrationSafetyError(RuntimeError):
    pass


class WorkerDrainUnverified(NarrationSafetyError):
    """The old worker may still be processing accepted work."""


_RETIRED_NAMES = {
    stage: {f'old_{role}': f'asb-pilot-{role}-before-{stage}' for role in ('api', 'worker')}
    for stage in ('media', 'narration')
}
_SLOTS = {
    'old_api': {'asb-pilot-api', *[names['old_api'] for names in _RETIRED_NAMES.values()]},
    'old_worker': {'asb-pilot-worker', *[names['old_worker'] for names in _RETIRED_NAMES.values()]},
    'new_api': {'asb-pilot-api', 'asb-narration-next-api', 'asb-media-rollback-api'},
    'new_worker': {'asb-pilot-worker', 'asb-narration-next-worker', 'asb-media-rollback-worker'},
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


def _validate_proxy(proxy, identities):
    if (not isinstance(proxy, dict) or set(proxy) != {'id', 'image_id'}
            or not isinstance(proxy['id'], str) or not re.fullmatch('[0-9a-f]{64}', proxy['id'])
            or proxy['id'] in identities.values() or not isinstance(proxy['image_id'], str)
            or not re.fullmatch('sha256:[0-9a-f]{64}', proxy['image_id'])):
        raise NarrationSafetyError('Invalid recovery proxy identity')
    return dict(proxy)


def _write_marker(path, identities, *, proxy=None, published_images=None):
    """Create the quarantine record or replace it after verified publication."""
    payload = {'version': 1, 'containers': identities}
    if proxy is not None:
        payload.update(version=2, proxy=_validate_proxy(proxy, identities))
    if published_images is not None:
        if proxy is None or not isinstance(published_images, dict) or set(published_images) != set(identities):
            raise NarrationSafetyError('Published release identities are invalid')
        if any(not isinstance(image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image)
               for image in published_images.values()):
            raise NarrationSafetyError('Published release images are invalid')
        payload.update(version=3, published_images=published_images)
    marker = path / 'narration-recovery.json'
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(payload, stream, sort_keys=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
                if published_images is None:
                    os.link(temporary, marker, follow_symlinks=False)
                else:
                    # Release holds the shared lock and has verified publication.
                    os.replace(temporary, marker)
            finally:
                temporary.unlink(missing_ok=True)
    except OSError:
        raise NarrationSafetyError('Recovery marker already exists or is inaccessible') from None
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


def _read_recovery_marker(marker):
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
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
        if not isinstance(data, dict) or type(data.get('version')) is not int:
            raise ValueError()
        identities = _validate_ids(data['containers'])
        version = data['version']
        proxy = None
        if version in (2, 3):
            proxy = _validate_proxy(data['proxy'], identities)
        expected = {'version', 'containers'}
        if proxy is not None:
            expected.add('proxy')
        if version == 3:
            expected.add('published_images')
            images = data['published_images']
            if (not isinstance(images, dict) or set(images) != set(identities)
                    or any(not isinstance(image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image)
                           for image in images.values())):
                raise ValueError()
        if version not in (1, 2, 3) or set(data) != expected:
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError):
        raise NarrationSafetyError('Invalid recovery marker') from None


def quarantine(directory, runtime):
    """Stop only pre-recorded, identity-checked pilot containers; keep marker.

    Stop and restart-policy failures are reported after attempting all targets.
    No code path starts an older image or changes the database.
    """
    path = _private_directory(directory)
    lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    lock_fd = os.open(path / 'narration-recovery.lock', lock_flags, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = _read_recovery_marker(path / 'narration-recovery.json')
        identities = data['containers']
        proxy = data.get('proxy')
        # A missing or foreign container must not prevent us from quarantining
        # the other identity-checked containers. Never touch an unverified ID.
        confirmed = []
        failed = False
        if proxy is not None:
            try:
                item = runtime.inspect(proxy['id'])
                if (item.get('id') != proxy['id'] or item.get('name') != 'asb-pilot-nginx'
                        or item.get('image_id') != proxy['image_id'] or type(item.get('running')) is not bool):
                    raise ValueError('proxy identity mismatch')
                confirmed.append(proxy['id'])
            except Exception:
                failed = True
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


def _resume_published(path, runtime, data):
    identities, images, proxy = data['containers'], data['published_images'], data['proxy']
    current_names = {'new_api': 'asb-pilot-api', 'new_worker': 'asb-pilot-worker'}
    proxy_verified = False
    try:
        item = runtime.inspect(proxy['id'])
        if (item.get('id') != proxy['id'] or item.get('name') != 'asb-pilot-nginx'
                or item.get('image_id') != proxy['image_id'] or type(item.get('running')) is not bool):
            raise NarrationSafetyError('Published proxy identity differs')
        proxy_verified = True
        if item.get('restart_policy') not in {'no', 'unless-stopped'}:
            raise NarrationSafetyError('Published proxy restart policy differs')
        retired_names = {}
        for slot, identifier in identities.items():
            item = runtime.inspect(identifier)
            if (item.get('id') != identifier or item.get('name') not in _SLOTS[slot]
                    or item.get('image_id') != images[slot] or type(item.get('running')) is not bool
                    or item.get('restart_policy') not in {'no', 'unless-stopped'}
                    or (slot.startswith('old_')
                        and (item['running'] or item['restart_policy'] != 'no'))):
                raise NarrationSafetyError('Published container identity or policy differs')
            if slot in current_names:
                if item['name'] != current_names[slot]:
                    raise NarrationSafetyError('Published container name differs')
            else:
                retired_names[slot] = item['name']
        if retired_names not in _RETIRED_NAMES.values():
            raise NarrationSafetyError('Published retired containers belong to different stages')
        api, worker = identities['new_api'], identities['new_worker']
        for identifier in (api, worker):
            if not runtime.inspect(identifier)['running']:
                runtime._run('start', identifier)
        probe = ("import urllib.request; "
                 "assert urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=5).status==200")
        for attempt in range(10):
            try:
                runtime._run('exec', api, 'python', '-c', probe)
                break
            except NarrationSafetyError:
                if attempt == 9:
                    raise
                time.sleep(2)
        worker_host = runtime._run('inspect', '--format', '{{.Config.Hostname}}', worker)
        if not re.fullmatch('[A-Za-z0-9_.-]{1,253}', worker_host):
            raise NarrationSafetyError('Published worker hostname is invalid')
        raw = runtime._run('exec', worker, 'celery', '-A', 'src.worker', 'inspect', 'ping', '--timeout', '10', '--json')
        if json.loads(raw) != {'celery@' + worker_host: {'ok': 'pong'}}:
            raise NarrationSafetyError('Published worker did not respond')
        if not runtime.inspect(proxy['id'])['running']:
            runtime._run('start', proxy['id'])
        runtime._run('exec', proxy['id'], 'wget', '-q', '-O', '/dev/null',
                     'http://asb-pilot-api:8000/health/ready')
        for identifier in (api, worker, proxy['id']):
            runtime.enable_restart(identifier)
            item = runtime.inspect(identifier)
            if item.get('running') is not True or item.get('restart_policy') != 'unless-stopped':
                raise NarrationSafetyError('Published restart policy could not be verified')
        (path / 'narration-recovery.json').unlink()
        fd = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError, KeyError, NarrationSafetyError):
        if proxy_verified and os.path.lexists(path / 'narration-recovery.json'):
            try:
                runtime.disable_restart(proxy['id'])
                if runtime.inspect(proxy['id'])['running']:
                    runtime.stop(proxy['id'])
            except NarrationSafetyError:
                pass
        raise NarrationSafetyError('Published restart recovery did not complete') from None
    return {'status': 'PUBLISHED_RELEASE_RECOVERED', 'restore_authorized': False}


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
    try:
        fd = backup_service_guard.BackupServiceGuard(BACKUP_STATE, runtime)._locked()
    except (backup_service_guard.GuardError, OSError):
        raise NarrationSafetyError('Another backup or deployment owns the recovery lock') from None
    try:
        # The deployment may have completed while we were acquiring its lock.
        try:
            (path / 'narration-recovery.json').lstat()
        except FileNotFoundError:
            return {'status': 'NO_RECOVERY_NEEDED', 'restore_authorized': False}
        try:
            data = _read_recovery_marker(path / 'narration-recovery.json')
        except OSError:
            raise NarrationSafetyError('Recovery marker unavailable') from None
        if data['version'] == 3:
            return _resume_published(path, runtime, data)
        return quarantine(path, runtime)
    finally:
        os.close(fd)


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
