"""Receive one provider key into a private file without printing its value.

The production CLI has fixed root-owned directory and app UID/GID, does not
replace an existing key, and stores a private recovery marker before writing.
It does not start services, install systemd units, or authorize a rollout.
"""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import urllib.request


class ReceiverError(RuntimeError):
    pass


_TOKEN = re.compile(r'[0-9a-f]{32}\Z')
_MAX_KEY = 4096
_PRODUCTION_DIRECTORY = '/etc/ai-story-book/pilot/private/provider-rotation'
_BACKUP_STATE = '/var/lib/ai-story-book/backup-state'
_OTHER_RECOVERY_MARKERS = (
    '/var/lib/ai-story-book/provider-install/activation.json',
    '/var/lib/ai-story-book/backup-state/restart-required.json',
    '/var/lib/ai-story-book/privacy-deploy/rollback.json',
    '/var/lib/ai-story-book/narration-deploy/narration-recovery.json',
    '/var/lib/ai-story-book/provider-rotation/docker-mutation.json',
    '/var/lib/ai-story-book/provider-rotation/recovery.json',
)


def _directory(path, owner):
    fds = []
    try:
        if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                or os.path.normpath(path) != path or path == '/'
                or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY')):
            raise ValueError()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        fds.append(os.open('/', flags))
        for part in path[1:].split('/'):
            fds.append(os.open(part, flags, dir_fd=fds[-1]))
        info = os.fstat(fds[-1])
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077:
            raise ValueError()
        return fds.pop()
    except Exception:
        raise ReceiverError('Private key directory is unavailable or unsafe') from None
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _sync(fd):
    os.fsync(fd)


def _read_key(stream):
    try:
        raw = stream.read(_MAX_KEY + 3)
        if not isinstance(raw, bytes) or len(raw) > _MAX_KEY + 2:
            raise ValueError()
        if raw.endswith(b'\r\n'):
            raw = raw[:-2]
        elif raw.endswith(b'\n'):
            raw = raw[:-1]
        if not re.fullmatch(rb'[\x21-\x7e]{1,4096}', raw):
            raise ValueError()
        return raw
    except Exception:
        raise ReceiverError('Key input is invalid') from None


def _marker_names(token):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ReceiverError('Transaction identity is invalid')
    return '.asb-key-' + token + '.json', '.asb-key-' + token + '.tmp'


