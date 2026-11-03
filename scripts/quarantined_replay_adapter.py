"""Prepare a real-data replay without bypassing the synthetic replay guard.

The currently available witness verifies only a prefix, not a latest head.
Consequently this adapter never runs the mutation replayer or releases a
restored system. A separately authenticated latest watermark and a reviewed
production-target replay implementation are still required.
"""
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from independent_journal_evidence import _verified_witnessed_scan
from narration_deploy_safety import _private_directory
from quarantined_backup_ingest import _dispose_owned, _local_daemon, _remaining, _verify_sandbox
from src.services.privacy_journal_verify import fingerprint_entries


class QuarantinedReplayError(RuntimeError):
    pass


def _evaluate(factory, container_id, token, *, timeout):
    resources = []
    try:
        arguments = factory()
        if not isinstance(arguments, dict):
            raise ValueError('invalid witness inputs')
        journal = arguments.get('journal')
        resources = [getattr(journal, '_store', None), arguments.get('head_store'), arguments.get('checkpoint_store')]
        # An authenticated prefix is insufficient: the backup's matched
        # events must themselves fall inside the signed checkpoint.
        scan = _verified_witnessed_scan(require_full_coverage=True, **arguments)
        result = subprocess.run(['docker', 'exec', '-u', '65534:65534',
                                 '-e', 'ASB_QUARANTINE_RESTORE=1', container_id,
                                 '/opt/venv/bin/python', '/offline/scripts/quarantined_replay_preflight.py', token],
                                capture_output=True, timeout=timeout)
        expected = {'status': 'RESTORED_TARGET_MATCHES_BACKUP_QUARANTINED',
                    'latest_journal_verified': False, 'privacy_replay_authorized': False,
                    'restore_authorized': False}
        if result.returncode != 0 or json.loads(result.stdout) != expected:
            raise ValueError('target is not verified')
        binding_result = subprocess.run(['docker', 'exec', '-u', '65534:65534',
                                 '-e', 'ASB_QUARANTINE_RESTORE=1', container_id,
                                 '/opt/venv/bin/python', '/offline/scripts/quarantined_outbox_binding.py', token],
                                capture_output=True, timeout=timeout)
        if binding_result.returncode != 0 or len(binding_result.stdout) > 4 * 1024 * 1024:
            raise ValueError('backup journal checkpoint is unverified')
        binding = json.loads(binding_result.stdout)
        if (not isinstance(binding, dict) or set(binding) != {'status', 'event_ids', 'journal_sha256', 'restore_authorized'}
                or binding['status'] != 'BACKUP_OUTBOX_CHECKPOINT_MATCHES'
                or binding['restore_authorized'] is not False or not isinstance(binding['event_ids'], list)
                or len(binding['event_ids']) > 100000
                or any(not isinstance(x, str) or not re.fullmatch('[0-9a-f]{32}', x) for x in binding['event_ids'])
                or len(set(binding['event_ids'])) != len(binding['event_ids'])
                or not isinstance(binding['journal_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', binding['journal_sha256'])):
            raise ValueError('backup journal checkpoint is invalid')
        ids = set(binding['event_ids'])
        matched = tuple(event for event in scan.committed if event.event_id in ids)
        if len(matched) != len(ids) or fingerprint_entries(matched) != binding['journal_sha256']:
            raise ValueError('witnessed journal does not contain the backup checkpoint')
        return True
    finally:
        seen = set()
        for resource in resources:
            if resource is not None and id(resource) not in seen:
                seen.add(id(resource))
                try:
                    close = getattr(resource, 'close', None)
                    if close is not None:
                        close()
                except Exception:
                    pass


def _worker(pipe, factory, container_id, token):
    try:
        pipe.send(_evaluate(factory, container_id, token, timeout=300))
    except BaseException:
        try:
            pipe.send(False)
        except Exception:
            pass
    finally:
        pipe.close()


def prepare_isolated_replay_direct(*, witness_factory, container_id, image_id, token,
                                   lock_dir, timeout_seconds=600):
    """Direct worker form: call only inside a separately killable process."""
    if (not callable(witness_factory) or not isinstance(container_id, str)
            or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900):
        raise QuarantinedReplayError('Replay preflight configuration is invalid')
    deadline = time.monotonic() + timeout_seconds
    _local_daemon(deadline)
    lock_path = _private_directory(Path(lock_dir)) / ('ingest-' + token + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QuarantinedReplayError('Sandbox operation is already active') from None
        completed = False
        try:
            _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
            _evaluate(witness_factory, container_id, token, timeout=max(1, deadline - time.monotonic()))
            _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
            completed = True
            return {'status': 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN',
                    'target_verified_at_preflight': True, 'privacy_replay_applied': False,
                    'restore_authorized': False, 'service_publish_authorized': False}
        finally:
            if not completed and not _dispose_owned(container_id, image_id, token):
                raise QuarantinedReplayError('Preflight failed; owned sandbox cleanup could not be verified') from None
    finally:
        os.close(fd)


def prepare_isolated_replay(*, witness_factory, container_id, image_id, token, lock_dir, timeout_seconds=600):
    """Verify target and witness prefix, then explicitly block replay/publish.

    The factory creates fresh read-only witness clients inside a killable child
    process. Its result and all user data stay in that process; no object names,
    personal data or credentials are returned or logged.
    """
    if (not callable(witness_factory) or threading.active_count() != 1
            or not isinstance(container_id, str) or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900):
        raise QuarantinedReplayError('Replay preflight configuration is invalid')
    deadline = time.monotonic() + timeout_seconds
    _local_daemon(deadline)
    lock_path = _private_directory(Path(lock_dir)) / ('ingest-' + token + '.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QuarantinedReplayError('Sandbox operation is already active') from None
        process = None
        parent = None
        child = None
        completed = False
        try:
            _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
            parent, child = multiprocessing.get_context('fork').Pipe(duplex=False)
            process = multiprocessing.get_context('fork').Process(target=_worker,
                args=(child, witness_factory, container_id, token))
            process.start()
            child.close()
            ok = parent.poll(max(0, deadline - time.monotonic())) and parent.recv() is True
            if ok:
                process.join(max(0, min(10, deadline - time.monotonic())))
                ok = not process.is_alive() and process.exitcode == 0
            if ok and deadline > time.monotonic():
                _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
                completed = True
                return {'status': 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN',
                        'target_verified_at_preflight': True, 'privacy_replay_applied': False,
                        'restore_authorized': False, 'service_publish_authorized': False}
        finally:
            if parent is not None:
                parent.close()
            if child is not None:
                child.close()
            if process is not None and process.is_alive():
                process.terminate()
                process.join(5)
                if process.is_alive():
                    process.kill()
                    process.join(5)
            if not completed and not _dispose_owned(container_id, image_id, token):
                raise QuarantinedReplayError('Preflight failed; owned sandbox cleanup could not be verified') from None
        raise QuarantinedReplayError('Replay preflight failed; the owned sandbox was removed')
    finally:
        os.close(fd)
