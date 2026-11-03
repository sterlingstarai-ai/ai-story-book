"""Encrypted, append-only privacy journal building blocks.

Account and consent operations may use these primitives when the journal is
enabled. The primitives alone do not establish completeness, independent
storage, or restore authorization. A missing, incomplete or corrupt journal
must never be treated as empty.
"""

import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class JournalError(RuntimeError):
    """A journal operation failed without exposing identifiers or provider data."""


class ImmutableStore(Protocol):
    """Provider must implement strongly consistent listing and create-only writes."""

    def create(self, name: str, data: bytes) -> None: ...
    def read(self, name: str) -> bytes: ...
    def list_names(self, prefix: str) -> list[str]: ...


@dataclass(frozen=True)
class CredentialState:
    """Only existing one-way verifier hashes; never raw device/recovery keys."""

    device_hash: str | None = field(repr=False)
    recovery_hash: str | None = field(repr=False)
    previous_hash: str | None = field(repr=False)
    recovery_created_at: datetime | None = field(repr=False)


@dataclass(frozen=True)
class ConsentState:
    privacy: bool
    photos: bool
    data_processing: bool
    version: str


@dataclass(frozen=True)
class DeletionReceipt:
    request_id: str
    profile_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class JournalEntry:
    event_id: str
    action: str
    subject: str = field(repr=False)
    revision: int
    credential_state: CredentialState | None = field(default=None, repr=False)
    resource_id: str | None = field(default=None, repr=False)
    consent_state: ConsentState | None = field(default=None, repr=False)
    deletion_receipt: DeletionReceipt | None = field(default=None, repr=False)


@dataclass(frozen=True)
class JournalScan:
    committed: tuple[JournalEntry, ...]
    pending_count: int
    # A successful scan is deliberately never a release authorization: it does
    # not prove journal coverage, authority, ordering, or the absence of races.
    restore_authorized: bool = False


_PREFIX = 'privacy-journal/v1/'
_NAME = re.compile(r'^privacy-journal/v1/([0-9a-f]{32})/(intent|commit|abort)$')
# Internal ownership identifiers currently use the legacy UUID form. Accepting
# an identifier that the replayer cannot address would create unreplayable data.
_SUBJECT = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
RESOURCE_ACTIONS = frozenset({'book_delete', 'character_delete', 'profile_delete', 'voice_delete', 'voice_revoke', 'voice_changed', 'share_revoke'})
_ACTIONS = frozenset({'account_delete', 'consent_revoke', 'consent_grant', 'photo_revoke', 'credential_revoke'}) | RESOURCE_ACTIONS
_RESOURCE = re.compile(r'^[A-Za-z0-9_-]{1,60}$')
_VERSION = b'ASBPJ1\x00'
_MAX_RECORD_BYTES = 4096


def consent_state_to_payload(state: ConsentState | None) -> dict | None:
    if state is None:
        return None
    if (not isinstance(state, ConsentState) or type(state.privacy) is not bool or type(state.photos) is not bool
            or type(state.data_processing) is not bool or not isinstance(state.version, str)
            or not 1 <= len(state.version) <= 20 or not re.fullmatch(r'[A-Za-z0-9_.-]+', state.version)):
        raise JournalError('Consent state is invalid')
    return {'privacy': state.privacy, 'photos': state.photos,
            'data_processing': state.data_processing, 'version': state.version}


def consent_state_from_payload(value) -> ConsentState | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'privacy', 'photos', 'data_processing', 'version'}:
        raise JournalError('Consent state is invalid')
    state = ConsentState(value['privacy'], value['photos'], value['data_processing'], value['version'])
    consent_state_to_payload(state)
    return state


def deletion_receipt_to_payload(value: DeletionReceipt | None) -> dict | None:
    if value is None:
        return None
    if (not isinstance(value, DeletionReceipt) or not isinstance(value.request_id, str)
            or not re.fullmatch('[0-9a-f]{32}', value.request_id)
            or (value.profile_id is not None and (not isinstance(value.profile_id, str)
                or not _RESOURCE.fullmatch(value.profile_id)))):
        raise JournalError('Deletion receipt is invalid')
    return {'request_id': value.request_id, 'profile_id': value.profile_id}


