"""Stream a pinned remote backup into an isolated tmpfs quarantine sandbox.

No local backup file is created. This adapter does not prove that the supplied
manifest hash is authentic or current, replay privacy events, restore a DB, or
authorize reopening a service. Only an owned, empty sandbox may be used.
"""
import hashlib
import hmac
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from check_restore_sandbox import assess
from narration_deploy_safety import _private_directory
from publish_backup_gcs import GCSBackupStore


class QuarantinedIngestError(RuntimeError):
    pass


MAX_TOTAL = 384 * 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
MAX_OBJECTS = 10000


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise QuarantinedIngestError('Ingest deadline expired')
    return min(value, 20)


def _local_daemon(deadline):
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise QuarantinedIngestError('Explicit Docker host or context is not allowed')
    result = subprocess.run(['docker', 'context', 'inspect'], capture_output=True,
                            timeout=_remaining(deadline), check=True)
    context = json.loads(result.stdout)
    endpoint = context[0]['Endpoints']['docker']['Host']
    if not isinstance(endpoint, str) or not endpoint.startswith('unix://'):
        raise QuarantinedIngestError('A local Docker daemon is required')


def _inspect(identifier, *, timeout=20):
    result = subprocess.run(['docker', 'inspect', identifier], capture_output=True, timeout=timeout, check=True)
    raw = json.loads(result.stdout)
    if not isinstance(raw, list) or len(raw) != 1:
        raise QuarantinedIngestError('Sandbox identity cannot be inspected')
    return raw[0]


def _verify_sandbox(identifier, image_id, token, *, timeout=20):
    item = _inspect(identifier, timeout=timeout)
    outcome = assess(item, container_id=identifier, image_id=image_id, token=token)
    if outcome != {'status': 'SANDBOX_CONFIGURATION_MATCHES', 'restore_authorized': False}:
        raise QuarantinedIngestError('Sandbox isolation cannot be verified')
    return item


def _ensure_empty(identifier, *, timeout=20):
    code = "from pathlib import Path; import sys; p=Path('/var/lib/asb-restore'); sys.exit(not p.is_dir() or any(p.iterdir()))"
    result = subprocess.run(['docker', 'exec', '-u', '65534:65534', identifier,
                             '/opt/venv/bin/python', '-c', code], capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise QuarantinedIngestError('An empty owned sandbox is required')


def _dispose_owned(identifier, image_id, token):
    try:
        try:
            item = _inspect(identifier)
        except subprocess.CalledProcessError:
            # A prior cleanup may already have removed it. Only accept absence
            # after a successful daemon-wide exact-ID listing.
            listing = subprocess.run(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}'],
                                     capture_output=True, check=True, timeout=20)
            return identifier not in listing.stdout.decode().splitlines()
        labels = item.get('Config', {}).get('Labels') or {}
        if (item.get('Id') != identifier or item.get('Image') != image_id
                or labels.get('asb.restore.purpose') != 'offline-candidate'
                or labels.get('asb.restore.token') != token):
            return False
        result = subprocess.run(['docker', 'rm', '-f', identifier], capture_output=True, timeout=30)
        return result.returncode == 0
    except Exception:
        return False


def _frame(stream, value):
    stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n')


