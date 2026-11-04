"""Authenticate an off-host restore of the exact backup created during media detach."""
import base64
import binascii
import hmac
import json
import os
import re
import secrets
import select
import stat
import subprocess
import tempfile
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from narration_release_backup import SOURCE_REVISION
from narration_deploy_safety import _private_directory
from publish_backup_gcs import _valid_checkpoint
from quarantined_backup_ingest import _verify_sandbox, ingest_verified_backup
from quarantined_restore_adapter import restore_in_owned_sandbox


class DetachAttestationError(RuntimeError):
    pass


def _matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _message(challenge):
    if (not isinstance(challenge, dict) or set(challenge) != {
            'nonce', 'run_id', 'manifest_sha256', 'revision', 'event_count', 'journal_sha256', 'issued_at',
        } or not _matches(challenge['nonce'], '[0-9a-f]{64}')
            or not _matches(challenge['run_id'], '[0-9a-f]{32}')
            or not _matches(challenge['manifest_sha256'], '[0-9a-f]{64}')
            or not _matches(challenge['journal_sha256'], '[0-9a-f]{64}')
            or challenge['revision'] != SOURCE_REVISION or type(challenge['event_count']) is not int
            or not 0 <= challenge['event_count'] <= 100000
            or type(challenge['issued_at']) is not int or challenge['issued_at'] <= 0):
        raise DetachAttestationError('Invalid restore challenge')
    return b'AI Story Book storage detach isolated restore v1\x00' + json.dumps(
        challenge, sort_keys=True, separators=(',', ':')).encode('ascii')


def issue_restore_challenge(*, run_id, manifest_sha256, revision, journal_checkpoint):
    if not _valid_checkpoint(journal_checkpoint):
        raise DetachAttestationError('Fenced journal binding is invalid')
    challenge = {'nonce': secrets.token_hex(32), 'run_id': run_id, 'manifest_sha256': manifest_sha256,
                 'revision': revision, 'event_count': journal_checkpoint['event_count'],
                 'journal_sha256': journal_checkpoint['journal_sha256'], 'issued_at': int(time.time())}
    _message(challenge)
    return challenge


def _fresh_message(challenge):
    message = _message(challenge)
    if not 0 <= int(time.time()) - challenge['issued_at'] <= 600:
        raise DetachAttestationError('Restore challenge is outside its validity window')
    return message


def _verify_signed_checkpoint(challenge, sandbox, *, head_store, checkpoint_store, public_key, receipt,
                              namespace, trusted_head, head_key, checkpoint_key):
    """Match an independently observed head to the restored outbox without exporting the journal key."""
    from src.services.privacy_checkpoint_head import _read
    from src.services.privacy_journal_checkpoint import _read_checkpoint
    from src.services.privacy_witness_receipt import verify_receipt

    if head_store is checkpoint_store or head_key == checkpoint_key:
        raise DetachAttestationError('Distinct checkpoint and head inputs are required')
    now = int(time.time())
    verify_receipt(public_key, receipt, namespace=namespace, trusted_head=trusted_head, now=now, max_age=600)
    head = _read(head_store, namespace, trusted_head, head_key)
    checkpoint = _read_checkpoint(checkpoint_store, namespace=namespace, generation=trusted_head['sequence'],
        expected_sha256=head['checkpoint_sha256'], key=checkpoint_key, now=now, max_age=600, historical=False)
    if (checkpoint['issued_at'] > receipt['payload']['observed_at']
            or checkpoint['event_count'] != challenge['event_count']
            or not hmac.compare_digest(checkpoint['journal_sha256'], challenge['journal_sha256'])):
        raise DetachAttestationError('Signed checkpoint differs from the fenced history')
    container, image, token = (sandbox[key] for key in ('container_id', 'image_id', 'token'))
    _verify_sandbox(container, image, token)

    def query(script):
        result = subprocess.run(['docker', 'exec', '-u', '65534:65534', '-e', 'ASB_QUARANTINE_RESTORE=1', container,
                                 '/opt/venv/bin/python', '/offline/scripts/' + script, token],
                                capture_output=True, timeout=90)
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
            raise DetachAttestationError('Restored target verification failed')
        return json.loads(result.stdout)

    if query('quarantined_replay_preflight.py') != {'status': 'RESTORED_TARGET_MATCHES_BACKUP_QUARANTINED',
            'latest_journal_verified': False, 'privacy_replay_authorized': False, 'restore_authorized': False}:
        raise DetachAttestationError('Restored database or media differs from the backup')
    expected = {'status': 'BACKUP_OUTBOX_CHECKPOINT_MATCHES', 'event_ids': checkpoint['event_ids'],
                'journal_sha256': checkpoint['journal_sha256'], 'restore_authorized': False}
    if query('quarantined_outbox_binding.py') != expected:
        raise DetachAttestationError('Restored outbox differs from the signed checkpoint')
    _verify_sandbox(container, image, token)


