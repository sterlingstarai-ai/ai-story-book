"""Restore a quarantined backup into its owned network-none tmpfs sandbox.

This does not apply later privacy events, prove independent latest history, or
authorize publishing a restored service. Failures destroy only the verified
owned sandbox; no production target is ever selected by this adapter.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time

from narration_deploy_safety import _private_directory
from quarantined_backup_ingest import _dispose_owned, _local_daemon, _remaining, _verify_sandbox


class QuarantinedRestoreError(RuntimeError):
    pass


@contextmanager
def open_restore_sandbox(*, image_id, state_dir, timeout_seconds=300):
    """Create and verify a disposable, networkless restore target on this host."""
    if (not isinstance(image_id, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900):
        raise QuarantinedRestoreError('Pinned restore image and deadline are required')
    _local_daemon(time.monotonic() + 20)
    state = _private_directory(Path(state_dir))
    token = secrets.token_hex(16)
    name = 'asb-quarantined-restore-' + token
    tmpfs = 'rw,nosuid,nodev,noexec,uid=65534,gid=65534,mode=0700'
    identifier = None
    with tempfile.TemporaryDirectory(dir=state, prefix='restore-lock-') as lock_dir:
        try:
            result = subprocess.run(['docker', 'run', '-d', '--rm', '--pull=never', '--name', name,
                '--network', 'none', '--read-only', '--user', '65534:65534',
                '--tmpfs', f'/tmp:{tmpfs},size=64m', '--tmpfs', f'/var/lib/asb-restore:{tmpfs},size=512m',
                '--tmpfs', f'/var/lib/postgresql/data:{tmpfs},size=8m', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--pids-limit', '128', '--memory', '1g',
                '--memory-swap', '1g', '--log-driver', 'none', '--label', 'asb.restore.purpose=offline-candidate',
                '--label', 'asb.restore.token=' + token, '--entrypoint', '/bin/sleep', image_id, '1800'],
                capture_output=True, timeout=60, check=True)
            candidate = result.stdout.decode('ascii').strip()
            if not re.fullmatch('[0-9a-f]{64}', candidate):
                raise QuarantinedRestoreError('Restore container identity is unavailable')
            identifier = candidate
            _verify_sandbox(identifier, image_id, token)
            probe = "import sys; sys.path[:0]=['/offline/scripts','/offline/apps/api']; import quarantined_outbox_binding"
            ready = subprocess.run(['docker', 'exec', '-u', '65534:65534', identifier, '/opt/venv/bin/python',
                                    '-c', probe], capture_output=True, timeout=20)
            if ready.returncode:
                raise QuarantinedRestoreError('Isolated restore image is not usable')
            yield {'container_id': identifier, 'image_id': image_id, 'token': token,
                   'lock_dir': Path(lock_dir), 'timeout_seconds': timeout_seconds}
        finally:
            if identifier is None:
                # A lost Docker response may still have started the container.
                listing = subprocess.run(['docker', 'ps', '-aq', '--no-trunc', '--filter',
                    f'name=^/{name}$', '--filter', f'label=asb.restore.token={token}'],
                    capture_output=True, timeout=20, check=True)
                identifier = listing.stdout.decode('ascii').strip()
                if identifier and not re.fullmatch('[0-9a-f]{64}', identifier):
                    raise QuarantinedRestoreError('Restore container cleanup is indeterminate')
            if identifier and not _dispose_owned(identifier, image_id, token):
                raise QuarantinedRestoreError('Owned restore container cleanup is unverified')


def restore_in_owned_sandbox(*, container_id, image_id, token, lock_dir, timeout_seconds=600):
    """Run the fixed internal restore helper; retain quarantine on success."""
    if (not isinstance(container_id, str) or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900):
        raise QuarantinedRestoreError('Restore sandbox identity or deadline is invalid')
    deadline = time.monotonic() + timeout_seconds
    _local_daemon(deadline)
    lock_path = _private_directory(Path(lock_dir)) / ('ingest-' + token + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QuarantinedRestoreError('Sandbox operation is already active') from None
        succeeded = False
        try:
            _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise QuarantinedRestoreError('Restore deadline expired')
            result = subprocess.run(['docker', 'exec', '-u', '65534:65534',
                                     '-e', 'ASB_QUARANTINE_RESTORE=1', container_id,
                                     '/opt/venv/bin/python', '/offline/scripts/quarantined_restore_runtime.py', token],
                                    capture_output=True, timeout=remaining)
            if result.returncode != 0 or json.loads(result.stdout) != {
                    'status': 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED',
                    'privacy_replay_verified': False, 'restore_authorized': False}:
                raise QuarantinedRestoreError('Quarantined restore did not complete')
            _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
            succeeded = True
            return {'status': 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED',
                    'privacy_replay_verified': False, 'restore_authorized': False,
                    'service_publish_authorized': False}
        finally:
            if not succeeded and not _dispose_owned(container_id, image_id, token):
                raise QuarantinedRestoreError('Restore failed; owned sandbox cleanup could not be verified') from None
    finally:
        os.close(fd)
