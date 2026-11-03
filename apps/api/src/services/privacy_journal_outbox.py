"""Inactive prototype connecting encrypted intents to a transactional outbox.

Callers must prepare before mutation and commit the outbox in the SAME DB
transaction as that mutation. Publishing uses a separate session AFTER commit.
No application route calls this module yet. It does not prove event coverage,
backup checkpoints, a durable external watermark, or authorization to restore.
"""

import asyncio
import hashlib
import os
import re
import threading
import uuid

from sqlalchemy import func, select, text, tuple_

from src.core.utils import utcnow
from src.models.db import PrivacyJournalOutbox, PrivacyJournalRetryCursor
from src.services.privacy_journal import (
    ConsentState, CredentialState, DeletionReceipt, JournalEntry, PrivacyJournal,
    RESOURCE_ACTIONS, consent_state_from_payload, consent_state_to_payload,
    credential_state_from_payload, credential_state_to_payload,
    deletion_receipt_from_payload, deletion_receipt_to_payload,
)


class PrivacyOutboxError(RuntimeError):
    """Record could not be safely prepared or published; keep restores isolated."""


class DisposableMemoryJournalStore:
    """Isolated in-process store for fenced recovery tests; never reaches a provider."""

    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

    def create(self, name, data):
        with self.lock:
            if name in self.data:
                raise RuntimeError('duplicate')
            self.data[name] = data

    def read(self, name):
        with self.lock:
            return self.data[name]

    def list_names(self, prefix):
        with self.lock:
            return [name for name in self.data if name.startswith(prefix)]


_USER_KEY = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_ACTIONS = {'account_delete', 'consent_revoke', 'consent_grant', 'photo_revoke', 'credential_revoke'} | RESOURCE_ACTIONS
_FENCE_KEY = int.from_bytes(hashlib.sha256(b'storybook:privacy-journal-writer-fence:v1').digest()[:8], 'big', signed=True)


async def prepare_privacy_event(db, journal: PrivacyJournal, *, user_key: str, action: str,
                                credential_state: CredentialState | None = None,
                                resource_id: str | None = None,
                                consent_state: ConsentState | None = None,
                                deletion_receipt: DeletionReceipt | None = None) -> str:
    """Write encrypted intent first; add an outbox row without committing it."""
    if (not isinstance(user_key, str) or not _USER_KEY.fullmatch(user_key)
            or not isinstance(action, str) or action not in _ACTIONS):
        raise PrivacyOutboxError('Invalid privacy event')
    try:
        if credential_state is not None and action != 'credential_revoke':
            raise ValueError('invalid action')
        if (action in RESOURCE_ACTIONS) != (isinstance(resource_id, str) and bool(re.fullmatch('[A-Za-z0-9_-]{1,60}', resource_id))):
            raise ValueError('invalid resource')
        if action not in RESOURCE_ACTIONS and resource_id is not None:
            raise ValueError('invalid resource')
        consent_payload = consent_state_to_payload(consent_state)
        if (action == 'consent_grant') != (consent_payload is not None):
            raise ValueError('invalid consent state')
        payload = credential_state_to_payload(credential_state)
        receipt_payload = deletion_receipt_to_payload(deletion_receipt)
        if receipt_payload is not None and action != 'book_delete':
            raise ValueError('invalid deletion receipt')
    except Exception:
        raise PrivacyOutboxError('Invalid privacy event') from None
    dialect = db.get_bind().dialect.name
    if dialect == 'postgresql':
        # Recovery can acquire this same lock exclusively after all current
        # writers complete and before any new writer starts.
        await db.execute(text('SELECT pg_advisory_xact_lock_shared(:lock_key)'), {'lock_key': _FENCE_KEY})
        digest = hashlib.sha256(f'storybook:privacy-journal:v1:{user_key}'.encode()).digest()
        lock_key = int.from_bytes(digest[:8], 'big', signed=True)
        await db.execute(text('SELECT pg_advisory_xact_lock(:lock_key)'), {'lock_key': lock_key})
    elif dialect != 'sqlite' or os.environ.get('TESTING', '').lower() != 'true':
        raise PrivacyOutboxError('Unsupported database for privacy journal')
    # PostgreSQL's transaction-scoped advisory lock serializes revision
    # allocation for a user, including the interval before their first row.
    previous = await db.scalar(select(func.max(PrivacyJournalOutbox.revision)).where(
        PrivacyJournalOutbox.user_key == user_key))
    revision = (previous or 0) + 1
    event_id = uuid.uuid4().hex
    try:
        await asyncio.to_thread(journal.begin, action, user_key, revision=revision, event_id=event_id,
                                credential_state=credential_state, resource_id=resource_id,
                                consent_state=consent_state, deletion_receipt=deletion_receipt)
    except Exception:
        raise PrivacyOutboxError('Privacy event intent could not be preserved') from None
    db.add(PrivacyJournalOutbox(event_id=event_id, user_key=user_key, revision=revision,
                                action=action, credential_state=payload, resource_id=resource_id,
                                consent_state=consent_payload, deletion_receipt=receipt_payload))
    # Caller owns flush/commit. A rollback or crash leaves an unresolved external
    # intent, which must keep restoration blocked until it is reconciled.
    return event_id


