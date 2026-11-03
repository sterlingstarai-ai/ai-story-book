import asyncio
from contextlib import asynccontextmanager
import hashlib
import threading

import pytest

from src.services import privacy_journal_checkpoint as checkpoints
from src.services.privacy_journal import JournalEntry, JournalError, JournalScan, PrivacyJournal
from src.services.privacy_journal_outbox import DisposableMemoryJournalStore
from src.services.privacy_journal_verify import fingerprint_entries


NAMESPACE = 'b' * 32
KEY = b'w' * 32
USER = '7c1d9999-9999-4999-8999-999999999999'


def event(number, *, action='consent_revoke'):
    return JournalEntry(f'{number:032x}', action, USER, number)


def checkpoint(scan):
    return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': len(scan.committed),
            'journal_sha256': fingerprint_entries(scan.committed), 'restore_authorized': False}


def issue(witness, scan):
    name, value = checkpoints._encode(NAMESPACE, 1, KEY, checkpoint(scan), scan, 100)
    witness.create(name, value)
    return hashlib.sha256(value).hexdigest()


def verify(witness, scan, digest, **kwargs):
    return checkpoints.verify_checkpoint_extension(witness, scan, namespace=NAMESPACE, generation=1,
        expected_sha256=digest, key=KEY, now=110, max_age=20, **kwargs)


def test_matching_prefix_accepts_later_events_without_authorizing_restore():
    witness = DisposableMemoryJournalStore()
    digest = issue(witness, JournalScan((event(1), event(2)), 0))
    result = verify(witness, JournalScan((event(1), event(2), event(3)), 0), digest)
    assert result == {'status': 'WITNESSED_PREFIX_MATCHES', 'checkpoint_count': 2,
                      'journal_count': 3, 'restore_authorized': False}
    # Both the identifiers and sensitive journal payload remain encrypted.
    blob = next(iter(witness.data.values()))
    assert USER.encode() not in blob and event(1).event_id.encode() not in blob


@pytest.mark.parametrize('candidate', [
    JournalScan((event(1),), 0),                         # lost checkpoint event
    JournalScan((event(1), event(2, action='photo_revoke')), 0),  # changed content
    JournalScan((event(1), event(3)), 0),                # revision gap
    JournalScan((event(1), event(2), event(2)), 0),      # duplicate
    JournalScan((event(1), event(2)), 1),                # unresolved intent
])
def test_missing_modified_gapped_duplicate_or_pending_events_fail(candidate):
    witness = DisposableMemoryJournalStore()
    digest = issue(witness, JournalScan((event(1), event(2)), 0))
    with pytest.raises(JournalError):
        verify(witness, candidate, digest)


def test_stale_changed_or_wrong_reference_fails_closed():
    witness = DisposableMemoryJournalStore()
    scan = JournalScan((event(1),), 0)
    digest = issue(witness, scan)
    with pytest.raises(JournalError):
        checkpoints.verify_checkpoint_extension(witness, scan, namespace=NAMESPACE, generation=1,
            expected_sha256=digest, key=KEY, now=121, max_age=20)
    with pytest.raises(JournalError):
        verify(witness, scan, '0' * 64)
    with pytest.raises(JournalError):
        checkpoints.verify_checkpoint_extension(witness, scan, namespace=NAMESPACE, generation=1,
            expected_sha256=digest, key=b'x' * 32, now=110, max_age=20)
    name = next(iter(witness.data))
    witness.data[name] = witness.data[name][:-1] + bytes([witness.data[name][-1] ^ 1])
    with pytest.raises(JournalError):
        verify(witness, scan, digest)


@pytest.mark.asyncio
async def test_capture_fences_source_and_stores_checkable_witness(monkeypatch):
    source, witness = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    journal = PrivacyJournal(source, b'j' * 32)
    scan = JournalScan((event(1),), 0)
    state = []

    @asynccontextmanager
    async def fake_fence(db, supplied):
        assert supplied is journal
        state.append('held')
        yield checkpoint(scan), scan
        assert len(witness.data) == 1
        state.append('released')

    monkeypatch.setattr(checkpoints, 'hold_consistent_source', fake_fence)
    result = await checkpoints.capture_fenced_checkpoint(object(), journal, witness,
        namespace=NAMESPACE, generation=1, key=KEY, now=100)
    assert state == ['held', 'released']
    assert result['restore_authorized'] is False
    assert verify(witness, scan, result['sha256'])['status'] == 'WITNESSED_PREFIX_MATCHES'


@pytest.mark.asyncio
async def test_cancellation_does_not_release_source_fence_during_witness_write(monkeypatch):
    source, witness = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    journal = PrivacyJournal(source, b'j' * 32)
    scan = JournalScan((), 0)
    entered, finish, released = threading.Event(), threading.Event(), asyncio.Event()

    @asynccontextmanager
    async def fake_fence(db, supplied):
        try:
            yield checkpoint(scan), scan
        finally:
            released.set()

    def slow_store(*args):
        entered.set()
        if not finish.wait(5):
            raise RuntimeError('timeout')
        return '0' * 64

    monkeypatch.setattr(checkpoints, 'hold_consistent_source', fake_fence)
    monkeypatch.setattr(checkpoints, '_store_checkpoint', slow_store)
    task = asyncio.create_task(checkpoints.capture_fenced_checkpoint(object(), journal, witness,
        namespace=NAMESPACE, generation=1, key=KEY, now=100))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(.05)
        task.cancel()
        await asyncio.sleep(.05)
        assert not released.is_set()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert released.is_set()
    finally:
        finish.set()
