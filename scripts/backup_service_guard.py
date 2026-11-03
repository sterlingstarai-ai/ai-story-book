"""Crash-recovery primitive for the private-pilot backup scheduler.

This module is not a scheduler. A caller must separately
prove admission is stopped, all worker activity is drained, DB/media consistency,
independent backup upload, retention, deletion replay and boot recovery. It never
considers a completed callback proof of a usable backup.
"""

import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess


class GuardError(RuntimeError):
    pass


# Never accept container names from a configuration file or operator input.
_API = 'asb-pilot-api'
_WORKER = 'asb-pilot-worker'
_NGINX = 'asb-pilot-nginx'
_MARKER = {'version': 1, 'previously_running': [_WORKER, _API]}
NARRATION_RECOVERY_MARKER = Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json')
PROVIDER_ROTATION_RECOVERY_MARKER = Path('/var/lib/ai-story-book/provider-rotation/recovery.json')


def assert_no_narration_recovery():
    """Block legacy restart during narration deployment or provider rotation.

    Both recovery paths use the same backup lock. Marker presence, including
    a dangling symlink or corrupt contents, is enough to block a restart. The
    provider marker does not itself implement rotation or guarantee boot
    quarantine: Docker restart policies must separately be disabled first.
    """
    for marker in (NARRATION_RECOVERY_MARKER, PROVIDER_ROTATION_RECOVERY_MARKER):
        try:
            marker.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise GuardError('Recovery state cannot be verified; automatic restart blocked') from None
        raise GuardError('Recovery required; automatic restart blocked')


class DockerRuntime:
    def _run(self, command, *, timeout):
        try:
            return subprocess.run(['docker', *command], check=True, capture_output=True,
                                  text=True, timeout=timeout).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise GuardError('Container operation failed') from None

    def running(self, name):
        if name not in (_API, _WORKER):
            raise GuardError('Unexpected container')
        value = self._run(['inspect', '--format', '{{.State.Running}}', name], timeout=15)
        if value not in ('true', 'false'):
            raise GuardError('Container state is unknown')
        return value == 'true'

    def stop(self, name):
        if name not in (_API, _WORKER):
            raise GuardError('Unexpected container')
        self._run(['stop', '--time', '600', name], timeout=630)

    def start(self, name):
        if name not in (_API, _WORKER):
            raise GuardError('Unexpected container')
        self._run(['start', name], timeout=60)

    def reload_proxy(self):
        if self._run(['inspect', '--format', '{{.State.Running}}', _NGINX], timeout=15) != 'true':
            raise GuardError('Proxy is not running')
        self._run(['exec', _NGINX, 'nginx', '-s', 'reload'], timeout=30)


class BackupServiceGuard:
    def __init__(self, state_dir: Path, runtime):
        self._dir = Path(state_dir)
        self._runtime = runtime
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self._dir.lstat()
        if (not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode)
                or st.st_uid != os.geteuid() or st.st_mode & 0o077):
            raise GuardError('A private, non-symlink state directory is required')
        self._marker = self._dir / 'restart-required.json'
        self._lock = self._dir / 'backup.lock'

    def _locked(self):
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(self._lock, flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise GuardError('Another backup or recovery is running') from None
        return fd

    def _sync_dir(self):
        fd = os.open(self._dir, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_marker(self):
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(self._marker, flags, 0o600)
        except OSError:
            raise GuardError('A backup recovery marker already exists or is inaccessible') from None
        with os.fdopen(fd, 'w') as output:
            json.dump(_MARKER, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        self._sync_dir()

    def _recover_unlocked(self):
        if not self._marker.exists() and not self._marker.is_symlink():
            return False
        assert_no_narration_recovery()
        if self._marker.is_symlink() or not self._marker.is_file():
            raise GuardError('Recovery marker is invalid; manual investigation required')
        try:
            if json.loads(self._marker.read_text()) != _MARKER:
                raise ValueError('unexpected marker')
        except (OSError, ValueError, TypeError):
            raise GuardError('Recovery marker is invalid; manual investigation required') from None
        failures = []
        for name in (_WORKER, _API):
            try:
                if not self._runtime.running(name):
                    self._runtime.start(name)
                if not self._runtime.running(name):
                    failures.append(name)
            except Exception:
                failures.append(name)
        if failures:
            raise GuardError('Service restart incomplete; recovery marker retained')
        try:
            # Docker may assign the restarted API a different address. Nginx
            # must resolve it again before the recovery marker can be removed.
            self._runtime.reload_proxy()
        except Exception:
            raise GuardError('Proxy reload failed; recovery marker retained') from None
        self._marker.unlink()
        self._sync_dir()
        return True

    def recover(self):
        fd = self._locked()
        try:
            return self._recover_unlocked()
        finally:
            os.close(fd)

    def run(self, *, verify_idle, backup):
        """Run callbacks with worker/API stopped; backup is NOT authorized here."""
        fd = self._locked()
        try:
            return self._run_unlocked(verify_idle=verify_idle, backup=backup)
        finally:
            os.close(fd)

    def _run_unlocked(self, *, verify_idle, backup):
        """Caller must hold this guard's exclusive backup.lock for entire call."""
        assert_no_narration_recovery()
        if self._marker.exists() or self._marker.is_symlink():
            raise GuardError('Previous backup requires recovery before another run')
        if not self._runtime.running(_API) or not self._runtime.running(_WORKER):
            raise GuardError('Both pilot services must initially be running')
        self._write_marker()
        try:
            self._runtime.stop(_API)
            if self._runtime.running(_API):
                raise GuardError('API did not stop')
            verify_idle()  # API is stopped; worker still running.
            self._runtime.stop(_WORKER)
            if self._runtime.running(_WORKER):
                raise GuardError('Worker did not stop')
            return backup()  # The callback must verify isolation and consistency.
        finally:
            self._recover_unlocked()


def main(argv=None):
    """Only recover a previously interrupted guard; never start a backup."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--recover', action='store_true', required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        recovered = BackupServiceGuard(args.state_dir, DockerRuntime()).recover()
        print(json.dumps({'status': 'RECOVERED' if recovered else 'NO_RECOVERY_NEEDED'}))
        return 0
    except Exception:
        print(json.dumps({'status': 'RECOVERY_FAILED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
