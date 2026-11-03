"""Issue and recover checkpoint keys using a separately held recovery key.

This does not provision storage, escrow the recovery key or guarantee that a
trusted envelope reference survives disaster. The caller must hold the random
32-byte recovery key and envelope reference outside the witness administrator.
"""
import hashlib
import hmac
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.services.privacy_journal import JournalError
from src.services.privacy_journal_checkpoint import _store_checkpoint

_ID = re.compile(r'^[0-9a-f]{32}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_MAGIC = b'ASBCK1\x00'


def _name(namespace, key_id):
    if (not isinstance(namespace, str) or not _ID.fullmatch(namespace)
            or not isinstance(key_id, str) or not _ID.fullmatch(key_id)):
        raise JournalError('Checkpoint key reference is invalid')
    return f'privacy-checkpoint-keys/v1/{namespace}/{key_id}'


def issue_checkpoint_key(store, *, namespace, recovery_key):
    """Store a newly generated key encrypted for an independently held key."""
    if not isinstance(recovery_key, bytes) or len(recovery_key) != 32:
        raise JournalError('Recovery key must contain 256 bits')
    key_id = secrets.token_hex(16)
    name = _name(namespace, key_id)
    checkpoint_key = secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    envelope = _MAGIC + nonce + AESGCM(recovery_key).encrypt(nonce, checkpoint_key, name.encode('ascii'))
    digest = _store_checkpoint(store, name, envelope)
    return checkpoint_key, {'namespace': namespace, 'key_id': key_id, 'sha256': digest}


def recover_checkpoint_key(store, *, namespace, key_id, expected_sha256, recovery_key):
    """Authenticate the independently referenced envelope before decrypting."""
    name = _name(namespace, key_id)
    if (not isinstance(recovery_key, bytes) or len(recovery_key) != 32
            or not isinstance(expected_sha256, str) or not _HASH.fullmatch(expected_sha256)):
        raise JournalError('Checkpoint recovery input is invalid')
    try:
        envelope = store.read(name)
        if (not isinstance(envelope, bytes) or len(envelope) != len(_MAGIC) + 12 + 32 + 16
                or not envelope.startswith(_MAGIC)
                or not hmac.compare_digest(hashlib.sha256(envelope).hexdigest(), expected_sha256)):
            raise ValueError('invalid envelope')
        start = len(_MAGIC)
        key = AESGCM(recovery_key).decrypt(envelope[start:start + 12], envelope[start + 12:], name.encode('ascii'))
        if len(key) != 32:
            raise ValueError('invalid key')
        return key
    except Exception:
        raise JournalError('Checkpoint key could not be recovered') from None
