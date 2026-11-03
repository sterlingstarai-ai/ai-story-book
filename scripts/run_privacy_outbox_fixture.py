"""PostgreSQL concurrency check in the disposable loopback fixture only."""

import asyncio
import importlib.util
import os
from pathlib import Path

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    from sqlalchemy import delete
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.exceptions import APIError
    from src.models.db import AccountIdentity, Book, BookShare, ChildProfile, Job, PrivacyJournalOutbox, StoragePurgeTask
    from src.routers.profiles import delete_profile
    from src.routers.shares import revoke_share
    from src.routers.users import delete_my_data
    from src.services.account_recovery import credential_hash, issue_recovery_code
    from src.services.privacy_journal import PrivacyJournal
    from src.services.privacy_journal_outbox import (
        DisposableMemoryJournalStore, PrivacyOutboxError, _claim_fair_batch, prepare_privacy_event, publish_pending_events,
        resolve_abandoned_fixture,
    )
    from src.services.privacy_journal_verify import (
        JournalVerificationError, verify_backup_checkpoint, verify_current_outbox,
    )
    from src.services.privacy_restore_source_guard import hold_consistent_source
    from src.services.privacy_journal_backfill_guard import backfill_with_source_fence

    owner = '00000000-0000-4000-8000-000000000099'
    journal = PrivacyJournal(DisposableMemoryJournalStore(), os.urandom(32))

    async def create_event(action):
        async with AsyncSessionLocal() as session:
            await prepare_privacy_event(session, journal, user_key=owner, action=action)
            # Keep the transaction open briefly so a competing transaction
            # must wait for the same account's advisory lock.
            await asyncio.sleep(0.1)
            await session.commit()

    try:
        await asyncio.gather(create_event('consent_revoke'), create_event('credential_revoke'))
        if await publish_pending_events(AsyncSessionLocal, journal) != 2:
            raise RuntimeError('Synthetic committed events were not published')
        scan = journal.scan()
        if sorted(entry.revision for entry in scan.committed) != [1, 2] or scan.pending_count:
            raise RuntimeError('Synthetic concurrent revisions were not serialized')
        async with AsyncSessionLocal() as session:
            before = await verify_current_outbox(session, scan)
            marker = {'journal_event_count': before['event_count'], 'journal_sha256': before['journal_sha256'],
                      'restore_authorized': False}
            result = await verify_backup_checkpoint(session, scan, marker)
            if result['event_count'] != 2 or result['restore_authorized'] is not False:
                raise RuntimeError('Synthetic checkpoint validation failed')
            try:
                await verify_backup_checkpoint(session, scan, dict(marker, journal_sha256='0' * 64))
            except JournalVerificationError:
                pass
            else:
                raise RuntimeError('Tampered synthetic checkpoint was accepted')
        witness = DisposableMemoryJournalStore()
        async with AsyncSessionLocal() as session:
            copied = await backfill_with_source_fence(session, journal, witness)
            if (copied != {'status': 'FENCED_BACKFILL_MATCHES', 'event_count': 2,
                           'object_count': 4, 'restore_authorized': False}
                    or journal._store.data != witness.data):
                raise RuntimeError('Fenced synthetic backfill failed')
        # The source consistency fence must remain held for the entire
        # protected section, not merely while collecting the first scan.
        writer_started = asyncio.Event()
        async def attempt_fenced_event():
            writer_started.set()
            await create_event('consent_revoke')
        async with AsyncSessionLocal() as session:
            async with hold_consistent_source(session, journal) as (checkpoint, _scan):
                if checkpoint['event_count'] != 2 or checkpoint['restore_authorized'] is not False:
                    raise RuntimeError('Source checkpoint was invalid')
                writer = asyncio.create_task(attempt_fenced_event())
                await asyncio.wait_for(writer_started.wait(), timeout=5)
                await asyncio.sleep(0.2)
                if writer.done():
                    raise RuntimeError('Privacy writer escaped the source fence')
            await asyncio.wait_for(writer, timeout=10)
        if await publish_pending_events(AsyncSessionLocal, journal) != 1:
            raise RuntimeError('Fenced synthetic writer was not released')
        async with AsyncSessionLocal() as session:
            abandoned = await prepare_privacy_event(session, journal, user_key=owner, action='account_delete')
            await session.rollback()
        if journal.scan().pending_count != 1:
            raise RuntimeError('Synthetic rolled-back intent did not remain unresolved')
        async with AsyncSessionLocal() as session:
            try:
                await resolve_abandoned_fixture(session, journal, scan.committed[0].event_id)
            except PrivacyOutboxError:
                pass
            else:
                raise RuntimeError('Committed journal event was incorrectly abandoned')
        writer_started = asyncio.Event()
        release_writer = asyncio.Event()
        resolver_done = asyncio.Event()

        async def fenced_writer():
            async with AsyncSessionLocal() as session:
                event = await prepare_privacy_event(session, journal, user_key=owner, action='consent_revoke')
                writer_started.set()
                await release_writer.wait()
                await session.commit()
            from src.services.privacy_journal_outbox import publish_privacy_event
            await publish_privacy_event(AsyncSessionLocal, journal, event)

        async def fenced_resolver():
            async with AsyncSessionLocal() as session:
                await resolve_abandoned_fixture(session, journal, abandoned)
                resolver_done.set()

        writer_task = asyncio.create_task(fenced_writer())
        await asyncio.wait_for(writer_started.wait(), timeout=10)
        resolver_task = asyncio.create_task(fenced_resolver())
        await asyncio.sleep(0.2)
        if resolver_done.is_set():
            raise RuntimeError('Orphan resolution did not wait for a live writer')
        release_writer.set()
        await asyncio.wait_for(asyncio.gather(writer_task, resolver_task), timeout=20)
        if journal.scan().pending_count:
            raise RuntimeError('Fenced abandoned event was not resolved')

        # A permanently failing event must not prevent later selected events
        # from being published, even when two recovery loops overlap. The batch
        # itself remains failed and the original event remains pending.
        async with AsyncSessionLocal() as session:
            blocked = await prepare_privacy_event(session, journal, user_key=owner, action='consent_revoke')
            await session.commit()
        async with AsyncSessionLocal() as session:
            later = await prepare_privacy_event(session, journal, user_key=owner, action='credential_revoke')
            await session.commit()
        original_commit = journal.commit
        def selectively_fail(event_id, **kwargs):
            if event_id == blocked:
                raise RuntimeError('synthetic event publication outage')
            return original_commit(event_id, **kwargs)
        journal.commit = selectively_fail
        outcomes = await asyncio.wait_for(asyncio.gather(
            publish_pending_events(AsyncSessionLocal, journal),
            publish_pending_events(AsyncSessionLocal, journal), return_exceptions=True), timeout=20)
        if not all(isinstance(value, PrivacyOutboxError) for value in outcomes):
            raise RuntimeError('Incomplete synthetic batch was accepted')
        async with AsyncSessionLocal() as session:
            blocked_row = await session.get(PrivacyJournalOutbox, blocked)
            later_row = await session.get(PrivacyJournalOutbox, later)
            if blocked_row.published_at is not None or later_row.published_at is None:
                raise RuntimeError('Synthetic independent event retry did not complete safely')
        if journal.scan().pending_count != 1:
            raise RuntimeError('Synthetic failed event was not left pending')
        journal.commit = original_commit
        if await publish_pending_events(AsyncSessionLocal, journal) != 1 or journal.scan().pending_count:
            raise RuntimeError('Synthetic failed event could not be retried')
        revisions = sorted(entry.revision for entry in journal.scan().committed if entry.subject == owner)
        if revisions != list(range(1, len(revisions) + 1)):
            raise RuntimeError('Synthetic concurrent recovery changed event ordering')

        fairness_events = []
        for action in ('consent_revoke', 'consent_revoke', 'credential_revoke'):
            async with AsyncSessionLocal() as session:
                fairness_events.append(await prepare_privacy_event(session, journal, user_key=owner, action=action))
                await session.commit()
        def fail_first_two(event_id, **kwargs):
            if event_id in fairness_events[:2]:
                raise RuntimeError('synthetic persistent outage')
            return original_commit(event_id, **kwargs)
        journal.commit = fail_first_two
        try:
            await publish_pending_events(AsyncSessionLocal, journal, limit=2)
        except PrivacyOutboxError:
            pass
        else:
            raise RuntimeError('Synthetic permanently failing batch was accepted')
        if await publish_pending_events(AsyncSessionLocal, journal, limit=2) != 1:
            raise RuntimeError('Persistent failed batch starved later synthetic event')
        # Claim and abandon work to simulate a process crash after cursor commit.
        abandoned_batch = await _claim_fair_batch(AsyncSessionLocal, 2)
        if set(abandoned_batch) != set(fairness_events[:2]):
            raise RuntimeError('Synthetic retry sweep did not wrap')
        journal.commit = original_commit
        if await publish_pending_events(AsyncSessionLocal, journal, limit=2) != 2:
            raise RuntimeError('Abandoned synthetic retry batch was not revisited')
        if journal.scan().pending_count:
            raise RuntimeError('Synthetic fairness retry left unexpected pending events')

        # Use PostgreSQL savepoints to test migration rollback behavior without
        # changing the fixture schema or removing any committed journal rows.
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        migration_path = (Path(__file__).resolve().parents[1] / 'apps/api/alembic/versions/'
                          '4c2d8f71b906_privacy_retry_fairness.py')
        spec = importlib.util.spec_from_file_location('synthetic_retry_migration', migration_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def run_downgrade(sync_session):
            with Operations.context(MigrationContext.configure(sync_session.connection())):
                migration.downgrade()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                try:
                    async with session.begin_nested():
                        session.add(PrivacyJournalOutbox(event_id='f' * 32, user_key=owner,
                            revision=99999, action='consent_revoke'))
                        await session.flush()
                        await session.run_sync(run_downgrade)
                except RuntimeError as exc:
                    if 'publication remains pending' not in str(exc):
                        raise
                else:
                    raise RuntimeError('Synthetic downgrade accepted pending events')
                savepoint = await session.begin_nested()
                await session.run_sync(run_downgrade)
                await savepoint.rollback()

        concurrent_events = []
        for action in ('consent_revoke', 'consent_revoke', 'consent_revoke', 'credential_revoke'):
            async with AsyncSessionLocal() as session:
                concurrent_events.append(await prepare_privacy_event(session, journal, user_key=owner, action=action))
                await session.commit()
        claimed = await asyncio.wait_for(asyncio.gather(
            _claim_fair_batch(AsyncSessionLocal, 2), _claim_fair_batch(AsyncSessionLocal, 2)), timeout=20)
        if (len(claimed[0]) != 2 or len(claimed[1]) != 2 or set(claimed[0]) & set(claimed[1])
                or set(claimed[0] + claimed[1]) != set(concurrent_events)):
            raise RuntimeError('Concurrent synthetic workers did not claim distinct retry ranges')
        if await publish_pending_events(AsyncSessionLocal, journal, limit=4) != 4:
            raise RuntimeError('Synthetic claimed retry ranges were not revisited')
        route_owner = '00000000-0000-4000-8000-000000000098'
        route_journal = PrivacyJournal(DisposableMemoryJournalStore(), os.urandom(32))
        async with AsyncSessionLocal() as session:
            session.add_all([ChildProfile(id='concurrent-profile-a', user_key=route_owner, name='A'),
                             ChildProfile(id='concurrent-profile-b', user_key=route_owner, name='B')])
            await session.commit()

        async def delete_one(profile_id):
            async with AsyncSessionLocal() as session:
                session.info['privacy_journal'] = route_journal
                await delete_profile(profile_id, db=session, user_key=route_owner)

        await asyncio.gather(delete_one('concurrent-profile-a'), delete_one('concurrent-profile-b'))
        entries = sorted(route_journal.scan().committed, key=lambda entry: entry.revision)
        if [entry.revision for entry in entries] != [1, 2] or {entry.resource_id for entry in entries} != {
            'concurrent-profile-a', 'concurrent-profile-b',
        }:
            raise RuntimeError('Concurrent route events were not preserved in order')
        identity_owner = '00000000-0000-4000-8000-000000000097'
        identity_journal = PrivacyJournal(DisposableMemoryJournalStore(), os.urandom(32))
        async with AsyncSessionLocal() as session:
            session.add(AccountIdentity(user_key=identity_owner,
                device_key_hash=credential_hash(identity_owner, kind='device'), deleted=False))
            await session.commit()

        async def rotate_or_delete(delete_account):
            async with AsyncSessionLocal() as session:
                session.info['privacy_journal'] = identity_journal
                try:
                    if delete_account:
                        await delete_my_data(db=session, user_key=identity_owner, x_user_key=identity_owner)
                    else:
                        await issue_recovery_code(session, identity_owner, identity_owner)
                except APIError:
                    if delete_account:
                        raise

        await asyncio.wait_for(asyncio.gather(rotate_or_delete(False), rotate_or_delete(True)), timeout=25)
        async with AsyncSessionLocal() as session:
            if not (await session.get(AccountIdentity, identity_owner)).deleted:
                raise RuntimeError('Concurrent account deletion did not persist')
        if identity_journal.scan().pending_count:
            raise RuntimeError('Concurrent credential rotation left an unresolved intent')
        share_owner = '00000000-0000-4000-8000-000000000096'
        share_journal = PrivacyJournal(DisposableMemoryJournalStore(), os.urandom(32))
        async with AsyncSessionLocal() as session:
            session.add(Job(id='share-job-fixture', status='done', user_key=share_owner))
            await session.flush()
            session.add(Book(id='share-book-fixture', job_id='share-job-fixture', user_key=share_owner,
                title='Synthetic', language='ko', target_age='3-5', style='watercolor'))
            await session.flush()
            session.add(BookShare(id='share-token-fixture', book_id='share-book-fixture', user_key=share_owner))
            await session.commit()
            session.info['privacy_journal'] = share_journal
            await revoke_share('share-book-fixture', db=session, user_key=share_owner)
            if (await session.get(BookShare, 'share-token-fixture')).revoked_at is None:
                raise RuntimeError('Synthetic share was not revoked')
        if [entry.action for entry in share_journal.scan().committed] != ['share_revoke']:
            raise RuntimeError('Synthetic share revocation was not journaled')
        async with AsyncSessionLocal() as session:
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == route_owner))
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == identity_owner))
            await session.execute(delete(StoragePurgeTask).where(StoragePurgeTask.user_key == identity_owner))
            await session.execute(delete(AccountIdentity).where(AccountIdentity.user_key == identity_owner))
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == share_owner))
            await session.execute(delete(BookShare).where(BookShare.user_key == share_owner))
            await session.execute(delete(Book).where(Book.user_key == share_owner))
            await session.execute(delete(Job).where(Job.user_key == share_owner))
            await session.commit()
        print('Synthetic PostgreSQL concurrent revisions serialized; fenced rollback recovery and committed-event rejection passed')
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
