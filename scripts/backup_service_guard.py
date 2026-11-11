"""Crash-recovery primitive for the private-pilot backup scheduler.

This module is not a scheduler. A caller must separately
prove admission is stopped, all worker activity is drained, DB/media consistency,
independent backup upload, retention, deletion replay and boot recovery. It never
considers a completed callback proof of a usable backup.
"""

import errno
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time


class GuardError(RuntimeError):
    pass


class RetryableRecoveryError(GuardError):
    pass


# Never accept container names from a configuration file or operator input.
_API = 'asb-pilot-api'
_WORKER = 'asb-pilot-worker'
_NGINX = 'asb-pilot-nginx'
_PILOT_PROXY_TLS_IDENTITY = '35.209.174.246'
_MARKER = {'version': 1, 'previously_running': [_WORKER, _API]}
NARRATION_RECOVERY_MARKER = Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json')
PROVIDER_ROTATION_RECOVERY_MARKER = Path('/var/lib/ai-story-book/provider-rotation/recovery.json')
RECOVERY_RETRY_DELAYS_SECONDS = (5, 5, 15, 25, 30)
RECOVERY_COMMAND_SECONDS = 150


def assert_no_narration_recovery():
    """Block legacy restart during narration deployment or provider rotation.

    Both recovery paths use the same backup lock. Marker presence, including
    a dangling symlink or corrupt contents, is enough to block a restart. The
    provider marker does not itself implement rotation or guarantee boot
    quarantine: Docker restart policies must separately be disabled first.
    """
    for marker in (NARRATION_RECOVERY_MARKER, PROVIDER_ROTATION_RECOVERY_MARKER,
                   PROVIDER_ROTATION_RECOVERY_MARKER.with_name('docker-mutation.json')):
        try:
            marker.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise GuardError('Recovery state cannot be verified; automatic restart blocked') from None
        raise GuardError('Recovery required; automatic restart blocked')


