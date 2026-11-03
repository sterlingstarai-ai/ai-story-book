"""Synthetic source consistency checks; never release a restored system."""

import hashlib
import json
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.db import PrivacyJournalOutbox
from src.services.privacy_journal import DeletionReceipt, JournalEntry, PrivacyJournal, JournalScan
from src.services.privacy_journal_outbox import prepare_privacy_event, publish_privacy_event
from src.services.privacy_journal_verify import (JournalVerificationError, fingerprint_entries,
                                                  verify_backup_checkpoint, verify_current_outbox)
from tests.test_privacy_journal_transaction import Store

OWNER = '00000000-0000-4000-8000-000000000011'


def test_old_fingerprint_remains_unchanged_and_receipt_is_bound():
    old = JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='book-a')
    previous = [{'event_id': old.event_id, 'action': old.action, 'subject': old.subject,
                 'revision': old.revision, 'credential_state': None,
                 'resource_id': old.resource_id, 'consent_state': None}]
    expected = hashlib.sha256(json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert fingerprint_entries([old]) == expected
    new = JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='book-a',
                       deletion_receipt=DeletionReceipt('b' * 32, 'profile-a'))
    changed = JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='book-a',
                           deletion_receipt=DeletionReceipt('c' * 32, 'profile-a'))
    assert fingerprint_entries([old]) != fingerprint_entries([new]) != fingerprint_entries([changed])


@pytest.mark.asyncio
async def test_exact_source_match_does_not_authorize_restore(db_session):
    journal = PrivacyJournal(Store(), b'k' * 32)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='profile_delete',
                                        resource_id='profile_fixture')
    await db_session.commit()
    with pytest.raises(JournalVerificationError):
        await verify_current_outbox(db_session, journal.scan())
    await publish_privacy_event(async_sessionmaker(db_session.bind, expire_on_commit=False), journal, event)
    result = await verify_current_outbox(db_session, journal.scan())
    assert result['event_count'] == 1 and result['restore_authorized'] is False
    with pytest.raises(JournalVerificationError):
        await verify_current_outbox(db_session, JournalScan((), 0))
    row = await db_session.get(PrivacyJournalOutbox, event)
    row.resource_id = 'different_profile'
    await db_session.commit()
    with pytest.raises(JournalVerificationError):
        await verify_current_outbox(db_session, journal.scan())


@pytest.mark.asyncio
async def test_abandoned_intent_and_database_history_gaps_block_verification(db_session):
    journal = PrivacyJournal(Store(), b'k' * 32)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='consent_revoke')
    await db_session.commit()
    await publish_privacy_event(async_sessionmaker(db_session.bind, expire_on_commit=False), journal, event)
    journal.begin('account_delete', OWNER, revision=2)
    with pytest.raises(JournalVerificationError):
        await verify_current_outbox(db_session, journal.scan())
    row = await db_session.get(PrivacyJournalOutbox, event)
    row.revision = 2
    await db_session.commit()
    with pytest.raises(JournalVerificationError):
        await verify_current_outbox(db_session, JournalScan(journal.scan().committed, 0))


@pytest.mark.asyncio
async def test_restored_checkpoint_accepts_later_events_but_rejects_missing_backup_events(db_session):
    journal = PrivacyJournal(Store(), b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='consent_revoke')
    await db_session.commit()
    await publish_privacy_event(factory, journal, first)
    before = await verify_current_outbox(db_session, journal.scan())
    marker = {'journal_event_count': before['event_count'], 'journal_sha256': before['journal_sha256'],
              'restore_authorized': False}
    second = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='account_delete')
    await db_session.commit()
    await publish_privacy_event(factory, journal, second)
    # Model an old restored backup; only the disposable test DB is changed.
    row = await db_session.get(PrivacyJournalOutbox, second)
    await db_session.delete(row)
    await db_session.commit()
    result = await verify_backup_checkpoint(db_session, journal.scan(), marker)
    assert result == {'status': 'BACKUP_CHECKPOINT_MATCHES', 'event_count': 1, 'restore_authorized': False}
    latest_only = tuple(entry for entry in journal.scan().committed if entry.event_id == second)
    with pytest.raises(JournalVerificationError):
        await verify_backup_checkpoint(db_session, JournalScan(latest_only, 0), marker)
    with pytest.raises(JournalVerificationError):
        await verify_backup_checkpoint(db_session, journal.scan(), dict(marker, journal_sha256='0' * 64))
    with pytest.raises(JournalVerificationError):
        await verify_backup_checkpoint(db_session, JournalScan(journal.scan().committed, 1), marker)