def _file_info(directory, name):
    try:
        return os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _read_private(directory, name, *, owner, maximum):
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0), dir_fd=directory)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner
                or before.st_mode & 0o077 or before.st_size > maximum):
            raise ValueError()
        value = os.read(fd, maximum + 1)
        after = os.fstat(fd)
        if (len(value) != before.st_size or len(value) > maximum
                or any(getattr(before, field) != getattr(after, field) for field in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_mode'))):
            raise ValueError()
        return value, before
    except Exception:
        raise ReceiverError('Private transaction file is unavailable or unsafe') from None
    finally:
        if fd is not None:
            os.close(fd)


def install(stream, *, directory, token, directory_owner, target_uid, target_gid):
    """Publish a new 0600 key exactly once; retain marker on uncertainty."""
    marker_name, stage_name = _marker_names(token)
    if any(type(value) is not int or value < 0 for value in (directory_owner, target_uid, target_gid)):
        raise ReceiverError('Receiver identity is invalid')
    key = _read_key(stream)
    parent = _directory(directory, directory_owner)
    try:
        if any(name.startswith('.asb-key-') for name in os.listdir(parent)):
            raise ReceiverError('Another key transfer requires recovery')
        if _file_info(parent, 'provider.key') is not None or _file_info(parent, stage_name) is not None:
            raise ReceiverError('Key destination or transaction already exists')
        marker = json.dumps({'version': 1, 'token': token, 'sha256': hashlib.sha256(key).hexdigest()},
                            sort_keys=True, separators=(',', ':')).encode()
        fd = os.open(marker_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            os.fchmod(fd, 0o600)
            if os.write(fd, marker) != len(marker):
                raise OSError('short write')
            _sync(fd)
        finally:
            os.close(fd)
        _sync(parent)
        fd = os.open(stage_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            os.fchmod(fd, 0o600)
            if (target_uid, target_gid) != (os.geteuid(), os.getegid()):
                os.fchown(fd, target_uid, target_gid)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != target_uid or info.st_gid != target_gid
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError()
            created_identity = (info.st_dev, info.st_ino)
            view = memoryview(key)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError('short write')
                view = view[written:]
            _sync(fd)
        finally:
            os.close(fd)
        os.link(stage_name, 'provider.key', src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        final_info = os.stat('provider.key', dir_fd=parent, follow_symlinks=False)
        if ((final_info.st_dev, final_info.st_ino) != created_identity or not stat.S_ISREG(final_info.st_mode)
                or final_info.st_uid != target_uid or final_info.st_gid != target_gid
                or stat.S_IMODE(final_info.st_mode) != 0o600):
            raise ValueError()
        _sync(parent)
        os.unlink(stage_name, dir_fd=parent)
        _sync(parent)
        os.unlink(marker_name, dir_fd=parent)
        _sync(parent)
        return {'status': 'KEY_FILE_INSTALLED', 'recovery_required': False}
    except ReceiverError:
        raise
    except Exception:
        raise ReceiverError('Key transfer failed; recovery marker may remain') from None
    finally:
        # A process crash or exception after the marker must not guess whether
        # a partially written/published key belongs to this transaction.
        del key
        os.close(parent)


def recover(*, directory, token, directory_owner, target_uid, target_gid):
    """Resolve only this transaction without overwriting or deleting a key."""
    marker_name, stage_name = _marker_names(token)
    parent = _directory(directory, directory_owner)
    try:
        if any(name.startswith('.asb-key-') and name not in (marker_name, stage_name)
               for name in os.listdir(parent)):
            raise ValueError()
        raw, marker_info = _read_private(parent, marker_name, owner=directory_owner, maximum=4096)
        marker = json.loads(raw)
        if (not isinstance(marker, dict) or set(marker) != {'version', 'token', 'sha256'}
                or type(marker['version']) is not int or marker['version'] != 1 or marker['token'] != token
                or not isinstance(marker['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', marker['sha256'])):
            raise ValueError()
        stage = _file_info(parent, stage_name)
        final = _file_info(parent, 'provider.key')
        if stage is not None and (not stat.S_ISREG(stage.st_mode) or stage.st_uid not in (directory_owner, target_uid)
                                  or stat.S_IMODE(stage.st_mode) != 0o600):
            raise ValueError()
        if final is not None:
            value, final_info = _read_private(parent, 'provider.key', owner=target_uid, maximum=_MAX_KEY)
            if (final_info.st_gid != target_gid or stat.S_IMODE(final_info.st_mode) != 0o600
                    or not hmac.compare_digest(hashlib.sha256(value).hexdigest(), marker['sha256'])
                    or (stage is not None and (stage.st_dev, stage.st_ino) != (final.st_dev, final.st_ino))):
                raise ValueError()
        if stage is not None:
            os.unlink(stage_name, dir_fd=parent)
            _sync(parent)
        current = _file_info(parent, marker_name)
        if current is None or (current.st_dev, current.st_ino) != (marker_info.st_dev, marker_info.st_ino):
            raise ValueError()
        os.unlink(marker_name, dir_fd=parent)
        _sync(parent)
        return {'status': 'KEY_FILE_PRESENT' if final is not None else 'TRANSFER_CANCELLED',
                'recovery_required': False}
    except Exception:
        raise ReceiverError('Key transfer recovery is unresolved') from None
    finally:
        os.close(parent)


def _verify_instance(expected_id):
    if not isinstance(expected_id, str) or not re.fullmatch(r'[0-9]{1,32}', expected_id):
        raise ReceiverError('Expected instance identity is invalid')
    try:
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/id',
                                         headers={'Metadata-Flavor': 'Google'})
        with client.open(request, timeout=3) as response:
            value = response.read(33).decode('ascii').strip()
        if not hmac.compare_digest(value, expected_id):
            raise ValueError()
    except Exception:
        raise ReceiverError('Instance identity could not be confirmed') from None


def _lock_and_check_recovery():
    directory = _directory(_BACKUP_STATE, 0)
    fd = None
    try:
        fd = os.open('backup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for marker in _OTHER_RECOVERY_MARKERS:
            try:
                os.lstat(marker)
            except FileNotFoundError:
                continue
            raise ValueError()
        return fd
    except Exception:
        if fd is not None:
            os.close(fd)
        raise ReceiverError('Backup lock or recovery state is unavailable') from None
    finally:
        os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--install', metavar='TRANSACTION_ID')
    group.add_argument('--recover', metavar='TRANSACTION_ID')
    parser.add_argument('--expected-instance-id', required=True)
    args = parser.parse_args()
    lock = None
    try:
        if os.geteuid() != 0:
            raise ReceiverError('Root receiver is required')
        _verify_instance(args.expected_instance_id)
        lock = _lock_and_check_recovery()
        if args.install:
            outcome = install(sys.stdin.buffer, directory=_PRODUCTION_DIRECTORY, token=args.install,
                              directory_owner=0, target_uid=1000, target_gid=1000)
        else:
            outcome = recover(directory=_PRODUCTION_DIRECTORY, token=args.recover,
                              directory_owner=0, target_uid=1000, target_gid=1000)
        print(json.dumps(outcome, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'KEY_TRANSFER_FAILED', 'recovery_required': True}))
        return 1
    finally:
        if lock is not None:
            os.close(lock)


if __name__ == '__main__':
    raise SystemExit(main())