def deletion_receipt_from_payload(value) -> DeletionReceipt | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'request_id', 'profile_id'}:
        raise JournalError('Deletion receipt is invalid')
    result = DeletionReceipt(value['request_id'], value['profile_id'])
    deletion_receipt_to_payload(result)
    return result


def credential_state_to_payload(state: CredentialState | None) -> dict | None:
    if state is None:
        return None
    if not isinstance(state, CredentialState):
        raise JournalError('Credential state is invalid')
    for value in (state.device_hash, state.recovery_hash, state.previous_hash):
        if value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
            raise JournalError('Credential state is invalid')
    created = state.recovery_created_at
    if created is not None and (not isinstance(created, datetime) or created.tzinfo is not None):
        raise JournalError('Credential state is invalid')
    return {'device_hash': state.device_hash, 'recovery_hash': state.recovery_hash,
            'previous_hash': state.previous_hash,
            'recovery_created_at': created.isoformat(timespec='microseconds') if created else None}


def credential_state_from_payload(value) -> CredentialState | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        'device_hash', 'recovery_hash', 'previous_hash', 'recovery_created_at',
    }:
        raise JournalError('Credential state is invalid')
    try:
        timestamp = value['recovery_created_at']
        if timestamp is not None and (not isinstance(timestamp, str) or len(timestamp) > 32):
            raise ValueError('invalid timestamp')
        state = CredentialState(value['device_hash'], value['recovery_hash'], value['previous_hash'],
                                datetime.fromisoformat(timestamp) if timestamp is not None else None)
        if credential_state_to_payload(state) != value:
            raise ValueError('noncanonical credential state')
        return state
    except (ValueError, TypeError, JournalError):
        raise JournalError('Credential state is invalid') from None


