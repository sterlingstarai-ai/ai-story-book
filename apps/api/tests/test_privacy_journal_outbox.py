"""Synthetic transactional ordering and failure recovery for inactive outbox."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.db import AccountIdentity, PrivacyJournalOutbox
from src.services.privacy_journal import ConsentState, CredentialState, PrivacyJournal
from src.services.privacy_journal_outbox import (
    PrivacyOutboxError, prepare_privacy_event, publish_pending_events, publish_privacy_event,
)


OWNER = '00000000-0000-4000-8000-000000000011'


class FakeStore:
    def __init__(self):
        self.objects = {}
        self.fail_intent = False
        self.fail_commit = False

    def create(self, name, data):
        if (self.fail_intent and name.endswith('/intent')) or (self.fail_commit and name.endswith('/commit')):
            raise RuntimeError('synthetic outage')
        if name in self.objects:
            raise RuntimeError('already exists')
        self.objects[name] = data

    def read(self, name):
        return self.objects[name]

    def list_names(self, prefix):
        return [name for name in self.objects if name.startswith(prefix)]


@pytest.mark.asyncio
async def test_committed_mutation_and_outbox_publish_in_order(db_session):
    store = FakeStore()
    journal = PrivacyJournal(store, b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='account_delete')
    db_session.add(AccountIdentity(user_key=OWNER, deleted=True))
    await db_session.commit()
    assert journal.scan().pending_count == 1
    await publish_privacy_event(factory, journal, first)
    await publish_privacy_event(factory, journal, first)  # lost response/retry is harmless
    second = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='credential_revoke')
    await db_session.commit()
    assert await publish_pending_events(factory, journal) == 1
    scan = journal.scan()
    assert sorted(e.revision for e in scan.committed) == [1, 2]
    assert scan.pending_count == 0 and scan.restore_authorized is False
    assert (await db_session.get(AccountIdentity, OWNER)).deleted
    assert (await db_session.get(PrivacyJournalOutbox, second)).revision == 2


@pytest.mark.asyncio
async def test_rollback_keeps_external_intent_unresolved_and_prevents_publication(db_session):
    journal = PrivacyJournal(FakeStore(), b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='consent_revoke')
    db_session.add(AccountIdentity(user_key=OWNER, deleted=True))
    await db_session.rollback()
    assert await db_session.get(AccountIdentity, OWNER) is None
    assert await db_session.get(PrivacyJournalOutbox, event) is None
    assert journal.scan().pending_count == 1
    with pytest.raises(PrivacyOutboxError, match='not found'):
        await publish_privacy_event(factory, journal, event)


@pytest.mark.asyncio
async def test_external_outage_before_mutation_leaves_no_outbox_row(db_session):
    store = FakeStore()
    store.fail_intent = True
    journal = PrivacyJournal(store, b'k' * 32)
    with pytest.raises(PrivacyOutboxError, match='intent'):
        await prepare_privacy_event(db_session, journal, user_key=OWNER, action='photo_revoke')
    assert await db_session.scalar(select(PrivacyJournalOutbox.event_id)) is None


@pytest.mark.asyncio
async def test_outage_after_commit_retains_outbox_and_retry_publishes(db_session):
    store = FakeStore()
    journal = PrivacyJournal(store, b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='consent_revoke')
    await db_session.commit()
    store.fail_commit = True
    with pytest.raises(PrivacyOutboxError, match='publication failed'):
        await publish_privacy_event(factory, journal, event)
    assert journal.scan().pending_count == 1
    async with factory() as check:
        assert (await check.get(PrivacyJournalOutbox, event)).published_at is None
    store.fail_commit = False
    assert await publish_pending_events(factory, journal) == 1
    assert journal.scan().pending_count == 0


@pytest.mark.asyncio
async def test_failed_event_does_not_starve_later_selected_events(db_session, monkeypatch):
    from datetime import datetime, timedelta

    store = FakeStore()
    journal = PrivacyJournal(store, b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='consent_revoke')
    await db_session.commit()
    second = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='credential_revoke')
    await db_session.commit()
    base = datetime(2026, 1, 1)
    (await db_session.get(PrivacyJournalOutbox, first)).created_at = base
    (await db_session.get(PrivacyJournalOutbox, second)).created_at = base + timedelta(seconds=1)
    await db_session.commit()

    original = journal.commit
    def fail_first(event_id, **kwargs):
        if event_id == first:
            raise RuntimeError('synthetic persistent per-event outage')
        return original(event_id, **kwargs)
    monkeypatch.setattr(journal, 'commit', fail_first)
    with pytest.raises(PrivacyOutboxError, match='incomplete'):
        await publish_pending_events(factory, journal)
    async with factory() as check:
        assert (await check.get(PrivacyJournalOutbox, first)).published_at is None
        assert (await check.get(PrivacyJournalOutbox, second)).published_at is not None
    scan = journal.scan()
    assert scan.pending_count == 1 and scan.restore_authorized is False
    assert [entry.revision for entry in scan.committed] == [2]
    monkeypatch.setattr(journal, 'commit', original)
    assert await publish_pending_events(factory, journal) == 1
    scan = journal.scan()
    assert sorted(entry.revision for entry in scan.committed) == [1, 2]
    assert scan.pending_count == 0 and scan.restore_authorized is False


@pytest.mark.asyncio
async def test_outbox_and_authenticated_intent_mismatch_is_not_published(db_session):
    journal = PrivacyJournal(FakeStore(), b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER, action='consent_revoke')
    row = await db_session.get(PrivacyJournalOutbox, event)
    row.revision = 2
    await db_session.commit()
    with pytest.raises(PrivacyOutboxError):
        await publish_privacy_event(factory, journal, event)
    assert journal.scan().pending_count == 1


@pytest.mark.asyncio
async def test_new_credential_verifiers_are_bound_to_committed_outbox(db_session):
    store = FakeStore()
    journal = PrivacyJournal(store, b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    state = CredentialState('a' * 64, 'b' * 64, None, None)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER,
        action='credential_revoke', credential_state=state)
    await db_session.commit()
    await publish_privacy_event(factory, journal, event)
    assert journal.scan().committed[0].credential_state == state
    assert all(('a' * 64).encode() not in data for data in store.objects.values())


@pytest.mark.asyncio
async def test_resource_identifier_is_bound_to_outbox_and_immutable_intent(db_session):
    journal = PrivacyJournal(FakeStore(), b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER,
                                        action='book_delete', resource_id='book_fixture')
    row = await db_session.get(PrivacyJournalOutbox, event)
    row.resource_id = 'book_other'
    await db_session.commit()
    with pytest.raises(PrivacyOutboxError):
        await publish_privacy_event(factory, journal, event)
    assert journal.scan().pending_count == 1
    row.resource_id = 'book_fixture'
    await db_session.commit()
    await publish_privacy_event(factory, journal, event)
    assert journal.scan().committed[0].resource_id == 'book_fixture'


@pytest.mark.asyncio
async def test_consent_regrant_is_bound_to_outbox_and_immutable_intent(db_session):
    journal = PrivacyJournal(FakeStore(), b'k' * 32)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    state = ConsentState(True, True, True, 'v2')
    event = await prepare_privacy_event(db_session, journal, user_key=OWNER,
                                        action='consent_grant', consent_state=state)
    row = await db_session.get(PrivacyJournalOutbox, event)
    row.consent_state = {'privacy': True, 'photos': False, 'data_processing': True, 'version': 'v2'}
    await db_session.commit()
    with pytest.raises(PrivacyOutboxError):
        await publish_privacy_event(factory, journal, event)
    assert journal.scan().pending_count == 1
