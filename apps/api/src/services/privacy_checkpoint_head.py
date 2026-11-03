"""Authenticated append-only checkpoint heads, with an external trust anchor.

An anchor is the exact latest sequence and digest recorded outside both the
source and this store. The code cannot establish whether that external anchor
is actually latest, independently administered, or preserved after a disaster.
"""
import hashlib
import hmac
import json
import re
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.services.privacy_journal import JournalError
from src.services.privacy_journal_checkpoint import _store_checkpoint, _verify_checkpoint_extension

_ID = re.compile(r'^[0-9a-f]{32}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_MAGIC = b'ASBCH1\x00'
# Bound verification work; start a new independently anchored namespace before
# exhausting this chain. A chain alone never proves there were no later events.
_LIMIT = 256
_VERIFY_SECONDS = 30


def _name(namespace, sequence):
    if (not isinstance(namespace, str) or not _ID.fullmatch(namespace)
            or type(sequence) is not int or not 1 <= sequence <= _LIMIT):
        raise JournalError('Checkpoint head identity is invalid')
    return f'privacy-checkpoint-heads/v1/{namespace}/{sequence:020d}'


def _reference(ref):
    return (isinstance(ref, dict) and set(ref) == {'sequence', 'sha256'}
            and type(ref['sequence']) is int and 1 <= ref['sequence'] <= _LIMIT
            and isinstance(ref['sha256'], str) and bool(_HASH.fullmatch(ref['sha256'])))


def _read(store, namespace, ref, key):
    if not _reference(ref) or not isinstance(key, bytes) or len(key) != 32:
        raise JournalError('Trusted checkpoint head is invalid')
    name = _name(namespace, ref['sequence'])
    try:
        blob = store.read(name)
        if (not isinstance(blob, bytes) or not 35 <= len(blob) <= 1024 or not blob.startswith(_MAGIC)
                or not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), ref['sha256'])):
            raise ValueError('invalid head')
        offset = len(_MAGIC)
        obj = json.loads(AESGCM(key).decrypt(blob[offset:offset + 12], blob[offset + 12:], name.encode('ascii')))
        if (not isinstance(obj, dict) or set(obj) != {'version', 'checkpoint_sha256', 'previous'}
                or type(obj['version']) is not int or obj['version'] != 1
                or not isinstance(obj['checkpoint_sha256'], str) or not _HASH.fullmatch(obj['checkpoint_sha256'])
                or (ref['sequence'] == 1 and obj['previous'] is not None)
                or (ref['sequence'] > 1 and (not _reference(obj['previous'])
                                             or obj['previous']['sequence'] != ref['sequence'] - 1))):
            raise ValueError('invalid chain')
        return obj
    except Exception:
        raise JournalError('Checkpoint head cannot be verified') from None


def append_checkpoint_head(store, *, namespace, key, checkpoint, previous=None):
    """Append after a trusted previous head; publish returned ref independently."""
    if (not isinstance(key, bytes) or len(key) != 32 or not isinstance(checkpoint, dict)
            or checkpoint.get('status') != 'FENCED_WITNESS_CHECKPOINT_STORED'
            or checkpoint.get('restore_authorized') is not False or checkpoint.get('namespace') != namespace
            or type(checkpoint.get('generation')) is not int or not isinstance(checkpoint.get('sha256'), str)
            or not _HASH.fullmatch(checkpoint['sha256'])):
        raise JournalError('Checkpoint head input is invalid')
    sequence = checkpoint['generation']
    name = _name(namespace, sequence)
    if sequence == 1:
        if previous is not None:
            raise JournalError('Initial checkpoint head cannot have a predecessor')
    else:
        if not _reference(previous) or previous['sequence'] != sequence - 1:
            raise JournalError('Checkpoint head predecessor is invalid')
        _read(store, namespace, previous, key)
    payload = json.dumps({'version': 1, 'checkpoint_sha256': checkpoint['sha256'], 'previous': previous},
                         sort_keys=True, separators=(',', ':')).encode()
    nonce = secrets.token_bytes(12)
    blob = _MAGIC + nonce + AESGCM(key).encrypt(nonce, payload, name.encode('ascii'))
    return {'sequence': sequence, 'sha256': _store_checkpoint(store, name, blob)}


def verify_anchored_checkpoint(head_store, checkpoint_store, scan, *, namespace, head_key, checkpoint_key,
                               candidate_head, trusted_head, now, max_age):
    """Require exact external head, full chain and matching journal prefix.

    The external trusted head MUST be retained in an independent failure and
    administration domain. This API always returns restore_authorized=false.
    """
    if (not _reference(trusted_head) or not _reference(candidate_head)
            or candidate_head['sequence'] != trusted_head['sequence']
            or not hmac.compare_digest(candidate_head['sha256'], trusted_head['sha256'])):
        raise JournalError('Checkpoint head does not match the trusted anchor')
    current = candidate_head
    latest = None
    latest_result = None
    newer_ids = None
    newer_timestamp = None
    deadline = time.monotonic() + _VERIFY_SECONDS
    while current is not None:
        if time.monotonic() >= deadline:
            raise JournalError('Checkpoint chain verification timed out')
        obj = _read(head_store, namespace, current, head_key)
        if latest is None:
            latest = obj
        result, checkpoint_ids, issued_at = _verify_checkpoint_extension(checkpoint_store, scan,
            namespace=namespace, generation=current['sequence'], expected_sha256=obj['checkpoint_sha256'],
            key=checkpoint_key, now=now, max_age=max_age, historical=newer_ids is not None)
        if newer_ids is not None and (not checkpoint_ids.issubset(newer_ids) or issued_at > newer_timestamp):
            raise JournalError('Checkpoint chain is not an append-only history')
        if latest_result is None:
            latest_result = result
        newer_ids, newer_timestamp = checkpoint_ids, issued_at
        current = obj['previous']
    if time.monotonic() >= deadline:
        raise JournalError('Checkpoint chain verification timed out')
    return {'status': 'ANCHORED_WITNESSED_PREFIX_MATCHES', 'head_sequence': candidate_head['sequence'],
            'checkpoint_count': latest_result['checkpoint_count'], 'journal_count': latest_result['journal_count'],
            'restore_authorized': False}
