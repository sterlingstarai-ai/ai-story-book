"""Encrypted witness checkpoints for privacy journals; never release a restore.

The caller must authenticate the source, secure a separate checkpoint key and
publish the returned reference through an independently trusted channel. An
old but valid checkpoint proves only its own prefix, never the absence of later
events. Provider/account independence and a latest-head guarantee are not
established by this module.
"""
import asyncio
from collections import defaultdict
import hashlib
import hmac
import json
import re
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.services.privacy_journal import JournalEntry, JournalError, JournalScan, PrivacyJournal
from src.services.privacy_journal_verify import fingerprint_entries
from src.services.privacy_restore_source_guard import hold_consistent_source

_PREFIX = 'privacy-checkpoints/v1/'
_MAGIC = b'ASBPC1\x00'
_MAX_ENTRIES = 100_000
_MAX_BYTES = 5 * 1024 * 1024
_ID = re.compile(r'^[0-9a-f]{32}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')


def _name(namespace, generation):
    if (not isinstance(namespace, str) or not _ID.fullmatch(namespace)
            or type(generation) is not int or not 1 <= generation <= 2**63 - 1):
        raise JournalError('Checkpoint identity is invalid')
    return f'{_PREFIX}{namespace}/{generation:020d}'


def _check_scan(scan):
    if (not isinstance(scan, JournalScan) or scan.restore_authorized is not False
            or type(scan.pending_count) is not int or scan.pending_count != 0
            or not isinstance(scan.committed, tuple) or len(scan.committed) > _MAX_ENTRIES):
        raise JournalError('Journal checkpoint scan is invalid or incomplete')
    ids = set()
    revisions = defaultdict(list)
    for entry in scan.committed:
        if (not isinstance(entry, JournalEntry) or not isinstance(entry.event_id, str)
                or not _ID.fullmatch(entry.event_id) or entry.event_id in ids
                or not isinstance(entry.subject, str) or not entry.subject
                or type(entry.revision) is not int or entry.revision < 1):
            raise JournalError('Journal checkpoint entries are invalid')
        ids.add(entry.event_id)
        revisions[entry.subject].append(entry.revision)
    if any(sorted(values) != list(range(1, len(values) + 1)) for values in revisions.values()):
        raise JournalError('Journal checkpoint revisions are incomplete')
    return ids


def _encode(namespace, generation, key, checkpoint, scan, issued_at):
    name = _name(namespace, generation)
    if not isinstance(key, bytes) or len(key) != 32:
        raise JournalError('Checkpoint key must contain 256 bits')
    ids = _check_scan(scan)
    if (not isinstance(checkpoint, dict) or checkpoint.get('status') != 'CURRENT_OUTBOX_MATCHES_JOURNAL'
            or checkpoint.get('restore_authorized') is not False or type(checkpoint.get('event_count')) is not int
            or checkpoint['event_count'] != len(ids) or not isinstance(checkpoint.get('journal_sha256'), str)
            or not _HASH.fullmatch(checkpoint['journal_sha256']) or type(issued_at) is not int
            or issued_at < 0 or fingerprint_entries(scan.committed) != checkpoint['journal_sha256']):
        raise JournalError('Checkpoint does not match source journal')
    data = json.dumps({'version': 1, 'issued_at': issued_at, 'event_ids': sorted(ids),
                       'event_count': len(ids), 'journal_sha256': checkpoint['journal_sha256']},
                      sort_keys=True, separators=(',', ':')).encode()
    if len(data) > _MAX_BYTES - 64:
        raise JournalError('Checkpoint is too large')
    nonce = secrets.token_bytes(12)
    return name, _MAGIC + nonce + AESGCM(key).encrypt(nonce, data, name.encode('ascii'))


def _store_checkpoint(witness, name, value):
    try:
        witness.create(name, value)
    except Exception:
        # A timeout may mean the immutable create succeeded. Do not overwrite.
        try:
            if not hmac.compare_digest(witness.read(name), value):
                raise ValueError('checkpoint conflict')
        except Exception:
            raise JournalError('Witness checkpoint could not be stored') from None
    try:
        if not hmac.compare_digest(witness.read(name), value):
            raise ValueError('checkpoint mismatch')
    except Exception:
        raise JournalError('Witness checkpoint could not be verified') from None
    return hashlib.sha256(value).hexdigest()