def _worker(pipe, bucket, token_provider, run_id, expected_manifest_hash, expected_revision,
            identifier, token, capacity):
    """Run in a killable child so one deadline covers provider and pipe I/O."""
    store = None
    process = None
    try:
        store = GCSBackupStore(bucket, token_provider)
        prefix = 'backups/v1/' + run_id + '/'
        marker_before = store.read_small(prefix + 'verified.json', 4096)
        manifest = store.read_small(prefix + 'manifest.json', MAX_MANIFEST)
        digest = hashlib.sha256(manifest).hexdigest()
        marker = json.loads(marker_before)
        if (not hmac.compare_digest(digest, expected_manifest_hash) or not isinstance(marker, dict)
                or type(marker.get('version')) is not int or marker['version'] != 1
                or marker.get('restore_authorized') is not False or marker.get('manifest_sha256') != digest):
            raise QuarantinedIngestError('Backup manifest identity differs')
        parsed = json.loads(manifest)
        if (not isinstance(parsed, dict) or type(parsed.get('format_version')) is not int
                or parsed['format_version'] != 1 or parsed.get('database_scope') != 'public'
                or parsed.get('requires_latest_deletion_and_identity_revocations') is not True
                or parsed.get('alembic_revision') != expected_revision):
            raise QuarantinedIngestError('Backup manifest is invalid')
        objects = parsed.get('objects') if isinstance(parsed, dict) else None
        if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
            raise QuarantinedIngestError('Backup inventory is invalid')
        descriptors = [parsed.get('database'), *objects]
        total = len(manifest) + len(marker_before)
        names = set()
        for index, descriptor in enumerate(descriptors):
            if not isinstance(descriptor, dict):
                raise QuarantinedIngestError('Backup inventory is invalid')
            if index == 0:
                expected_name = 'database.dump'
            else:
                key = descriptor.get('key')
                if not isinstance(key, str) or not key:
                    raise QuarantinedIngestError('Backup inventory is invalid')
                expected_name = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
            size, value = descriptor.get('size'), descriptor.get('sha256')
            if (descriptor.get('file') != expected_name or expected_name in names
                    or type(size) is not int or size < 0 or (index == 0 and size == 0)
                    or not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
                raise QuarantinedIngestError('Backup inventory is invalid')
            names.add(expected_name)
            total += descriptor['size']
        if total > MAX_TOTAL or total + 32 * 1024 * 1024 > capacity:
            raise QuarantinedIngestError('Backup exceeds isolated memory capacity')
        process = subprocess.Popen(['docker', 'exec', '-i', '-u', '65534:65534', identifier,
                                    '/opt/venv/bin/python', '/offline/scripts/quarantined_backup_receiver.py', token],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _frame(process.stdin, {'kind': 'manifest', 'size': len(manifest), 'sha256': digest})
        process.stdin.write(manifest)
        _frame(process.stdin, {'kind': 'verification', 'size': len(marker_before),
                               'sha256': hashlib.sha256(marker_before).hexdigest()})
        process.stdin.write(marker_before)
        for descriptor in descriptors:
            name, size, expected = descriptor['file'], descriptor['size'], descriptor['sha256']
            _frame(process.stdin, {'kind': 'object', 'name': name, 'size': size, 'sha256': expected})
            for chunk in store.iter_verified(prefix + name, expected_size=size, expected_hash=expected):
                process.stdin.write(chunk)
        _frame(process.stdin, {'kind': 'end'})
        process.stdin.close()
        process.stdin = None
        stdout, _ = process.communicate(timeout=30)
        if (process.returncode != 0 or json.loads(stdout) !=
                {'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False}):
            raise QuarantinedIngestError('Quarantine receiver did not complete')
        if (store.read_small(prefix + 'verified.json', 4096) != marker_before
                or store.read_small(prefix + 'manifest.json', MAX_MANIFEST) != manifest):
            raise QuarantinedIngestError('Remote backup changed during ingestion')
        pipe.send(True)
    except BaseException:
        try:
            pipe.send(False)
        except Exception:
            pass
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if store is not None:
            store.close()
        pipe.close()


def ingest_verified_backup(*, store, run_id, expected_manifest_sha256, expected_revision,
                           container_id, image_id, token, lock_dir, timeout_seconds=600):
    """Import bytes to an owned sandbox or destroy that sandbox on failure.

    An independently authenticated, latest privacy journal is still required
    and the return value can never be used to authorize production restore.
    """
    if (not isinstance(store, GCSBackupStore) or not re.fullmatch('[0-9a-f]{32}', run_id or '')
            or not re.fullmatch('[0-9a-f]{64}', expected_manifest_sha256 or '')
            or not re.fullmatch('[0-9a-f]{12}', expected_revision or '')
            or not re.fullmatch('[0-9a-f]{64}', container_id or '')
            or not re.fullmatch('sha256:[0-9a-f]{64}', image_id or '')
            or not re.fullmatch('[0-9a-f]{32}', token or '')
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900
            or threading.active_count() != 1):
        raise QuarantinedIngestError('Ingest configuration is invalid')
    deadline = time.monotonic() + timeout_seconds
    _local_daemon(deadline)
    lock_path = _private_directory(Path(lock_dir)) / ('ingest-' + token + '.lock')
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _ingest_locked(store, run_id, expected_manifest_sha256, expected_revision,
                              container_id, image_id, token, deadline)
    except BlockingIOError:
        raise QuarantinedIngestError('Sandbox ingestion is already active') from None
    finally:
        os.close(lock_fd)


def _ingest_locked(store, run_id, expected_manifest_sha256, expected_revision,
                   container_id, image_id, token, deadline):
    item = _verify_sandbox(container_id, image_id, token, timeout=_remaining(deadline))
    _ensure_empty(container_id, timeout=_remaining(deadline))
    succeeded = False
    process = None
    parent = None
    child = None
    try:
        options = item['HostConfig']['Tmpfs']['/var/lib/asb-restore'].split(',')
        sizes = [int(value[5:-1]) * 1024 * 1024 for value in options if re.fullmatch(r'size=[1-9][0-9]{0,3}m', value)]
        if len(sizes) != 1:
            raise QuarantinedIngestError('Sandbox capacity is unavailable')
        capacity = min(sizes[0], item['HostConfig']['Memory'])
        parent, child = multiprocessing.get_context('fork').Pipe(duplex=False)
        process = multiprocessing.get_context('fork').Process(target=_worker,
            args=(child, store._bucket, store._token_provider, run_id, expected_manifest_sha256,
                  expected_revision, container_id, token, capacity))
        process.start()
        child.close()
        worker_ok = parent.poll(max(0, deadline - time.monotonic())) and parent.recv() is True
        if worker_ok:
            process.join(max(0, min(10, deadline - time.monotonic())))
            if process.is_alive() or process.exitcode != 0:
                worker_ok = False
        if worker_ok and deadline > time.monotonic():
            _verify_sandbox(container_id, image_id, token, timeout=min(20, deadline - time.monotonic()))
            succeeded = True
            return {'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False,
                    'privacy_replay_verified': False, 'service_publish_authorized': False}
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
        if not succeeded and not _dispose_owned(container_id, image_id, token):
            raise QuarantinedIngestError('Ingest failed; owned sandbox cleanup could not be verified') from None
    raise QuarantinedIngestError('Ingest failed; the owned sandbox was removed')
