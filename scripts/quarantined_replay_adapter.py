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
from replay_privacy_journal import encode_replay_transfer
from src.services.privacy_journal_verify import fingerprint_entries


class QuarantinedReplayError(RuntimeError):
    pass


def _evaluate(factory, container_id, token, *, timeout, live_journal_binding=None, require_exact_backup=False,
              apply_legacy_public_url=None):
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
        if live_journal_binding is not None and (
                len(scan.committed), fingerprint_entries(scan.committed)) != live_journal_binding:
            raise ValueError('Witnessed history differs from the fenced live source')
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
        if require_exact_backup and (live_journal_binding is None or len(ids) != len(scan.committed)):
            raise ValueError('Restored backup requires newer privacy events to be reapplied')
        later_count = len(scan.committed) - len(ids)
        if apply_legacy_public_url is not None:
            if live_journal_binding is None or require_exact_backup:
                raise ValueError('Live source binding is required before isolated replay')
            transfer = encode_replay_transfer(scan, live_journal_binding[1], apply_legacy_public_url)
            if len(transfer) > 32 * 1024 * 1024:
                raise ValueError('Replay transfer exceeds its limit')
            replay = subprocess.run(['docker', 'exec', '-i', '-u', '65534:65534',
                                     '-e', 'ASB_QUARANTINE_RESTORE=1', container_id,
                                     '/opt/venv/bin/python', '/offline/scripts/quarantined_replay_preflight.py',
                                     '--apply', token], input=transfer, capture_output=True, timeout=timeout)
            if replay.returncode or json.loads(replay.stdout) != {
                'status': 'REPLAYED_STILL_QUARANTINED', 'applied_count': later_count, 'restore_authorized': False,
            }:
                raise ValueError('Isolated replay did not complete')
        # Keep the authenticated replay plan in this process. The parent
        # receives no event payloads or credentials.
        return {'backup_event_count': len(ids), 'later_event_count': later_count}
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


def _worker(pipe, factory, container_id, token, live_journal_binding, require_exact_backup):
    try:
        pipe.send(_evaluate(factory, container_id, token, timeout=300, live_journal_binding=live_journal_binding,
                            require_exact_backup=require_exact_backup))
    except BaseException:
        try:
            pipe.send(False)
        except Exception:
            pass
    finally:
        pipe.close()


def prepare_isolated_replay_direct(*, witness_factory, container_id, image_id, token,
                                   lock_dir, timeout_seconds=600, live_journal_binding=None,
                                   require_exact_backup=False, apply_legacy_public_url=None):
    """Direct worker form: call only inside a separately killable process."""
    if (not callable(witness_factory) or not isinstance(container_id, str)
            or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900
            or type(require_exact_backup) is not bool):
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
            counts = _evaluate(witness_factory, container_id, token, timeout=_remaining(deadline),
                               live_journal_binding=live_journal_binding, require_exact_backup=require_exact_backup,
                               apply_legacy_public_url=apply_legacy_public_url)
            _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
            completed = True
            return {'status': ('RESTORED_OUTBOX_MATCHES_FENCED_LIVE_HISTORY' if require_exact_backup
                               else 'REPLAYED_STILL_QUARANTINED' if apply_legacy_public_url is not None
                               else 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN'),
                    'target_verified_at_preflight': True, 'privacy_replay_applied': apply_legacy_public_url is not None,
                    'restore_authorized': False, 'service_publish_authorized': False, **counts}
        finally:
            if not completed and not _dispose_owned(container_id, image_id, token):
                raise QuarantinedReplayError('Preflight failed; owned sandbox cleanup could not be verified') from None
    finally:
        os.close(fd)


def prepare_isolated_replay(*, witness_factory, container_id, image_id, token, lock_dir, timeout_seconds=600,
                             live_journal_binding=None, require_exact_backup=False):
    """Verify target and witnessed history without applying events or publishing.

    The factory creates fresh read-only witness clients inside a killable child
    process. Its result and all user data stay in that process; no object names,
    personal data or credentials are returned or logged. Exact matching also
    requires a binding obtained while the caller holds the live source fence.
    """
    if (not callable(witness_factory) or threading.active_count() != 1
            or not isinstance(container_id, str) or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900
            or type(require_exact_backup) is not bool):
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
                args=(child, witness_factory, container_id, token, live_journal_binding, require_exact_backup))
            process.start()
            child.close()
            counts = parent.recv() if parent.poll(max(0, deadline - time.monotonic())) else None
            ok = (isinstance(counts, dict) and set(counts) == {'backup_event_count', 'later_event_count'}
                  and all(type(count) is int and 0 <= count <= 100000 for count in counts.values()))
            if ok:
                process.join(max(0, min(10, deadline - time.monotonic())))
                ok = not process.is_alive() and process.exitcode == 0
            if ok and deadline > time.monotonic():
                _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
                completed = True
                return {'status': ('RESTORED_OUTBOX_MATCHES_FENCED_LIVE_HISTORY' if require_exact_backup
                                   else 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN'),
                        'target_verified_at_preflight': True, 'privacy_replay_applied': False,
                        'restore_authorized': False, 'service_publish_authorized': False, **counts}
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