def restore_and_attest(challenge, *, store, sandbox, signing_key, signed_witness):
    """Sign only after the isolated DB, media and complete fenced history match."""
    _fresh_message(challenge)
    if not isinstance(signing_key, Ed25519PrivateKey):
        raise DetachAttestationError('Restore signing key is invalid')
    imported = ingest_verified_backup(store=store, run_id=challenge['run_id'],
        expected_manifest_sha256=challenge['manifest_sha256'], expected_revision=challenge['revision'], **sandbox)
    if (imported.get('status') != 'BACKUP_IMPORTED_QUARANTINED' or imported.get('restore_authorized') is not False
            or imported.get('privacy_replay_verified') is not False):
        raise DetachAttestationError('Backup import is unverified')
    restored = restore_in_owned_sandbox(**sandbox)
    if (restored.get('status') != 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED'
            or restored.get('restore_authorized') is not False
            or restored.get('service_publish_authorized') is not False):
        raise DetachAttestationError('Database or media restore is unverified')
    _verify_signed_checkpoint(challenge, sandbox, **signed_witness)
    return base64.b64encode(signing_key.sign(_fresh_message(challenge))).decode('ascii')


def verify_restore_attestation(challenge, signature, *, public_key):
    message = _fresh_message(challenge)
    if not isinstance(public_key, Ed25519PublicKey) or not _matches(signature, '[A-Za-z0-9+/]{86}=='):
        raise DetachAttestationError('Restore attestation is invalid')
    try:
        public_key.verify(base64.b64decode(signature, validate=True), message)
    except (InvalidSignature, binascii.Error):
        raise DetachAttestationError('Restore attestation is invalid') from None


def request_restore_attestation(challenge, *, input_fd, output, timeout_seconds=540):
    """Exchange one challenge/signature pair over an already authenticated pipe."""
    _fresh_message(challenge)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 540:
        raise DetachAttestationError('Restore attestation deadline is invalid')
    output.write(json.dumps(challenge, sort_keys=True, separators=(',', ':')).encode('ascii') + b'\n')
    output.flush()
    deadline = time.monotonic() + timeout_seconds
    reply = bytearray()
    while b'\n' not in reply and len(reply) < 89:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([input_fd], [], [], remaining)[0]:
            raise DetachAttestationError('Restore attestation deadline expired')
        block = os.read(input_fd, 90 - len(reply))
        if not block:
            raise DetachAttestationError('Restore verifier disconnected')
        reply.extend(block)
    if re.fullmatch(rb'[A-Za-z0-9+/]{86}==\n', reply) is None:
        raise DetachAttestationError('Restore attestation response is invalid')
    return reply[:-1].decode('ascii')


_MAILBOX_LIMITS = {'started': 128, 'challenge': 1024, 'signature': 90, 'result': 1024}


def write_mailbox_record(directory, name, content):
    """Publish one immutable record without exposing a partially written file."""
    folder = _private_directory(directory)
    if name not in _MAILBOX_LIMITS or not isinstance(content, bytes) or not 0 < len(content) <= _MAILBOX_LIMITS[name]:
        raise DetachAttestationError('Invalid restore mailbox record')
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as file:
        temporary = folder / os.path.basename(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            os.link(temporary, folder / name, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
    fd = os.open(folder, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_mailbox_record(directory, name):
    folder = _private_directory(directory)
    limit = _MAILBOX_LIMITS[name]
    fd = os.open(folder / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= limit):
            raise DetachAttestationError('Unsafe restore mailbox record')
        result = os.read(fd, limit + 1)
        if len(result) != info.st_size:
            raise DetachAttestationError('Restore mailbox record changed')
        return result
    finally:
        os.close(fd)


def request_mailbox_attestation(challenge, directory, *, timeout_seconds=540):
    _fresh_message(challenge)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 540:
        raise DetachAttestationError('Restore attestation deadline is invalid')
    write_mailbox_record(directory, 'challenge', json.dumps(challenge, sort_keys=True).encode('ascii') + b'\n')
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            reply = read_mailbox_record(directory, 'signature')
        except FileNotFoundError:
            time.sleep(1)
            continue
        if re.fullmatch(rb'[A-Za-z0-9+/]{86}==\n', reply) is None:
            raise DetachAttestationError('Restore attestation response is invalid')
        return reply[:-1].decode('ascii')
    raise DetachAttestationError('Restore attestation deadline expired')
