import asyncio
from contextlib import asynccontextmanager
import threading

import pytest

from src.services import privacy_journal_backfill_guard as guard
from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_outbox import DisposableMemoryJournalStore


@pytest.mark.asyncio
async def test_cancelled_backfill_keeps_fence_until_copy_thread_finishes(monkeypatch):
    entered = threading.Event()
    finish = threading.Event()
    released = asyncio.Event()
    source = DisposableMemoryJournalStore()
    witness = DisposableMemoryJournalStore()
    journal = PrivacyJournal(source, b'k' * 32)

    @asynccontextmanager
    async def fake_fence(db, source_journal):
        try:
            yield {'event_count': 0}, object()
        finally:
            released.set()

    def copy(_source, _witness):
        entered.set()
        if not finish.wait(5):
            raise RuntimeError('fixture timed out')
        return {'status': 'BACKFILL_MATCHES', 'object_count': 0, 'restore_authorized': False}

    monkeypatch.setattr(guard, 'hold_consistent_source', fake_fence)
    monkeypatch.setattr(guard, 'backfill_fenced_journal', copy)
    task = asyncio.create_task(guard.backfill_with_source_fence(object(), journal, witness))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not released.is_set()
        task.cancel()  # Repeated cancellation must not release the fence either.
        await asyncio.sleep(0.05)
        assert not released.is_set()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert released.is_set()
    finally:
        finish.set()


@pytest.mark.asyncio
async def test_same_store_is_never_a_witness():
    store = DisposableMemoryJournalStore()
    with pytest.raises(JournalError):
        await guard.backfill_with_source_fence(object(), PrivacyJournal(store, b'k' * 32), store)
