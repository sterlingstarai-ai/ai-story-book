"""Explicit opt-in GCE IAP session for the pinned provider-key sender.

This is an integration component, not an automatic deployment command. The
caller must finish its independent cutover preflight before setting execute.
No key is read until a dedicated pinned SSH master has authenticated and the
temporary metadata row and local SSH identity have both been removed.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import email.utils
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    from scripts import provider_key_transfer as sender
    from scripts.gcp_instance_ssh_guard import Conflict, InstanceKeyGuard, UncertainUpdate, make_entry
    from scripts.provider_iap_session_ledger import SenderSessionLedger
except ModuleNotFoundError:
    import provider_key_transfer as sender
    from gcp_instance_ssh_guard import Conflict, InstanceKeyGuard, UncertainUpdate, make_entry
    from provider_iap_session_ledger import SenderSessionLedger


class SessionError(RuntimeError):
    """A provider transfer or its temporary access cleanup was not confirmed."""

    def __init__(self, message, *, metadata_cleanup_uncertain=False, identity_cleanup_uncertain=False,
                 tunnel_cleanup_uncertain=False):
        super().__init__(message)
        self.metadata_cleanup_uncertain = metadata_cleanup_uncertain
        self.identity_cleanup_uncertain = identity_cleanup_uncertain
        self.tunnel_cleanup_uncertain = tunnel_cleanup_uncertain


class TunnelCleanupError(SessionError):
    """The owned IAP process group could not be confirmed terminated."""


class IdentityCleanupError(SessionError):
    """The exact owned temporary private key inode could not be removed."""


class MetadataCleanupError(SessionError):
    """The GCE metadata request or the owned row cleanup is uncertain."""


@contextmanager
def _handle_sigterm():
    """Convert a normal stop request into unwinding on the main thread only."""
    if threading.current_thread() is not threading.main_thread():
        raise SessionError('IAP session must run on the main thread')
    previous = signal.getsignal(signal.SIGTERM)
    interrupted = False

    def stop(_signum, _frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


PROJECT = 'gen-lang-client-0308507618'
ZONE = 'us-central1-c'
INSTANCE = 'asb-free-test'
INSTANCE_ID = '1428786032988053776'
SSH_USER = 'jmac'
PRODUCTION_JOURNAL_DIR = '/Users/jmac/.codex/provider-iap-session'
_BASE = f'https://compute.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances/{INSTANCE}'
_GCLOUD = '/opt/homebrew/bin/gcloud'
_MAX_CLOCK_SKEW_SECONDS = 15
_MAX_CLOCK_REQUEST_SECONDS = 10
# Previous-session and completed-operation reconciliation is not yet wired.
# The isolated test dependency path cannot authorize actual GCE access.


def _verify_server_clock(headers, *, wall_before, wall_after, monotonic_before, monotonic_after):
    """Bound local-vs-authenticated-GCE time with RTT and one-second Date precision."""
    try:
        if (not isinstance(headers, list) or len(headers) != 1 or not isinstance(headers[0], str)
                or not re.fullmatch(r'[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} '
                                    r'[0-9]{2}:[0-9]{2}:[0-9]{2} GMT', headers[0])):
            raise ValueError()
        values = (wall_before, wall_after, monotonic_before, monotonic_after)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError()
        elapsed = monotonic_after - monotonic_before
        if (elapsed < 0 or elapsed > _MAX_CLOCK_REQUEST_SECONDS or wall_after < wall_before
                or abs((wall_after - wall_before) - elapsed) > .5):
            raise ValueError()
        parsed = email.utils.parsedate_to_datetime(headers[0])
        if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
            raise ValueError()
        server = parsed.timestamp()
        # The Date header has one-second resolution and can have been made at
        # any time during the request; bound the worst case, not its midpoint.
        worst_skew = max(abs(server - wall_after), abs((server + 1) - wall_before))
        if worst_skew > _MAX_CLOCK_SKEW_SECONDS:
            raise ValueError()
    except Exception:
        raise SessionError('Authenticated GCE clock could not be verified') from None


class GceInstanceTransport:
    """Only the exact target instance; metadata is never logged or returned."""

    def __init__(self, *, env, ledger, session_id, entry):
        self.env, self.ledger, self.session_id, self.entry = env, ledger, session_id, entry

    def _request(self, url, *, method='GET', payload=None, require_clock=False):
        try:
            result = subprocess.run([_GCLOUD, 'auth', 'print-access-token', '--quiet'], env=self.env,
                                    check=True, capture_output=True, timeout=20)
            token = result.stdout.decode('ascii').strip()
            if not token or '\n' in token:
                raise ValueError()
            data = None if payload is None else json.dumps(payload).encode()
            request = urllib.request.Request(url, data=data, method=method,
                                             headers={'Authorization': 'Bearer ' + token,
                                                      'Content-Type': 'application/json',
                                                      'Accept-Encoding': 'identity'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            wall_before, monotonic_before = time.time(), time.monotonic()
            with opener.open(request, timeout=20) as response:
                date_headers = response.headers.get_all('Date') if require_clock else None
                if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                    raise ValueError()
                payload = response.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError()
            if require_clock:
                _verify_server_clock(date_headers, wall_before=wall_before, wall_after=time.time(),
                                     monotonic_before=monotonic_before, monotonic_after=time.monotonic())
            return json.loads(payload)
        except urllib.error.HTTPError:
            raise
        except Exception:
            raise SessionError('GCE request could not be confirmed') from None

    def verify_target(self):
        try:
            item = self._request(_BASE, require_clock=True)
            if (not isinstance(item, dict) or str(item.get('id')) != INSTANCE_ID
                    or item.get('name') != INSTANCE or item.get('status') != 'RUNNING'):
                raise ValueError()
        except Exception:
            raise SessionError('GCE instance identity could not be confirmed') from None

    def read(self):
        try:
            item = self._request(_BASE)
            if str(item.get('id')) != INSTANCE_ID or item.get('name') != INSTANCE:
                raise ValueError()
            metadata = item.get('metadata')
            if not isinstance(metadata, dict):
                raise ValueError()
            return metadata
        except Exception:
            raise SessionError('GCE instance metadata could not be read') from None

    def compare_and_set(self, metadata):
        try:
            # Refuse a metadata write if the authenticated GCE clock and local
            # clock no longer agree. This check occurs before journal/POST.
            self.verify_target()
            if not isinstance(metadata, dict) or not isinstance(metadata.get('items', []), list):
                raise ValueError()
            ssh_items = [item for item in metadata.get('items', [])
                         if isinstance(item, dict) and item.get('key') == 'ssh-keys']
            if len(ssh_items) > 1 or (ssh_items and not isinstance(ssh_items[0].get('value'), str)):
                raise ValueError()
            lines = ssh_items[0]['value'].splitlines() if ssh_items else []
            count = sum(line == self.entry for line in lines)
            if count not in (0, 1):
                raise ValueError()
            operation_id, request_id = self.ledger.begin_operation(
                self.session_id, self.entry, metadata_fingerprint=metadata.get('fingerprint'),
                action='insert' if count else 'remove')
        except Exception:
            raise SessionError('GCE clock, metadata or journal preflight is unavailable') from None
        try:
            operation = self._request(_BASE + '/setMetadata?requestId=' + request_id,
                                      method='POST', payload=metadata)
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                try:
                    self.ledger.finish_operation(operation_id, self.session_id, 'rejected')
                except Exception:
                    raise UncertainUpdate('GCE rejection could not be recorded') from None
                raise Conflict('GCE metadata changed') from None
            raise UncertainUpdate('GCE metadata outcome is unknown') from None
        except BaseException:
            raise UncertainUpdate('GCE metadata outcome is unknown') from None
        try:
            name = operation['name']
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name):
                raise ValueError()
            self.ledger.record_operation(operation_id, self.session_id, name)
            url = f'https://compute.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}/operations/{name}'
            for _ in range(40):
                result = self._request(url)
                if result.get('name') != name:
                    raise ValueError()
                if result.get('status') == 'DONE':
                    if result.get('error'):
                        raise ValueError()
                    self.ledger.finish_operation(operation_id, self.session_id, 'applied')
                    return
                if result.get('status') not in ('PENDING', 'RUNNING'):
                    raise ValueError()
                time.sleep(.5)
        except BaseException:
            raise UncertainUpdate('GCE metadata completion is unconfirmed') from None
        raise UncertainUpdate('GCE metadata completion is unconfirmed')


class GceInfrastructure:
    def __init__(self, config_dir='/tmp/asb-owner-session'):
        if not isinstance(config_dir, str) or not os.path.isabs(config_dir):
            raise ValueError('GCE configuration path must be absolute')
        self.env = dict(os.environ, CLOUDSDK_CONFIG=config_dir, CLOUDSDK_CORE_DISABLE_FILE_LOGGING='true')

    def identity(self, directory):
        path = Path(directory) / 'identity'
        try:
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(path)],
                           check=True, capture_output=True, timeout=20)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077 or info.st_nlink != 1):
                    raise ValueError()
                identity = (info.st_dev, info.st_ino)
            finally:
                os.close(fd)
            public_fd = os.open(path.with_suffix('.pub'), os.O_RDONLY | os.O_NOFOLLOW)
            try:
                public_info = os.fstat(public_fd)
                if (not stat.S_ISREG(public_info.st_mode) or public_info.st_uid != os.geteuid()
                        or public_info.st_nlink != 1 or public_info.st_size > 8192):
                    raise ValueError()
                public_raw = os.read(public_fd, 8193)
                after = os.fstat(public_fd)
                if (len(public_raw) != public_info.st_size
                        or any(getattr(public_info, field) != getattr(after, field) for field in
                               ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
                    raise ValueError()
                parts = public_raw.decode('ascii').split()
            finally:
                os.close(public_fd)
            if len(parts) < 2:
                raise ValueError()
            return path, identity, ' '.join(parts[:2])
        except Exception:
            raise SessionError('Temporary SSH identity could not be created') from None

    def transport(self, ledger, session_id, entry):
        return GceInstanceTransport(env=self.env, ledger=ledger, session_id=session_id, entry=entry)

    @contextmanager
    def tunnel(self):
        sock = socket.socket()
        try:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        finally:
            sock.close()
        command = [_GCLOUD, 'compute', 'start-iap-tunnel', INSTANCE, '22', f'--project={PROJECT}',
                   f'--zone={ZONE}', f'--local-host-port=127.0.0.1:{port}',
                   '--iap-tunnel-disable-connection-check', '--quiet', '--verbosity=error']
        process = None
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       env=self.env, start_new_session=True)
            for _ in range(80):
                if process.poll() is not None:
                    raise SessionError('IAP tunnel exited')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.25):
                        break
                except OSError:
                    time.sleep(.25)
            else:
                raise SessionError('IAP tunnel did not become available')
            yield port
        finally:
            if process is not None:
                try:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                        raise TunnelCleanupError('IAP tunnel cleanup is unconfirmed')
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                        try:
                            os.killpg(process.pid, 0)
                        except ProcessLookupError:
                            pass
                        else:
                            raise TunnelCleanupError('IAP tunnel cleanup is unconfirmed')
                    except Exception:
                        raise TunnelCleanupError('IAP tunnel cleanup is unconfirmed') from None
                except Exception:
                    raise TunnelCleanupError('IAP tunnel cleanup is unconfirmed') from None


def _remove_identity(path, identity):
    """Delete only the same owned private inode and fsync its private parent."""
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or (info.st_dev, info.st_ino) != identity):
            raise ValueError()
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != identity:
                raise ValueError()
            os.unlink(path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise ValueError()
        finally:
            os.close(parent_fd)
    except Exception:
        raise IdentityCleanupError('Temporary SSH identity cleanup is unconfirmed') from None


def _audit_legacy_sessions(infrastructure):
    """Check journal ownership against GCE before any new session is opened."""
    try:
        from scripts.provider_iap_legacy_audit import audit_owned_legacy_journals
        from scripts.provider_iap_reconcile import GceReadOnly
    except ModuleNotFoundError:
        from provider_iap_legacy_audit import audit_owned_legacy_journals
        from provider_iap_reconcile import GceReadOnly
    identity = subprocess.run(
        [_GCLOUD, 'auth', 'list', '--filter=status:ACTIVE', '--format=value(account)', '--quiet'],
        env=infrastructure.env, capture_output=True, text=True, timeout=15, check=True,
    ).stdout.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+', identity):
        raise SessionError('Authenticated Google Cloud operator is unavailable')
    return audit_owned_legacy_journals(client=GceReadOnly(env=infrastructure.env), operator=identity)


def transfer_via_iap(*, transaction_id, receiver_source, receiver_sha256, known_hosts_file,
                     journal_dir, execute=False, recover=False, _infrastructure=None,
                     _sender=None):
    """Run the concrete sender only after explicit opt-in and verified cleanup.

    The leading-underscore dependencies are solely for isolated unit tests.
    A successful key transfer does not deploy, start, or verify the API.
    """
    if execute is not True:
        raise SessionError('Transfer session is disabled until explicitly executed')
    live_infrastructure = _infrastructure is None or isinstance(_infrastructure, GceInfrastructure)
    if live_infrastructure and (journal_dir != PRODUCTION_JOURNAL_DIR or _sender is not None):
        raise SessionError('Live IAP session configuration is invalid')
    if (not isinstance(transaction_id, str) or not re.fullmatch(r'[0-9a-f]{32}', transaction_id)
            or not isinstance(receiver_source, bytes) or len(receiver_source) > 128 * 1024
            or not isinstance(receiver_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', receiver_sha256)
            or hashlib.sha256(receiver_source).hexdigest() != receiver_sha256 or type(recover) is not bool):
        raise SessionError('Transfer session configuration is invalid')
    infrastructure = _infrastructure or GceInfrastructure()
    transfer = _sender or sender.transfer
    receipt = None
    guard = None
    identity = None
    identity_path = None
    identity_removed = False
    metadata_removed = False
    metadata_uncertain = False
    identity_uncertain = False
    tunnel_uncertain = False
    tunnel_closed = False
    failure = False
    result = None
    try:
        sender._known_hosts(known_hosts_file)
        with _handle_sigterm(), SenderSessionLedger(journal_dir) as ledger, tempfile.TemporaryDirectory(prefix='asb-iap-sender-', dir='/tmp') as directory:
            ledger.assert_quiescent()
            if live_infrastructure:
                _audit_legacy_sessions(infrastructure)
            session_id = ledger.begin_session(str(Path(directory).resolve()))
            try:
                directory = str(Path(directory).resolve())
                identity_path, identity, public = infrastructure.identity(directory)
                transport = infrastructure.transport(ledger, session_id, '')
                transport.verify_target()
                # With a maximum 15-second verified skew, a 4m30s local
                # lifetime remains below five minutes on the GCE clock.
                entry = make_entry(SSH_USER, public, now=dt.datetime.now(dt.timezone.utc),
                                   lifetime=dt.timedelta(minutes=4, seconds=30))
                transport.entry = entry
                guard = InstanceKeyGuard(transport)
                with infrastructure.tunnel() as port:
                    try:
                        try:
                            receipt = guard.insert(entry)
                        except UncertainUpdate:
                            metadata_uncertain = True
                            raise

                        def on_master_ready():
                            nonlocal receipt, identity_removed, metadata_removed, metadata_uncertain
                            try:
                                guard.remove(entry, receipt)
                                receipt = None
                                metadata_removed = True
                                _remove_identity(identity_path, identity)
                                identity_removed = True
                                return True
                            except BaseException:
                                # A failed remove may have reached the daemon; never
                                # infer completion from a later empty observation.
                                metadata_uncertain = not metadata_removed
                                return False

                        result = transfer(port=port, instance_id=INSTANCE_ID, transaction_id=transaction_id,
                                          receiver_source=receiver_source, receiver_sha256=receiver_sha256,
                                          known_hosts_file=known_hosts_file, identity_file=str(identity_path),
                                          on_master_ready=on_master_ready, recover=recover)
                        expected = {'KEY_FILE_PRESENT', 'TRANSFER_CANCELLED'} if recover else {'KEY_FILE_INSTALLED'}
                        if (not metadata_removed or not identity_removed or not isinstance(result, dict)
                                or set(result) != {'status', 'recovery_required'} or result.get('status') not in expected
                                or result.get('recovery_required') is not False):
                            raise SessionError('Temporary access cleanup was not confirmed')
                    except BaseException:
                        # Let the tunnel context finish before deciding if this
                        # session can be durably closed.
                        failure = True
                tunnel_closed = True
            finally:
                # Cleanup must run while the journal descriptor and private
                # temporary directory are still open, even on interruption.
                if guard is not None:
                    pending = receipt or guard._pending
                    if pending is not None:
                        try:
                            guard.remove(entry, pending)
                            if not metadata_uncertain:
                                metadata_removed = True
                        except BaseException:
                            metadata_uncertain = True
                if identity_path is not None and not identity_removed:
                    try:
                        _remove_identity(identity_path, identity)
                        identity_removed = True
                    except BaseException:
                        identity_uncertain = True
                        failure = True
                if metadata_removed and identity_removed and tunnel_closed and not metadata_uncertain:
                    try:
                        ledger.close_session(session_id, metadata_removed=True, identity_removed=True, tunnel_closed=True)
                    except BaseException:
                        failure = True
    except TunnelCleanupError:
        tunnel_uncertain = True
        failure = True
    except BaseException:
        failure = True
    flags = {'metadata_cleanup_uncertain': metadata_uncertain, 'identity_cleanup_uncertain': identity_uncertain,
             'tunnel_cleanup_uncertain': tunnel_uncertain}
    if metadata_uncertain:
        raise MetadataCleanupError('Temporary GCE metadata cleanup is unconfirmed; inspect the recovery journal',
                                   **flags) from None
    if identity_uncertain:
        raise IdentityCleanupError('Temporary SSH identity cleanup is unconfirmed', **flags) from None
    if tunnel_uncertain:
        raise TunnelCleanupError('IAP tunnel cleanup is unconfirmed; remote transaction may require recovery',
                                 **flags) from None
    if failure:
        raise SessionError('IAP transfer was not confirmed; the remote transaction may require recovery') from None
    return result
