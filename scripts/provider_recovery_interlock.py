"""Serialize legacy privacy recovery with a provider rotation.

The installed systemd unit must run this wrapper instead of directly invoking
the legacy recovery command. A durable provider marker always blocks it. The
transition must acquire the same lock before publishing the marker. This
component alone does not prove systemd boot ordering or implement a rollout.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys


class InterlockError(RuntimeError):
    pass


_LEGACY_PRIVACY_SHA256 = 'e7aa61afc9de1f658f75a1946f1a9525a480369d751f0ee9f2e2ed84712fa16a'
_LEGACY_PRIVACY_SCRIPT = '/opt/ai-story-book/current/scripts/deploy_pilot_privacy.py'


def _verify_source(path, expected_sha256):
    """Do not wrap the newer self-locking recovery or an unreviewed version."""
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024:
            raise ValueError()
        digest = hashlib.sha256()
        chunks = []
        total = 0
        for block in iter(lambda: os.read(fd, 65536), b''):
            total += len(block)
            if total > 1024 * 1024:
                raise ValueError()
            digest.update(block)
            chunks.append(block)
        after = os.fstat(fd)
        if (any(getattr(before, n) != getattr(after, n) for n in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
                or digest.hexdigest() != expected_sha256):
            raise ValueError()
        resolved = str(Path(path).resolve(strict=True))
        linked = os.stat(resolved, follow_symlinks=False)
        if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError()
        return resolved, b''.join(chunks)
    except Exception:
        raise InterlockError('Legacy recovery source is not the verified version') from None
    finally:
        if fd is not None:
            os.close(fd)


def _private_directory(path):
    path = Path(path)
    try:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise ValueError()
        return path
    except Exception:
        raise InterlockError('Interlock directory is unavailable or unsafe') from None


def run_guarded(*, state_dir, marker_dir, command, timeout=600, source_sha256=None):
    """Hold the shared lock and check the marker before starting recovery."""
    state = _private_directory(state_dir)
    marker_path = _private_directory(marker_dir)
    markers = (marker_path / 'recovery.json', marker_path / 'docker-mutation.json')
    if (not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command)
            or type(timeout) is not int or not 1 <= timeout <= 900):
        raise InterlockError('Recovery command is invalid')
    fd = None
    try:
        fd = os.open(state / 'backup.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise InterlockError('Interlock lock file is unsafe')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for marker in markers:
            try:
                marker.lstat()
            except FileNotFoundError:
                continue
            raise InterlockError('Provider rotation or Docker mutation recovery is pending')
        child_command = command
        source = None
        if source_sha256 is not None:
            if len(command) != 3 or command[-1] != '--recover':
                raise InterlockError('Legacy recovery command is invalid')
            resolved, source = _verify_source(command[1], source_sha256)
            bootstrap = ("import os,sys; p=sys.argv[1]; data=sys.stdin.buffer.read(1048577); "
                         "sys.argv=[p,'--recover']; sys.path.insert(0,os.path.dirname(p)); "
                         "exec(compile(data,p,'exec'),{'__name__':'__main__','__file__':p})")
            child_command = [command[0], '-c', bootstrap, resolved]
        # Pass the lock to the legacy process, so a wrapper SIGKILL cannot
        # release it while that direct child is still performing recovery.
        completed = subprocess.run(child_command, input=source, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=timeout, pass_fds=(fd,))
        if completed.returncode != 0:
            raise InterlockError('Legacy recovery did not complete')
        return True
    except InterlockError:
        raise
    except Exception:
        raise InterlockError('Recovery interlock could not be verified') from None
    finally:
        if fd is not None:
            os.close(fd)


def main():
    if len(sys.argv) != 1:
        return 75
    try:
        run_guarded(state_dir='/var/lib/ai-story-book/backup-state',
                    marker_dir='/var/lib/ai-story-book/provider-rotation',
                    command=['/opt/ai-story-book/current/apps/api/venv/bin/python',
                             _LEGACY_PRIVACY_SCRIPT, '--recover'], source_sha256=_LEGACY_PRIVACY_SHA256)
        return 0
    except InterlockError:
        return 75


if __name__ == '__main__':
    raise SystemExit(main())
