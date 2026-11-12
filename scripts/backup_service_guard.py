"""Crash-recovery primitive for the private-pilot backup scheduler.

This module is not a scheduler. A caller must separately
prove admission is stopped, all worker activity is drained, DB/media consistency,
independent backup upload, retention, deletion replay and boot recovery. It never
considers a completed callback proof of a usable backup.
"""

import errno
import fcntl
import ipaddress
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
# A real OS cold boot took 118 seconds just to import/start the API on the
# 1 GB pilot. Leave room for the worker too; normal backup restarts use 60s.
RECOVERY_COMMAND_SECONDS = 300
RECOVERY_COLD_START_SECONDS = 180


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
    # The 1 GB pilot's cold worker exceeded the former 30-second window.
    # The standalone cold-boot command supplies its own bounded startup budget.
    def __init__(self, *, deadline=None, startup_timeout_seconds=60):
        if type(startup_timeout_seconds) is not int or not 1 <= startup_timeout_seconds <= 300:
            raise ValueError('Invalid container startup budget')
        self._deadline = deadline
        self._startup_timeout_seconds = startup_timeout_seconds
        self._proxy_probe_failure = 'unavailable'

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

    def identity(self, name):
        """Pin only bounded process identity fields, never container environment."""
        if name not in (_API, _WORKER):
            raise GuardError('Unexpected container')
        fields = self._run(['inspect', '--format',
            '{{.Id}} {{.Image}} {{.State.Pid}} {{.State.StartedAt}} {{.State.Running}} {{.State.OOMKilled}}',
            name], timeout=15).split()
        if (len(fields) != 6 or not re.fullmatch('[0-9a-f]{64}', fields[0])
                or not re.fullmatch('sha256:[0-9a-f]{64}', fields[1])
                or not re.fullmatch('[1-9][0-9]{0,9}', fields[2])
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z', fields[3])
                or fields[4:] != ['true', 'false']):
            raise GuardError('Online service identity could not be verified')
        return tuple(fields[:4])

    def stop(self, name):
        if name not in (_API, _WORKER):
            raise GuardError('Unexpected container')
        self._run(['stop', '--time', '600', name], timeout=630)

    def start(self, name):
        if name not in (_API, _WORKER):
            raise GuardError('Unexpected container')
        self._run(['start', name], timeout=60)

    def verify_api_upstream(self):
        """Restore the HTTP route before waiting for a slow worker control reply."""
        deadline = self._probe_deadline(self._startup_timeout_seconds)
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                value = json.loads(self._run(
                    ['exec', _NGINX, 'wget', '-q', '-T', '3', '-O', '-',
                     f'http://{_API}:8000/health/live'], timeout=min(8, remaining),
                ))
                if isinstance(value, dict) and value.get('status') == 'alive':
                    return
            except (GuardError, ValueError):
                pass
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise GuardError('API upstream did not report liveness')

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
                remaining = deadline - time.monotonic()
                if remaining < 3:
                    time.sleep(max(0, remaining))
                    break
                # Killing a timed-out docker CLI alone can leave its exec
                # process alive. Arm an in-container watchdog before imports.
                lifetime = min(35, int(remaining) - 2)
                workers = probe(['exec', _WORKER, 'python', '-c',
                                 worker_control_source(('ping',), timeout=10,
                                                       expected_hostnames=(hostname,), target_only=True,
                                                       process_timeout=lifetime)],
                                command_timeout=45)
                if workers == {'ping': True}:
                    return
            except (GuardError, ValueError):
                pass
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise GuardError('API upstream or expected worker did not respond')

    def reload_proxy(self):
        if self._run(['inspect', '--format', '{{.State.Running}}', _NGINX], timeout=15) != 'true':
            raise GuardError('Proxy is not running')
        self._verify_proxy_dns(self._probe_deadline(10))

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
            raise GuardError('Reloaded proxy did not serve API liveness over HTTPS: '
                             + self._proxy_probe_failure)
        raise GuardError('Proxy did not start a new worker after reload')

    def _verify_proxy_dns(self, deadline):
        """A live response from one peer is not proof that no retired peer remains."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GuardError('Proxy DNS verification time budget exhausted')
        expected = self._run(
            ['inspect', '--format', '{{(index .NetworkSettings.Networks "asb-pilot-net").IPAddress}}', _API],
            timeout=min(5, remaining),
        )
        try:
            address = ipaddress.IPv4Address(expected)
            if not address.is_private or address.is_loopback or address.is_unspecified:
                raise ValueError
        except ValueError:
            raise GuardError('Current API network address is invalid') from None
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                raw = self._run(['exec', _NGINX, 'getent', 'hosts', _API], timeout=min(5, remaining))
                addresses = {str(ipaddress.IPv4Address(line.split()[0]))
                             for line in raw.splitlines() if line.strip()}
                if addresses == {expected}:
                    return
            except (GuardError, ValueError, IndexError):
                pass
            time.sleep(min(.25, max(0, deadline - time.monotonic())))
        raise GuardError('Proxy DNS does not exclusively select the current API')

    def _proxy_is_live(self, remaining):
        if remaining <= 0:
            self._proxy_probe_failure = 'time_budget'
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
            good = code == b'200' and isinstance(payload, dict) and payload.get('status') == 'alive'
            self._proxy_probe_failure = ('unavailable' if good else
                                         'http_' + code.decode('ascii') if re.fullmatch(rb'[0-9]{3}', code)
                                         and code != b'200' else 'invalid_response')
            return good
        except subprocess.TimeoutExpired:
            self._proxy_probe_failure = 'timeout'
            return False
        except subprocess.CalledProcessError as exc:
            # Keep only finite transport reasons, never curl stderr, response
            # bodies, URLs or provider/user data in recovery diagnostics.
            self._proxy_probe_failure = {28: 'timeout', 60: 'tls_verification',
                                         22: 'http_failure'}.get(exc.returncode, 'transport_failure')
            if exc.returncode == 22 and isinstance(exc.stdout, bytes):
                code = exc.stdout.rpartition(b'\n')[2]
                if re.fullmatch(rb'[1-5][0-9]{2}', code) and code != b'200':
                    self._proxy_probe_failure = 'http_' + code.decode('ascii')
            return False
        except OSError:
            self._proxy_probe_failure = 'transport_unavailable'
            return False
        except ValueError:
            self._proxy_probe_failure = 'invalid_response'
            return False


class BackupServiceGuard:
    def __init__(self, state_dir: Path, runtime, *, timings_ms=None, start_worker_early=False):
        if type(start_worker_early) is not bool:
            raise ValueError('Invalid recovery start order')
        self._dir = Path(state_dir)
        self._runtime = runtime
        self._timings_ms = timings_ms
        self._start_worker_early = start_worker_early
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self._dir.lstat()
        if (not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode)
                or st.st_uid != os.geteuid() or st.st_mode & 0o077):
            raise GuardError('A private, non-symlink state directory is required')
        self._marker = self._dir / 'restart-required.json'
        self._lock = self._dir / 'backup.lock'
        self._online_expected = None

    def _timed(self, name, operation):
        if self._timings_ms is None:
            return operation()
        start = time.monotonic_ns()
        try:
            return operation()
        finally:
            elapsed = (time.monotonic_ns() - start) // 1_000_000
            self._timings_ms[name] = self._timings_ms.get(name, 0) + elapsed

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
        def start(name):
            if not self._runtime.running(name):
                self._runtime.start(name)
            if not self._runtime.running(name):
                raise GuardError('Service did not start')

        # A normal backup routes HTTP first. During OS cold recovery, start
        # both roles before waiting: serial cold imports consumed the entire
        # shared budget while the worker had not even been launched.
        route_error = None
        worker_error = None
        def start_worker():
            nonlocal worker_error
            try:
                self._timed('recovery_worker_start', lambda: start(_WORKER))
            except Exception as exc:
                worker_error = RetryableRecoveryError('Service restart incomplete; recovery marker retained')
                worker_error.__cause__ = exc

        try:
            self._timed('recovery_api_start', lambda: start(_API))
        except Exception as exc:
            route_error = RetryableRecoveryError('Service restart incomplete; recovery marker retained')
            route_error.__cause__ = exc
        if self._start_worker_early:
            start_worker()
        if route_error is None:
            try:
                self._timed('recovery_api_upstream', self._runtime.verify_api_upstream)
            except Exception as exc:
                route_error = RetryableRecoveryError('Service liveness check failed; recovery marker retained')
                route_error.__cause__ = exc
        if route_error is None:
            try:
                # A restarted API can have a new IP; verify DNS and strict TLS.
                self._timed('recovery_proxy', self._runtime.reload_proxy)
            except Exception as exc:
                route_error = RetryableRecoveryError('Proxy reload failed; recovery marker retained')
                route_error.__cause__ = exc
        if not self._start_worker_early:
            start_worker()
        if worker_error is not None:
            raise worker_error
        if route_error is not None:
            raise route_error
        try:
            self._timed('recovery_worker_response', self._runtime.verify_recovery)
        except Exception:
            # HTTP reads can recover while a worker is still starting. The
            # cycle remains unverified until the exact worker also responds.
            raise RetryableRecoveryError('Service liveness check failed; recovery marker retained') from None
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

    def run_online(self, *, backup):
        """Exclude deployments/recovery without stopping or restarting a service."""
        fd = self._locked()
        try:
            assert_no_narration_recovery()
            if self._marker.exists() or self._marker.is_symlink():
                raise GuardError('Previous backup requires recovery before another run')
            if not self._runtime.running(_API) or not self._runtime.running(_WORKER):
                raise GuardError('Both pilot services must initially be running')
            self._online_expected = {name: self._runtime.identity(name) for name in (_API, _WORKER)}
            result = backup()
            self.verify_online_identity()
            return result
        finally:
            # An online failure never creates a restart marker or alters a
            # container. Only the source/destination snapshot is discarded.
            self._online_expected = None
            os.close(fd)

    def verify_online_identity(self):
        """Also run immediately before publication, not only after capture."""
        if (self._online_expected is None or any(
                self._runtime.identity(name) != expected
                for name, expected in self._online_expected.items())):
            raise GuardError('A service restarted or changed during the online backup')

    def _run_unlocked(self, *, verify_idle, backup):
        """Caller must hold this guard's exclusive backup.lock for entire call."""
        assert_no_narration_recovery()
        if self._marker.exists() or self._marker.is_symlink():
            raise GuardError('Previous backup requires recovery before another run')
        if not self._runtime.running(_API) or not self._runtime.running(_WORKER):
            raise GuardError('Both pilot services must initially be running')
        self._write_marker()
        try:
            self._timed('admission_stop', lambda: self._runtime.stop(_API))
            if self._runtime.running(_API):
                raise GuardError('API did not stop')
            verify_idle()  # API is stopped; worker still running.
            self._timed('worker_stop', lambda: self._runtime.stop(_WORKER))
            if self._runtime.running(_WORKER):
                raise GuardError('Worker did not stop')
            return backup()  # The callback must verify isolation and consistency.
        finally:
            self._recover_unlocked()