async def resolve_abandoned_fixture(db, journal: PrivacyJournal, event_id: str) -> None:
    """Resolve one orphan only in a disposable local PostgreSQL fixture.

    Live use needs independent proof of the authoritative primary and that all
    writers participate in this fence; neither is established here.
    """
    url = db.get_bind().url
    if not (os.environ.get('TESTING', '').lower() == 'true' and url.drivername == 'postgresql+asyncpg'
            and url.host == '127.0.0.1' and url.username == 'runtime_test'
            and url.password == 'disposable-runtime-password' and url.database == 'runtime_test'
            and isinstance(journal, PrivacyJournal)
            and type(journal._store) is DisposableMemoryJournalStore):
        raise PrivacyOutboxError('Abandoned-event resolution is fixture-only')
    if not isinstance(event_id, str) or not re.fullmatch('[0-9a-f]{32}', event_id) or db.in_transaction():
        raise PrivacyOutboxError('Invalid abandoned-event resolution request')
    try:
        await db.execute(text('SELECT pg_advisory_xact_lock(:lock_key)'), {'lock_key': _FENCE_KEY})
        if await db.get(PrivacyJournalOutbox, event_id) is not None:
            raise PrivacyOutboxError('A committed event cannot be abandoned')
        await asyncio.to_thread(journal._abort_uncommitted, event_id)
    except PrivacyOutboxError:
        raise
    except Exception:
        raise PrivacyOutboxError('Abandoned event could not be resolved') from None
    finally:
        await db.rollback()


async def publish_privacy_event(session_factory, journal: PrivacyJournal, event_id: str) -> None:
    """Publish one previously committed outbox entry using an independent session."""
    if not isinstance(event_id, str) or not re.fullmatch('[0-9a-f]{32}', event_id):
        raise PrivacyOutboxError('Invalid privacy event identifier')
    try:
        async with session_factory() as db:
            row = await db.scalar(select(PrivacyJournalOutbox).where(
                PrivacyJournalOutbox.event_id == event_id).with_for_update())
            if row is None:
                raise PrivacyOutboxError('Committed privacy event was not found')
            expected = JournalEntry(row.event_id, row.action, row.user_key, row.revision,
                                    credential_state_from_payload(row.credential_state), row.resource_id,
                                    consent_state_from_payload(row.consent_state),
                                    deletion_receipt_from_payload(row.deletion_receipt))
            await asyncio.to_thread(journal.commit, event_id, expected=expected)
            if row.published_at is None:
                row.published_at = utcnow()
                await db.commit()
    except PrivacyOutboxError:
        raise
    except Exception:
        raise PrivacyOutboxError('Privacy event publication failed') from None


async def _claim_fair_batch(session_factory, limit):
    """Persist a bounded sweep before work; failed/crashed claims recur next sweep.

    A fixed upper bound makes each sweep finite even if new events arrive
    continuously. The database lock serializes cursor movement across workers.
    It is not a delivery lease or proof of external publication.
    """
    async with session_factory() as db:
        async with db.begin():
            if db.get_bind().dialect.name not in ('postgresql', 'sqlite'):
                raise PrivacyOutboxError('Unsupported privacy retry database')
            await db.execute(text("INSERT INTO privacy_journal_retry_cursor (name) VALUES ('outbox') "
                                  "ON CONFLICT (name) DO NOTHING"))
            cursor = await db.scalar(select(PrivacyJournalRetryCursor).where(
                PrivacyJournalRetryCursor.name == 'outbox').with_for_update())
            if cursor is None:
                raise PrivacyOutboxError('Privacy retry cursor is unavailable')
            position = tuple_(PrivacyJournalOutbox.created_at, PrivacyJournalOutbox.event_id)
            base = select(PrivacyJournalOutbox.created_at, PrivacyJournalOutbox.event_id).where(
                PrivacyJournalOutbox.published_at.is_(None))

            async def next_rows():
                statement = base
                if cursor.upper_created_at is not None:
                    statement = statement.where(position <= (cursor.upper_created_at, cursor.upper_event_id))
                if cursor.cursor_created_at is not None:
                    statement = statement.where(position > (cursor.cursor_created_at, cursor.cursor_event_id))
                return list((await db.execute(statement.order_by(
                    PrivacyJournalOutbox.created_at, PrivacyJournalOutbox.event_id).limit(limit))).all())

            rows = await next_rows() if cursor.upper_created_at is not None else []
            if not rows:
                upper = (await db.execute(base.order_by(PrivacyJournalOutbox.created_at.desc(),
                    PrivacyJournalOutbox.event_id.desc()).limit(1))).first()
                cursor.cursor_created_at = cursor.cursor_event_id = None
                cursor.upper_created_at, cursor.upper_event_id = upper if upper is not None else (None, None)
                rows = await next_rows() if upper is not None else []
            if rows:
                cursor.cursor_created_at, cursor.cursor_event_id = rows[-1]
            return [row.event_id for row in rows]


async def publish_pending_events(session_factory, journal: PrivacyJournal, *, limit: int = 100) -> int:
    """Retry a bounded batch; any failure remains pending and fails the batch.

    A damaged record must not prevent unrelated events from being attempted.
    Cursor rotation persists across workers and restarts; it does not prove
    independent latest-history durability or guarantee progress during outage.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise PrivacyOutboxError('Invalid privacy event batch size')
    try:
        ids = await _claim_fair_batch(session_factory, limit)
        completed = 0
        failed = False
        for event_id in ids:
            try:
                await publish_privacy_event(session_factory, journal, event_id)
                completed += 1
            except PrivacyOutboxError:
                failed = True
        if failed:
            raise PrivacyOutboxError('Privacy event recovery incomplete')
        return completed
    except PrivacyOutboxError:
        raise
    except Exception:
        raise PrivacyOutboxError('Privacy event recovery failed') from None
