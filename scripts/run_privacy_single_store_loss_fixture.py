"""Synthetic acknowledged deletion followed by one journal replica loss."""
import asyncio
import os
from urllib.parse import urlsplit
import uuid

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    first, second = urlsplit(os.environ['S3_ENDPOINT']), urlsplit(os.environ.get('ASB_SECOND_FIXTURE_S3', ''))
    if (second.scheme != 'http' or second.hostname != '127.0.0.1' or not second.port
            or second.netloc == first.netloc or second.path not in ('', '/')):
        raise RuntimeError('Separate disposable storage is required')
    import boto3
    from botocore.config import Config
    from sqlalchemy import delete, select
    from src.core.database import AsyncSessionLocal, async_engine
    from src.models.db import ChildProfile, PrivacyJournalOutbox
    from src.routers.profiles import delete_profile
    from src.services.privacy_journal import JournalError, PrivacyJournal
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore
    from replay_privacy_journal import ReplayIncomplete, plan_quarantined_replay

    def connect(endpoint):
        return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id='runtime_test',
            aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
            config=Config(signature_version='s3v4', proxies={}, s3={'addressing_style': 'path'},
                          connect_timeout=5, read_timeout=10))

    clients = [connect(os.environ['S3_ENDPOINT']), connect(os.environ['ASB_SECOND_FIXTURE_S3'])]
    bucket = 'restore-rehearsal'
    a, b = [S3ImmutableJournalStore(client, bucket) for client in clients]
    owner = str(uuid.uuid4())
    profile_id = 'loss_' + uuid.uuid4().hex[:20]

    class CommitOutage:
        def __init__(self, delegate):
            self.delegate = delegate
            self.owned = set()
        def create(self, name, data):
            if name.endswith('/commit'):
                raise RuntimeError('synthetic commit outage')
            self.delegate.create(name, data)
            self.owned.add(name)
        def read(self, name):
            return self.delegate.read(name)
        def list_names(self, prefix):
            return self.delegate.list_names(prefix)

    journal_a, journal_b = CommitOutage(a), CommitOutage(b)
    mirrored = PrivacyJournal(MirroredJournalStore(journal_a, journal_b), b'k' * 32)
    try:
        async with AsyncSessionLocal() as db:
            db.add(ChildProfile(id=profile_id, user_key=owner, name='Synthetic'))
            await db.commit()
            db.info['privacy_journal'] = mirrored
            result = await delete_profile(profile_id, db=db, user_key=owner)
            row = await db.scalar(select(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            if not isinstance(result, dict) or await db.get(ChildProfile, profile_id) is not None:
                raise RuntimeError('Synthetic deletion did not succeed')
            if row is None or row.published_at is not None or mirrored.scan().pending_count != 1:
                raise RuntimeError('Synthetic pending commit was not retained')
            if len(journal_a.owned) != 1 or journal_a.owned != journal_b.owned:
                raise RuntimeError('Synthetic intent did not reach both stores')
            name = next(iter(journal_a.owned))
            if a.read(name) != b.read(name):
                raise RuntimeError('Synthetic independent intents differ')
            # Destroy only this run's exact synthetic intent in one store.
            clients[0].delete_object(Bucket=bucket, Key=name)
            journal_a.owned.remove(name)
            try:
                mirrored.scan()
            except JournalError:
                pass
            else:
                raise RuntimeError('Missing synthetic replica was accepted')
            survivor = PrivacyJournal(b, b'k' * 32).scan()
            if survivor.pending_count != 1 or survivor.restore_authorized is not False:
                raise RuntimeError('Surviving intent did not preserve uncertainty')
            try:
                plan_quarantined_replay(survivor)
            except ReplayIncomplete:
                pass
            else:
                raise RuntimeError('Surviving pending intent improperly permitted replay')
            await db.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            await db.commit()
        print('Synthetic acknowledged deletion survived one replica loss as pending; replay remained blocked')
    finally:
        for client, wrapped in zip(clients, (journal_a, journal_b)):
            for name in wrapped.owned:
                client.delete_object(Bucket=bucket, Key=name)
            client.close()
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
