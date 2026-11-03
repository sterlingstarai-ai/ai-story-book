"""Fence and verify a journal backfill; never enable or authorize restore.

Callers must separately authenticate the source DB and verify the witness is
an independent, create-only store. A mismatch leaves the witness quarantined.
"""
import asyncio

from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_backfill import backfill_fenced_journal
from src.services.privacy_restore_source_guard import hold_consistent_source


async def backfill_with_source_fence(db, source_journal, witness):
    if not isinstance(source_journal, PrivacyJournal) or source_journal._store is witness:
        raise JournalError('Independent source and witness stores are required')
    try:
        async with hold_consistent_source(db, source_journal) as (checkpoint, _scan):
            task = asyncio.create_task(asyncio.to_thread(backfill_fenced_journal, source_journal._store, witness))
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError as cancelled:
                # Cancelling a thread does not stop its writes. Do not release
                # the source fence while a background copy may still be active.
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()  # Retrieve any worker exception.
                raise cancelled
            if result.get('status') != 'BACKFILL_MATCHES' or result.get('restore_authorized') is not False:
                raise JournalError('Journal witness backfill did not verify')
            return {'status': 'FENCED_BACKFILL_MATCHES', 'event_count': checkpoint['event_count'],
                    'object_count': result['object_count'], 'restore_authorized': False}
    except JournalError:
        raise
    except Exception:
        raise JournalError('Fenced journal backfill could not be verified') from None
