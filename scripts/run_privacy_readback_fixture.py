"""Check journal readback failures against disposable PostgreSQL and MinIO."""
import asyncio
import os

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    import boto3
    from botocore.config import Config
    from sqlalchemy import delete, select
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.exceptions import APIError
    from src.models.db import ChildProfile, PrivacyJournalOutbox
    from src.routers.profiles import delete_profile
    from src.services.privacy_journal import PrivacyJournal
    from src.services.privacy_journal_outbox import publish_pending_events
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore

    client = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'],
        aws_access_key_id='runtime_test', aws_secret_access_key='disposable-runtime-password',
        region_name='us-east-1', config=Config(signature_version='s3v4', proxies={},
        s3={'addressing_style': 'path'}, connect_timeout=5, read_timeout=10))
    bucket = 'restore-rehearsal'
    base = S3ImmutableJournalStore(client, bucket)
    owner = '00000000-0000-4000-8000-000000000095'

    class InjectedReadFailure:
        def __init__(self):
            self.failure = 'intent'
            self.names = set()
        def create(self, name, data):
            self.names.add(name)
            return base.create(name, data)
        def read(self, name):
            if name.endswith('/' + self.failure):
                raise RuntimeError('synthetic readback outage')
            return base.read(name)
        def list_names(self, prefix):
            return base.list_names(prefix)

    store = InjectedReadFailure()
    journal = PrivacyJournal(store, b'k' * 32)
    try:
        async with AsyncSessionLocal() as session:
            session.add(ChildProfile(id='readback-fixture-1', user_key=owner, name='Synthetic'))
            await session.commit()
            session.info['privacy_journal'] = journal
            try:
                await delete_profile('readback-fixture-1', db=session, user_key=owner)
            except APIError as exc:
                if exc.status_code != 503:
                    raise
            else:
                raise RuntimeError('Unverifiable intent did not block deletion')
            if (await session.get(ChildProfile, 'readback-fixture-1') is None
                    or await session.scalar(select(PrivacyJournalOutbox.event_id).where(
                        PrivacyJournalOutbox.user_key == owner)) is not None):
                raise RuntimeError('Synthetic protected deletion committed without verified intent')
            store.failure = ''
            if journal.scan().pending_count != 1 or journal.scan().restore_authorized is not False:
                raise RuntimeError('Uncommitted synthetic intent did not block restoration')
            # This fixture owns these random test objects and disposable DB.
            for name in store.names:
                client.delete_object(Bucket=bucket, Key=name)
            store.names.clear()
            store.failure = 'commit'
            await delete_profile('readback-fixture-1', db=session, user_key=owner)
            row = await session.scalar(select(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            if await session.get(ChildProfile, 'readback-fixture-1') is not None or row.published_at is not None:
                raise RuntimeError('Synthetic commit readback failure was not retained for retry')
            store.failure = ''
            if await publish_pending_events(AsyncSessionLocal, journal) != 1:
                raise RuntimeError('Synthetic publication retry did not complete')
            scan = journal.scan()
            if scan.pending_count or len(scan.committed) != 1 or scan.restore_authorized is not False:
                raise RuntimeError('Synthetic readback retry is inconsistent')
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            await session.commit()
        print('PostgreSQL mutation and MinIO readback failure/retry checks passed')
    finally:
        for name in store.names:
            client.delete_object(Bucket=bucket, Key=name)
        client.close()
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
