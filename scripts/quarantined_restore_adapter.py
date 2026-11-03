"""Restore a quarantined backup into its owned network-none tmpfs sandbox.

This does not apply later privacy events, prove independent latest history, or
authorize publishing a restored service. Failures destroy only the verified
owned sandbox; no production target is ever selected by this adapter.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time

from narration_deploy_safety import _private_directory
from quarantined_backup_ingest import _dispose_owned, _local_daemon, _remaining, _verify_sandbox


class QuarantinedRestoreError(RuntimeError):
    pass


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