class DockerRuntime:
    def __init__(self, *, deadline=None, startup_timeout_seconds=30):
        if type(startup_timeout_seconds) is not int or not 1 <= startup_timeout_seconds <= 300:
            raise ValueError('Invalid container startup budget')
        self._deadline = deadline
        self._startup_timeout_seconds = startup_timeout_seconds

    def _probe_deadline(self, seconds):
        deadline = time.monotonic() + seconds
        return min(deadline, self._deadline) if self._deadline is not None else deadline

    def _run(self, command, *, timeout):
        if self._deadline is not None:
            timeout = min(timeout, self._deadline - time.monotonic())
            if timeout <= 0:
                raise GuardError('Recovery time budget exhausted')
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

    def verify_recovery(self):
        """Wait for the API upstream and the exact worker to answer after start."""
        from worker_control_probe import worker_control_source

        hostname = self._run(['inspect', '--format', '{{.Config.Hostname}}', _WORKER], timeout=5)
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}', hostname):
            raise GuardError('Recovery worker hostname is invalid')
        deadline = self._probe_deadline(self._startup_timeout_seconds)

        def probe(command, command_timeout=8):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GuardError('Recovery probe timed out')
            return json.loads(self._run(command, timeout=min(command_timeout, remaining)))

        while time.monotonic() < deadline:
            try:
                live = probe(['exec', _NGINX, 'wget', '-q', '-T', '3', '-O', '-',
                              f'http://{_API}:8000/health/live'])
                if not isinstance(live, dict) or live.get('status') != 'alive':
                    raise GuardError('API upstream did not report liveness')
                workers = probe(['exec', _WORKER, 'python', '-c',
                                 worker_control_source(('ping',), timeout=10)], command_timeout=45)
                if workers == {'ping': True}:
                    return
            except (GuardError, ValueError):
                pass
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise GuardError('API upstream or expected worker did not respond')

    def reload_proxy(self):
        if self._run(['inspect', '--format', '{{.State.Running}}', _NGINX], timeout=15) != 'true':
            raise GuardError('Proxy is not running')

        def workers(timeout):
            value = self._run(['exec', _NGINX, 'pgrep', '-f', r'^nginx: worker process[[:space:]]*$'],
                              timeout=timeout)
            pids = set(value.splitlines())
            if not pids or any(not pid.isascii() or not pid.isdecimal() for pid in pids):
                raise GuardError('Proxy worker state is unavailable')
            return pids

        previous = workers(5)
        self._run(['exec', _NGINX, 'nginx', '-s', 'reload'], timeout=30)
        deadline = self._probe_deadline(10)
        reloaded = False
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                if not reloaded:
                    reloaded = not workers(min(5, remaining)).intersection(previous)
                if reloaded and self._proxy_is_live(deadline - time.monotonic()):
                    return
            except GuardError:
                pass
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        if reloaded:
            raise GuardError('Reloaded proxy did not serve API liveness over HTTPS')
        raise GuardError('Proxy did not start a new worker after reload')

    def _proxy_is_live(self, remaining):
        if remaining <= 0:
            return False
        try:
            # Validate the backend nginx certificate and route over loopback.
            # A VM -> Cloud Run -> same VM hairpin is not an internal recovery
            # check. The deployment coordinator separately verifies the public
            # Cloud Run origin from the external client before promotion.
            response = subprocess.run(
                ['/usr/bin/curl', '-q', '--silent', '--fail', '--noproxy', '*',
                 '--max-filesize', '65536', '--max-time', '3',
                 '--connect-to', f'{_PILOT_PROXY_TLS_IDENTITY}:443:127.0.0.1:443',
                 '--write-out', '\n%{http_code}', f'https://{_PILOT_PROXY_TLS_IDENTITY}/health/live'],
                capture_output=True, timeout=min(4, remaining), check=True,
                env={'PATH': '/usr/bin:/bin'},
            )
            body, _, code = response.stdout.rpartition(b'\n')
            payload = json.loads(body)
            return code == b'200' and isinstance(payload, dict) and payload.get('status') == 'alive'
        except (OSError, subprocess.SubprocessError, ValueError):
            return False


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
        except OSError as exc:
            os.close(fd)
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RetryableRecoveryError('Another backup or recovery is running') from None
            raise GuardError('Backup lock could not be verified') from None
        return fd

    def _sync_dir(self):
        fd = os.open(self._dir, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_marker(self):
        staged = None
        try:
            # A crash during serialization must never leave a partial marker at
            # the recovery path. Publish without replacing an existing marker.
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self._dir, prefix='.restart-required-', delete=False,
            ) as output:
                staged = Path(output.name)
                json.dump(_MARKER, output, sort_keys=True)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.link(staged, self._marker, follow_symlinks=False)
        except OSError:
            raise GuardError('A backup recovery marker already exists or is inaccessible') from None
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
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
            raise RetryableRecoveryError('Service restart incomplete; recovery marker retained')
        try:
            self._runtime.verify_recovery()
        except Exception:
            raise RetryableRecoveryError('Service liveness check failed; recovery marker retained') from None
        try:
            # Docker may assign the restarted API a different address. Nginx
            # must resolve it again before the recovery marker can be removed.
            self._runtime.reload_proxy()
        except Exception:
            raise RetryableRecoveryError('Proxy reload failed; recovery marker retained') from None
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


def recover_services(state_dir):
    """Retry temporary failures inside systemd's 180-second command budget."""
    deadline = time.monotonic() + RECOVERY_COMMAND_SECONDS
    guard = BackupServiceGuard(state_dir, DockerRuntime(deadline=deadline))
    for delay in RECOVERY_RETRY_DELAYS_SECONDS:
        try:
            return guard.recover()
        except RetryableRecoveryError:
            if time.monotonic() + delay >= deadline:
                raise
            # Recover releases the lock before waiting. Every attempt rechecks fences.
            time.sleep(delay)
    return guard.recover()


def main(argv=None):
    """Only recover a previously interrupted guard; never start a backup."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--recover', action='store_true', required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        recovered = recover_services(args.state_dir)
        print(json.dumps({'status': 'RECOVERED' if recovered else 'NO_RECOVERY_NEEDED'}))
        return 0
    except Exception:
        print(json.dumps({'status': 'RECOVERY_FAILED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
