"""Mirrored encrypted journal must fail closed on a missing or changed copy."""
import pytest

from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_mirror import MirroredJournalStore
from src.services.privacy_journal_outbox import DisposableMemoryJournalStore


OWNER = '00000000-0000-4000-8000-000000000001'


def test_mirrored_journal_detects_missing_and_modified_records():
    first, second = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    journal = PrivacyJournal(MirroredJournalStore(first, second), b'k' * 32)
    event = journal.begin('account_delete', OWNER, revision=1)
    journal.commit(event)
    assert len(journal.scan().committed) == 1
    name = next(key for key in second.data if key.endswith('/commit'))
    copy = second.data.pop(name)
    with pytest.raises(JournalError):
        journal.scan()
    second.data[name] = copy + b'x'
    with pytest.raises(JournalError):
        journal.scan()
    second.data[name] = copy
    assert journal.scan().restore_authorized is False


def test_create_retry_cannot_replace_existing_different_bytes():
    first, second = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    mirrored = MirroredJournalStore(first, second)
    mirrored.create('p/a', b'original')
    mirrored.create('p/a', b'original')
    with pytest.raises(JournalError):
        mirrored.create('p/a', b'different')
    assert first.data['p/a'] == second.data['p/a'] == b'original'
    with pytest.raises(JournalError):
        MirroredJournalStore(first, first)


def test_partial_write_blocks_listing_until_exact_retry():
    class TemporarilyBroken(DisposableMemoryJournalStore):
        broken = True
        def create(self, name, data):
            if self.broken:
                raise RuntimeError('unavailable')
            return super().create(name, data)

    first, second = DisposableMemoryJournalStore(), TemporarilyBroken()
    mirrored = MirroredJournalStore(first, second)
    with pytest.raises(JournalError):
        mirrored.create('p/a', b'ciphertext')
    with pytest.raises(JournalError):
        mirrored.list_names('p/')
    second.broken = False
    mirrored.create('p/a', b'ciphertext')
    assert mirrored.read('p/a') == b'ciphertext'
    assert mirrored.list_names('p/') == ['p/a']
