"""Isolated evidence for journal confidentiality and failure handling only."""

import importlib

import pytest


@pytest.fixture
def journal_module(monkeypatch):
    return importlib.import_module('src.services.privacy_journal')


class FakeStore:
    def __init__(self):
        self.objects = {}

    def create(self, name, data):
        if name in self.objects:
            raise RuntimeError('create-only precondition failed')
        self.objects[name] = data

    def read(self, name):
        return self.objects[name]

    def list_names(self, prefix):
        return [name for name in self.objects if name.startswith(prefix)]


def test_resource_events_are_encrypted_and_require_exact_resource(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    subject = '00000000-0000-4000-8000-000000000001'
    with pytest.raises(journal_module.JournalError):
        journal.begin('book_delete', subject, revision=1)
    with pytest.raises(journal_module.JournalError):
        journal.begin('account_delete', subject, revision=1, resource_id='book_secret')
    event = journal.begin('book_delete', subject, revision=1, resource_id='book_secret')
    assert all(b'book_secret' not in value for value in store.objects.values())
    journal.commit(event)
    entry = journal.scan().committed[0]
    assert entry.resource_id == 'book_secret'
    assert 'book_secret' not in repr(entry)


def test_consent_regrant_requires_authentic_complete_state(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    subject = '00000000-0000-4000-8000-000000000001'
    with pytest.raises(journal_module.JournalError):
        journal.begin('consent_grant', subject, revision=1)
    state = journal_module.ConsentState(True, True, True, 'v2')
    event = journal.begin('consent_grant', subject, revision=1, consent_state=state)
    journal.commit(event)
    assert journal.scan().committed[0].consent_state == state


def test_fenced_abort_is_immutable_and_never_authorizes_restore(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    subject = '00000000-0000-4000-8000-000000000001'
    event = journal.begin('account_delete', subject, revision=1)
    journal._abort_uncommitted(event)
    journal._abort_uncommitted(event)
    assert journal.scan().pending_count == 0 and not journal.scan().committed
    assert journal.scan().restore_authorized is False
    with pytest.raises(journal_module.JournalError):
        journal.commit(event)
    with pytest.raises(journal_module.JournalError):
        journal.begin('account_delete', subject, revision=1, event_id=event)
    abort_name = next(name for name in store.objects if name.endswith('/abort'))
    store.objects[abort_name] = b'tampered'
    with pytest.raises(journal_module.JournalError):
        journal.scan()


def test_encrypted_intent_and_commit_scan_never_authorizes_restore(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    subject = '00000000-0000-4000-8000-000000000001'
    event = journal.begin('account_delete', subject, revision=1)
    assert all(subject.encode() not in data for data in store.objects.values())
    assert all(subject not in name for name in store.objects)
    assert journal.scan().pending_count == 1
    journal.commit(event)
    result = journal.scan()
    assert result.pending_count == 0
    assert [(e.action, e.subject) for e in result.committed] == [('account_delete', subject)]
    assert result.restore_authorized is False
    assert subject not in repr(result)


def test_unresolved_intent_and_duplicate_commit(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    first = journal.begin('consent_revoke', '00000000-0000-4000-8000-000000000010', revision=1)
    journal.begin('credential_revoke', '00000000-0000-4000-8000-000000000010', revision=2)
    journal.commit(first)
    commit_name = next(name for name in store.objects if name.endswith('/commit'))
    original = store.objects[commit_name]
    journal.commit(first)
    assert store.objects[commit_name] == original
    assert journal.scan().pending_count == 1


def test_ambiguous_write_is_reconciled_and_id_reuse_conflicts(journal_module):
    class LostResponseStore(FakeStore):
        def create(self, name, data):
            super().create(name, data)
            raise TimeoutError('response lost after write')

    store = LostResponseStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    event_id = 'a' * 32
    assert journal.begin('account_delete', '00000000-0000-4000-8000-000000000011', revision=1, event_id=event_id) == event_id
    journal.commit(event_id)
    assert len(journal.scan().committed) == 1
    with pytest.raises(journal_module.JournalError):
        journal.begin('account_delete', '00000000-0000-4000-8000-000000000012', revision=1, event_id=event_id)


def test_unreadable_intent_blocks_then_preserves_pending_until_exact_retry(journal_module):
    class TemporarilyUnreadable(FakeStore):
        unavailable = True
        def read(self, name):
            if self.unavailable:
                raise RuntimeError('synthetic read outage')
            return super().read(name)

    store = TemporarilyUnreadable()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    event_id = 'f' * 32
    subject = '00000000-0000-4000-8000-000000000011'
    with pytest.raises(journal_module.JournalError):
        journal.begin('consent_revoke', subject, revision=1, event_id=event_id)
    store.unavailable = False
    scan = journal.scan()
    assert scan.pending_count == 1 and scan.restore_authorized is False
    assert journal.begin('consent_revoke', subject, revision=1, event_id=event_id) == event_id
    journal.commit(event_id)
    assert journal.scan().pending_count == 0 and journal.scan().restore_authorized is False


def test_tampering_wrong_key_and_cross_record_swap_fail_closed(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    journal.begin('photo_revoke', '00000000-0000-4000-8000-000000000011', revision=1)
    journal.begin('photo_revoke', '00000000-0000-4000-8000-000000000012', revision=1)
    names = list(store.objects)
    with pytest.raises(journal_module.JournalError):
        journal_module.PrivacyJournal(store, b'x' * 32).scan()
    store.objects[names[0]] = store.objects[names[1]]
    with pytest.raises(journal_module.JournalError):
        journal.scan()


def test_commit_is_bound_to_exact_encrypted_intent(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    event = journal.begin('account_delete', '00000000-0000-4000-8000-000000000011', revision=1)
    journal.commit(event)
    name = next(name for name in store.objects if name.endswith('/intent'))
    store.objects[name] = journal._seal(name, {
        'id': event, 'action': 'account_delete', 'subject': '00000000-0000-4000-8000-000000000012',
        'revision': 1, 'credential_state': None,
    })
    with pytest.raises(journal_module.JournalError, match='commit is invalid'):
        journal.scan()


def test_missing_intent_unknown_objects_and_provider_failure_fail_closed(journal_module):
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    event = journal.begin('account_delete', '00000000-0000-4000-8000-000000000010', revision=1)
    journal.commit(event)
    intent = next(name for name in store.objects if name.endswith('/intent'))
    del store.objects[intent]
    with pytest.raises(journal_module.JournalError):
        journal.scan()
    store.objects.clear()
    store.objects['privacy-journal/v1/unexpected'] = b'bad'
    with pytest.raises(journal_module.JournalError):
        journal.scan()
    store.list_names = lambda _: (_ for _ in ()).throw(RuntimeError('provider secret'))
    with pytest.raises(journal_module.JournalError) as error:
        journal.scan()
    assert 'provider secret' not in str(error.value)


def test_invalid_keys_and_actions_fail_before_writing(journal_module):
    store = FakeStore()
    with pytest.raises(journal_module.JournalError):
        journal_module.PrivacyJournal(store, b'short')
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    for action, subject in [('unknown', 'synthetic'), ('account_delete', 'contains spaces')]:
        with pytest.raises(journal_module.JournalError):
            journal.begin(action, subject, revision=1)
    assert not store.objects


def test_credential_verifiers_are_encrypted_validated_and_bound(journal_module):
    from datetime import datetime
    store = FakeStore()
    journal = journal_module.PrivacyJournal(store, b'k' * 32)
    state = journal_module.CredentialState('a' * 64, 'b' * 64, None, datetime(2026, 11, 2))
    event = journal.begin('credential_revoke', '00000000-0000-4000-8000-000000000010',
                          revision=1, credential_state=state)
    journal.commit(event)
    scan = journal.scan()
    assert scan.committed[0].credential_state == state
    assert 'a' * 64 not in repr(scan)
    assert all(('a' * 64).encode() not in data for data in store.objects.values())
    with pytest.raises(journal_module.JournalError):
        journal.begin('account_delete', '00000000-0000-4000-8000-000000000010',
                      revision=2, credential_state=state)
    with pytest.raises(journal_module.JournalError):
        journal.begin('credential_revoke', '00000000-0000-4000-8000-000000000010',
                      revision=2, credential_state=journal_module.CredentialState('raw-key', None, None, None))
