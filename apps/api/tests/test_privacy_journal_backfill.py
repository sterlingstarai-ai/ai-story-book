import pytest

from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_backfill import backfill_fenced_journal
from src.services.privacy_journal_mirror import MirroredJournalStore
from src.services.privacy_journal_outbox import DisposableMemoryJournalStore


OWNER = '00000000-0000-4000-8000-000000000001'


def test_backfill_is_idempotent_and_preserves_encrypted_records():
    source, witness = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    source_journal = PrivacyJournal(source, b'k' * 32)
    event = source_journal.begin('consent_revoke', OWNER, revision=1)
    source_journal.commit(event)
    for _ in range(2):
        assert backfill_fenced_journal(source, witness) == {
            'status': 'BACKFILL_MATCHES', 'object_count': 2, 'restore_authorized': False}
    assert source.data == witness.data
    assert len(PrivacyJournal(MirroredJournalStore(source, witness), b'k' * 32).scan().committed) == 1


def test_backfill_rejects_conflicts_and_unexpected_witness_objects():
    source, witness = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    name = 'privacy-journal/v1/' + 'a' * 32 + '/intent'
    source.create(name, b'correct')
    witness.create(name, b'wrong')
    with pytest.raises(JournalError):
        backfill_fenced_journal(source, witness)
    assert witness.read(name) == b'wrong'
    witness.create('privacy-journal/v1/' + 'b' * 32 + '/intent', b'extra')
    with pytest.raises(JournalError):
        backfill_fenced_journal(source, witness)


def test_backfill_rejects_source_changes():
    class ChangingStore(DisposableMemoryJournalStore):
        calls = 0
        def list_names(self, prefix):
            self.calls += 1
            if self.calls == 2:
                self.create(prefix + 'b' * 32 + '/intent', b'new')
            return super().list_names(prefix)

    source, witness = ChangingStore(), DisposableMemoryJournalStore()
    source.create('privacy-journal/v1/' + 'a' * 32 + '/intent', b'old')
    with pytest.raises(JournalError):
        backfill_fenced_journal(source, witness)