async def capture_fenced_checkpoint(db, journal, witness, *, namespace, generation, key, now=None):
    """Store a source-verified checkpoint under the cooperating writer fence.

    Returns a reference that must be anchored independently. Closing the fence
    allows new events, so this capture is not a continuously current head.
    """
    if not isinstance(journal, PrivacyJournal) or witness is journal._store:
        raise JournalError('A separate checkpoint witness is required')
    timestamp = int(time.time()) if now is None else now
    try:
        async with hold_consistent_source(db, journal) as (checkpoint, scan):
            name, value = _encode(namespace, generation, key, checkpoint, scan, timestamp)
            task = asyncio.create_task(asyncio.to_thread(_store_checkpoint, witness, name, value))
            try:
                digest = await asyncio.shield(task)
            except asyncio.CancelledError as cancelled:
                # The provider write runs in a thread; hold the fence until it
                # ends even under repeated cancellation.
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                raise cancelled
            return {'status': 'FENCED_WITNESS_CHECKPOINT_STORED', 'namespace': namespace,
                    'generation': generation, 'sha256': digest, 'event_count': checkpoint['event_count'],
                    'restore_authorized': False}
    except (JournalError, asyncio.CancelledError):
        raise
    except Exception:
        raise JournalError('Witness checkpoint capture failed') from None


def verify_checkpoint_extension(witness, scan, *, namespace, generation, expected_sha256, key, now, max_age):
    """Verify an authenticated reference and retained prefix of a newer scan.

    `expected_sha256` and generation MUST come from an independently trusted
    latest-head channel; max_age only bounds staleness, not events after capture.
    Success never authorizes promotion, nor proves all application mutations
    were journaled or that the witness and key have separate administrators.
    """
    result, _, _ = _verify_checkpoint_extension(witness, scan, namespace=namespace, generation=generation,
        expected_sha256=expected_sha256, key=key, now=now, max_age=max_age, historical=False)
    return result


def _verify_checkpoint_extension(witness, scan, *, namespace, generation, expected_sha256, key, now,
                                 max_age, historical):
    """Return authenticated membership only to internal chain verification.

    Historical checkpoints can be older than the latest head's age limit, but
    must still have a valid non-future issue time. This does not establish that
    the latest head itself is current or independently administered.
    """
    name = _name(namespace, generation)
    if (not isinstance(key, bytes) or len(key) != 32 or not isinstance(expected_sha256, str)
            or not _HASH.fullmatch(expected_sha256) or type(now) is not int or now < 0
            or type(max_age) is not int or not 0 <= max_age <= 86400):
        raise JournalError('Trusted checkpoint reference is invalid')
    ids = _check_scan(scan)
    try:
        blob = witness.read(name)
        if (not isinstance(blob, bytes) or not 36 <= len(blob) <= _MAX_BYTES or not blob.startswith(_MAGIC)
                or not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), expected_sha256)):
            raise ValueError('checkpoint reference mismatch')
        offset = len(_MAGIC)
        decoded = AESGCM(key).decrypt(blob[offset:offset + 12], blob[offset + 12:], name.encode('ascii'))
        obj = json.loads(decoded)
        if (not isinstance(obj, dict) or set(obj) != {'version', 'issued_at', 'event_ids', 'event_count', 'journal_sha256'}
                or type(obj['version']) is not int or obj['version'] != 1 or type(obj['issued_at']) is not int
                or not 0 <= obj['issued_at'] <= now
                or (not historical and now - obj['issued_at'] > max_age)
                or type(obj['event_count']) is not int or not 0 <= obj['event_count'] <= _MAX_ENTRIES
                or not isinstance(obj['event_ids'], list) or len(obj['event_ids']) != obj['event_count']
                or any(not isinstance(value, str) or not _ID.fullmatch(value) for value in obj['event_ids'])
                or obj['event_ids'] != sorted(set(obj['event_ids']))
                or not isinstance(obj['journal_sha256'], str) or not _HASH.fullmatch(obj['journal_sha256'])):
            raise ValueError('invalid checkpoint')
        checkpoint_ids = set(obj['event_ids'])
        if not checkpoint_ids.issubset(ids):
            raise ValueError('checkpoint events missing')
        retained = (entry for entry in scan.committed if entry.event_id in checkpoint_ids)
        if not hmac.compare_digest(fingerprint_entries(retained), obj['journal_sha256']):
            raise ValueError('checkpoint contents differ')
        return ({'status': 'WITNESSED_PREFIX_MATCHES', 'checkpoint_count': obj['event_count'],
                 'journal_count': len(ids), 'restore_authorized': False}, checkpoint_ids, obj['issued_at'])
    except Exception:
        raise JournalError('Witness checkpoint cannot verify journal extension') from None