class PrivacyJournal:
    def __init__(self, store: ImmutableStore, encryption_key: bytes):
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise JournalError('A 256-bit journal encryption key is required')
        self._store = store
        self._aead = AESGCM(encryption_key)

    def _seal(self, name: str, payload: dict) -> bytes:
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return _VERSION + nonce + self._aead.encrypt(nonce, plaintext, name.encode('ascii'))

    def _open(self, name: str, data: bytes) -> dict:
        if not isinstance(data, bytes) or not data.startswith(_VERSION) or not 35 <= len(data) <= _MAX_RECORD_BYTES:
            raise JournalError('Journal record is invalid')
        offset = len(_VERSION)
        try:
            plaintext = self._aead.decrypt(data[offset:offset + 12], data[offset + 12:], name.encode('ascii'))
            value = json.loads(plaintext)
        except (InvalidTag, ValueError, UnicodeError):
            raise JournalError('Journal record authentication failed') from None
        if not isinstance(value, dict):
            raise JournalError('Journal record is invalid')
        return value

    def _matching_existing(self, name: str, payload: dict) -> bool:
        """Authenticate an existing record, repairing a partial mirror if supported."""
        try:
            return self._open(name, self._store.read(name)) == payload
        except Exception:
            reconcile = getattr(self._store, 'reconcile', None)
            if reconcile is None:
                raise
            reconcile(name, lambda ciphertext: self._open(name, ciphertext) == payload)
            return self._open(name, self._store.read(name)) == payload

    def _list_or_reconcile(self, prefix: str, name: str, payload: dict):
        try:
            return self._store.list_names(prefix)
        except Exception:
            # A previous mirror attempt can leave an exact authenticated
            # partial record. Repair only that expected record; any other
            # disagreement must still make the repeated listing fail.
            reconcile = getattr(self._store, 'reconcile', None)
            if reconcile is None:
                raise
            reconcile(name, lambda ciphertext: self._open(name, ciphertext) == payload)
            return self._store.list_names(prefix)

    def begin(self, action: str, subject: str, *, revision: int, event_id: str | None = None,
              credential_state: CredentialState | None = None, resource_id: str | None = None,
              consent_state: ConsentState | None = None, deletion_receipt: DeletionReceipt | None = None) -> str:
        if not isinstance(action, str) or action not in _ACTIONS or not isinstance(subject, str) or not _SUBJECT.fullmatch(subject):
            raise JournalError('Unsupported journal event')
        if type(revision) is not int or not 1 <= revision <= 2**63 - 1:
            raise JournalError('Journal revision is invalid')
        if credential_state is not None and action != 'credential_revoke':
            raise JournalError('Credential state is invalid')
        if (action in RESOURCE_ACTIONS) != (isinstance(resource_id, str) and bool(_RESOURCE.fullmatch(resource_id))):
            raise JournalError('Resource identifier is invalid')
        if action not in RESOURCE_ACTIONS and resource_id is not None:
            raise JournalError('Resource identifier is invalid')
        consent_payload = consent_state_to_payload(consent_state)
        if (action == 'consent_grant') != (consent_payload is not None):
            raise JournalError('Consent state is invalid')
        credential_payload = credential_state_to_payload(credential_state)
        receipt_payload = deletion_receipt_to_payload(deletion_receipt)
        if receipt_payload is not None and action != 'book_delete':
            raise JournalError('Deletion receipt is invalid')
        if event_id is None:
            event_id = uuid.uuid4().hex
        if not isinstance(event_id, str) or not re.fullmatch('[0-9a-f]{32}', event_id):
            raise JournalError('Journal event identifier is invalid')
        name = f'{_PREFIX}{event_id}/intent'
        payload = {'id': event_id, 'action': action, 'subject': subject, 'revision': revision,
                   'credential_state': credential_payload}
        if resource_id is not None:
            payload['resource_id'] = resource_id
        if consent_payload is not None:
            payload['consent_state'] = consent_payload
        if receipt_payload is not None:
            payload['deletion_receipt'] = receipt_payload
        data = self._seal(name, payload)
        try:
            aborted = f'{_PREFIX}{event_id}/abort' in self._list_or_reconcile(
                f'{_PREFIX}{event_id}/', name, payload)
        except Exception:
            raise JournalError('Journal event state is unavailable') from None
        if aborted:
            raise JournalError('Journal event was aborted')
        try:
            self._store.create(name, data)
            # A provider's successful create response alone does not establish
            # that the intended bytes can be read before the DB mutation commits.
            if not hmac.compare_digest(self._store.read(name), data):
                raise JournalError('Journal intent readback does not match')
        except Exception:
            # A create-only request may have succeeded before a timeout. Only
            # accept the retry if the existing authenticated intent is exact.
            try:
                if not self._matching_existing(name, payload):
                    raise JournalError('Journal intent conflict')
            except Exception:
                raise JournalError('Journal intent could not be preserved') from None
        return event_id

    def commit(self, event_id: str, *, expected: JournalEntry | None = None) -> None:
        if not isinstance(event_id, str) or not re.fullmatch('[0-9a-f]{32}', event_id):
            raise JournalError('Journal event identifier is invalid')
        intent = f'{_PREFIX}{event_id}/intent'
        commit = f'{_PREFIX}{event_id}/commit'
        try:
            intent_data = self._store.read(intent)
            value = self._open(intent, intent_data)
            entry = self._validate_intent(event_id, value)
            if expected is not None and entry != expected:
                raise JournalError('Journal intent does not match the committed event')
            payload = {
                'id': event_id, 'state': 'committed',
                'intent_sha256': hashlib.sha256(intent_data).hexdigest(),
            }
            if f'{_PREFIX}{event_id}/abort' in self._list_or_reconcile(
                    f'{_PREFIX}{event_id}/', commit, payload):
                raise JournalError('Journal event was aborted')
            try:
                sealed = self._seal(commit, payload)
                self._store.create(commit, sealed)
                if not hmac.compare_digest(self._store.read(commit), sealed):
                    raise JournalError('Journal commit readback does not match')
            except Exception:
                # Resolve a timeout or precondition failure without rewriting.
                if not self._matching_existing(commit, payload):
                    raise JournalError('Journal commit conflict')
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal commit could not be preserved') from None

    def _abort_uncommitted(self, event_id: str) -> None:
        """Mark an abandoned intent; caller must hold a proven writer fence.

        This primitive alone cannot establish whether a DB transaction committed.
        A caller must check the authoritative primary while excluding every writer.
        """
        if not isinstance(event_id, str) or not re.fullmatch('[0-9a-f]{32}', event_id):
            raise JournalError('Journal event identifier is invalid')
        prefix = f'{_PREFIX}{event_id}/'
        intent = prefix + 'intent'
        abort = prefix + 'abort'
        try:
            data = self._store.read(intent)
            self._validate_intent(event_id, self._open(intent, data))
            payload = {'id': event_id, 'state': 'aborted', 'intent_sha256': hashlib.sha256(data).hexdigest()}
            names = self._list_or_reconcile(prefix, abort, payload)
            if prefix + 'commit' in names:
                raise JournalError('Committed events cannot be aborted')
            try:
                sealed = self._seal(abort, payload)
                self._store.create(abort, sealed)
                if not hmac.compare_digest(self._store.read(abort), sealed):
                    raise JournalError('Journal abort readback does not match')
            except Exception:
                if not self._matching_existing(abort, payload):
                    raise JournalError('Journal abort conflict')
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal abort could not be preserved') from None

    @staticmethod
    def _validate_intent(event_id: str, value: dict) -> JournalEntry:
        required = {'id', 'action', 'subject', 'revision', 'credential_state'}
        if (not required.issubset(value) or set(value) - required - {'resource_id', 'consent_state', 'deletion_receipt'} or value['id'] != event_id
                or not isinstance(value['action'], str) or value['action'] not in _ACTIONS
                or not isinstance(value['subject'], str)
                or not _SUBJECT.fullmatch(value['subject']) or type(value['revision']) is not int
                or not 1 <= value['revision'] <= 2**63 - 1):
            raise JournalError('Journal intent is invalid')
        state = credential_state_from_payload(value['credential_state'])
        if state is not None and value['action'] != 'credential_revoke':
            raise JournalError('Journal intent is invalid')
        resource_id = value.get('resource_id')
        if (value['action'] in RESOURCE_ACTIONS) != (isinstance(resource_id, str) and bool(_RESOURCE.fullmatch(resource_id))):
            raise JournalError('Journal resource identifier is invalid')
        if value['action'] not in RESOURCE_ACTIONS and 'resource_id' in value:
            raise JournalError('Journal resource identifier is invalid')
        consent = consent_state_from_payload(value.get('consent_state'))
        if (value['action'] == 'consent_grant') != (consent is not None):
            raise JournalError('Journal consent state is invalid')
        if value['action'] != 'consent_grant' and 'consent_state' in value:
            raise JournalError('Journal consent state is invalid')
        receipt = deletion_receipt_from_payload(value.get('deletion_receipt'))
        if ('deletion_receipt' in value and (receipt is None or value['action'] != 'book_delete')):
            raise JournalError('Journal deletion receipt is invalid')
        return JournalEntry(event_id, value['action'], value['subject'], value['revision'], state, resource_id, consent, receipt)

    def scan(self) -> JournalScan:
        try:
            names = self._store.list_names(_PREFIX)
            if not isinstance(names, list) or len(names) != len(set(names)):
                raise JournalError('Journal listing is invalid')
            groups: dict[str, set[str]] = {}
            for name in names:
                if not isinstance(name, str):
                    raise JournalError('Journal listing is invalid')
                match = _NAME.fullmatch(name)
                if not match:
                    raise JournalError('Journal listing is invalid')
                groups.setdefault(match[1], set()).add(match[2])
            committed = []
            pending = 0
            for event_id, phases in groups.items():
                if 'intent' not in phases:
                    raise JournalError('Journal commit has no intent')
                if 'abort' in phases and 'commit' in phases:
                    raise JournalError('Journal event has conflicting outcomes')
                intent = f'{_PREFIX}{event_id}/intent'
                intent_data = self._store.read(intent)
                entry = self._validate_intent(event_id, self._open(intent, intent_data))
                if 'abort' in phases:
                    abort = f'{_PREFIX}{event_id}/abort'
                    value = self._open(abort, self._store.read(abort))
                    if value != {'id': event_id, 'state': 'aborted',
                                 'intent_sha256': hashlib.sha256(intent_data).hexdigest()}:
                        raise JournalError('Journal abort is invalid')
                    continue
                if 'commit' not in phases:
                    pending += 1
                    continue
                commit = f'{_PREFIX}{event_id}/commit'
                value = self._open(commit, self._store.read(commit))
                if value != {'id': event_id, 'state': 'committed',
                             'intent_sha256': hashlib.sha256(intent_data).hexdigest()}:
                    raise JournalError('Journal commit is invalid')
                committed.append(entry)
            return JournalScan(tuple(committed), pending)
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal scan could not be completed') from None