def recover_services(state_dir):
    """Retry cold-start failures within 300s; systemd leaves 30s cleanup margin."""
    deadline = time.monotonic() + RECOVERY_COMMAND_SECONDS
    guard = BackupServiceGuard(state_dir, DockerRuntime(
        deadline=deadline, startup_timeout_seconds=RECOVERY_COLD_START_SECONDS,
    ), start_worker_early=True)
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
    except Exception as exc:
        print(json.dumps({'status': 'RECOVERY_FAILED', 'reason': recovery_failure_code(exc)}))
        return 1


def recovery_failure_code(exc):
    """Return only finite operator reasons, without any exception payload."""
    codes = {
        'Another backup or recovery is running': 'lock_busy',
        'Recovery required; automatic restart blocked': 'recovery_fence',
        'Recovery state cannot be verified; automatic restart blocked': 'recovery_fence',
        'Recovery marker is invalid; manual investigation required': 'invalid_marker',
        'Recovery time budget exhausted': 'time_budget',
        'API upstream did not report liveness': 'api_upstream',
        'API upstream or expected worker did not respond': 'worker_response',
        'Proxy DNS does not exclusively select the current API': 'proxy_dns',
        'Proxy is not running': 'proxy_not_running',
        'Proxy did not start a new worker after reload': 'proxy_reload',
        'Container operation failed': 'container_operation',
    }
    seen = set()
    reason = 'unclassified'
    while exc is not None and id(exc) not in seen and len(seen) < 12:
        seen.add(id(exc))
        if type(exc) in (GuardError, RetryableRecoveryError):
            message = str(exc)
            if message in codes:
                reason = codes[message]
            elif message.startswith('Reloaded proxy did not serve API liveness over HTTPS: '):
                value = message.rsplit(': ', 1)[-1]
                if value in {'timeout', 'tls_verification', 'http_failure', 'transport_failure',
                             'transport_unavailable', 'invalid_response', 'time_budget'}:
                    reason = 'proxy_' + value
                elif re.fullmatch(r'http_[1-5][0-9]{2}', value):
                    reason = 'proxy_' + value
        exc = exc.__cause__ or exc.__context__
    return reason


if __name__ == '__main__':
    raise SystemExit(main())
