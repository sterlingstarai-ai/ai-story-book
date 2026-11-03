"""Synthetic-only concurrent fence + two object stores + checkpoint failures.

Run exclusively inside the network-none restore fixture. It does not establish
production writer coverage, independently controlled head freshness, or restore
permission. The containing offline rehearsal separately restores a backup and
replays synthetic deletion, consent and credential events.
"""
import asyncio
import fcntl
import json
import os
import re
import socket
import struct
from urllib.parse import urlsplit
import uuid

from run_restore_replay_fixture import require_local_fixture


def require_offline():
    require_local_fixture()
    second = urlsplit(os.environ.get('ASB_SECOND_FIXTURE_S3', ''))
    first = urlsplit(os.environ['S3_ENDPOINT'])
    if (os.geteuid() != 65534 or os.environ.get('ASB_OFFLINE_SYNTHETIC_FIXTURE') != 'true'
            or second.scheme != 'http' or second.hostname != '127.0.0.1'
            or not second.port or second.netloc == first.netloc or second.path not in ('', '/')):
        raise RuntimeError('An isolated two-store synthetic fixture is required')
    interfaces = socket.if_nameindex()
    if not any(name == 'lo' for _, name in interfaces):
        raise RuntimeError('Synthetic loopback is unavailable')
    with socket.socket() as control:
        for _, name in interfaces:
            if name != 'lo':
                request = struct.pack('256s', name.encode('ascii'))
                flags = struct.unpack('H', fcntl.ioctl(control.fileno(), 0x8913, request)[16:18])[0]
                if flags & 1:
                    raise RuntimeError('Synthetic network isolation is unavailable')


async def main():
    require_offline()
    import boto3
    from botocore.config import Config
    from sqlalchemy import delete
    from src.core.database import AsyncSessionLocal, async_engine
    from src.models.db import ChildProfile, PrivacyJournalOutbox
    from src.services.privacy_checkpoint_head import append_checkpoint_head, verify_anchored_checkpoint
    from src.services.privacy_journal import JournalError, PrivacyJournal
    from src.services.privacy_journal_checkpoint import capture_fenced_checkpoint
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_outbox import prepare_privacy_event, publish_pending_events
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore
    from src.services.privacy_restore_source_guard import hold_consistent_source

    class OwnedStore:
        def __init__(self, client):
            self.delegate = S3ImmutableJournalStore(client, 'restore-rehearsal')
            self.names = set()
        def create(self, name, data):
            self.delegate.create(name, data)
            self.names.add(name)
        def read(self, name):
            return self.delegate.read(name)
        def list_names(self, prefix):
            return self.delegate.list_names(prefix)

    class CheckpointStore:
        """Synthetic S3 stand-in for the separate checkpoint API."""
        def __init__(self, client):
            self.client, self.names = client, set()
        def create(self, name, data):
            if not re.fullmatch(r'privacy-(?:checkpoints|checkpoint-heads)/v1/[0-9a-f]{32}/[0-9]{20}', name):
                raise ValueError('Unexpected synthetic checkpoint name')
            self.client.put_object(Bucket='restore-rehearsal', Key=name, Body=data, IfNoneMatch='*')
            self.names.add(name)
        def read(self, name):
            if name not in self.names:
                raise ValueError('Unknown synthetic checkpoint')
            body = self.client.get_object(Bucket='restore-rehearsal', Key=name)['Body']
            try:
                return body.read(5 * 1024 * 1024 + 1)
            finally:
                body.close()

    def connect(endpoint):
        return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id='runtime_test',
            aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
            config=Config(signature_version='s3v4', proxies={}, s3={'addressing_style': 'path'},
                          connect_timeout=5, read_timeout=10))

    clients = [connect(os.environ['S3_ENDPOINT']), connect(os.environ['ASB_SECOND_FIXTURE_S3'])]
    stores = [OwnedStore(client) for client in clients]
    checkpoints = CheckpointStore(clients[1])
    journal = PrivacyJournal(MirroredJournalStore(*stores), os.urandom(32))
    owner, namespace = str(uuid.uuid4()), uuid.uuid4().hex
    checkpoint_key, head_key = os.urandom(32), os.urandom(32)
    tasks = []

    async def event(action, resource=None):
        async with AsyncSessionLocal() as db:
            await prepare_privacy_event(db, journal, user_key=owner, action=action, resource_id=resource)
            await db.commit()

    async def publish(count):
        if await publish_pending_events(AsyncSessionLocal, journal) != count:
            raise RuntimeError('Synthetic event publication differs')

    try:
        async with AsyncSessionLocal() as db:
            db.add(ChildProfile(id='fixture_profile', user_key=owner, name='Synthetic'))
            await db.commit()
        await event('consent_revoke')
        await publish(1)
        async with AsyncSessionLocal() as db:
            first = await capture_fenced_checkpoint(db, journal, checkpoints, namespace=namespace,
                generation=1, key=checkpoint_key, now=100)
        head1 = append_checkpoint_head(checkpoints, namespace=namespace, key=head_key, checkpoint=first)
        async with AsyncSessionLocal() as db:
            async with hold_consistent_source(db, journal) as (boundary, _scan):
                if boundary['event_count'] != 1 or boundary['restore_authorized'] is not False:
                    raise RuntimeError('Synthetic source boundary differs')
                tasks = [asyncio.create_task(event('profile_delete', 'fixture_profile')),
                         asyncio.create_task(event('credential_revoke')),
                         asyncio.create_task(event('consent_revoke'))]
                await asyncio.sleep(0.3)
                if any(task.done() for task in tasks):
                    raise RuntimeError('A cooperating privacy writer escaped the fence')
                # A direct, noncooperating deletion ignores the advisory lock.
                # Its success is a limitation, never evidence of completeness.
                async with AsyncSessionLocal() as direct:
                    deleted = await direct.execute(delete(ChildProfile).where(
                        ChildProfile.id == 'fixture_profile', ChildProfile.user_key == owner))
                    await direct.commit()
                    if deleted.rowcount != 1:
                        raise RuntimeError('Synthetic uncooperative deletion was not demonstrated')
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
        await publish(3)
        scan = journal.scan()
        if scan.pending_count or len(scan.committed) != 4:
            raise RuntimeError('Synthetic journal history differs')
        async with AsyncSessionLocal() as db:
            second = await capture_fenced_checkpoint(db, journal, checkpoints, namespace=namespace,
                generation=2, key=checkpoint_key, now=101)
        head2 = append_checkpoint_head(checkpoints, namespace=namespace, key=head_key, checkpoint=second, previous=head1)
        args = {'namespace': namespace, 'head_key': head_key, 'checkpoint_key': checkpoint_key,
                'trusted_head': head2, 'now': 102, 'max_age': 10}
        result = verify_anchored_checkpoint(checkpoints, checkpoints, scan, candidate_head=head2, **args)
        if result['restore_authorized'] is not False or result['journal_count'] != 4:
            raise RuntimeError('Synthetic witness authorized restore or omitted events')
        try:
            verify_anchored_checkpoint(checkpoints, checkpoints, scan, candidate_head=head1, **args)
        except JournalError:
            pass
        else:
            raise RuntimeError('Old synthetic head was accepted as newest trusted head')
        journal_names = set(stores[0].names)
        if not journal_names or not journal_names.issubset(stores[1].names):
            raise RuntimeError('Synthetic mirrored event objects differ')
        victim = next(iter(journal_names))
        saved = stores[1].read(victim)
        clients[1].delete_object(Bucket='restore-rehearsal', Key=victim)
        try:
            journal.scan()
        except JournalError:
            pass
        else:
            raise RuntimeError('Synthetic missing witness object was accepted')
        stores[1].delegate.create(victim, saved)
        if len(journal.scan().committed) != 4:
            raise RuntimeError('Synthetic exact witness repair failed')
        print(json.dumps({'status': 'SYNTHETIC_FENCE_WITNESS_PASSED', 'event_count': 4,
            'stale_head_rejected': True, 'missing_replica_rejected': True,
            'uncooperative_deletion_not_fenced': True,
            'writer_coverage_verified': False, 'latest_head_verified': False, 'restore_authorized': False}))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
                await db.execute(delete(ChildProfile).where(ChildProfile.user_key == owner))
                await db.commit()
        finally:
            await async_engine.dispose()
            for name in checkpoints.names:
                clients[1].delete_object(Bucket='restore-rehearsal', Key=name)
            for client, store in zip(clients, stores):
                for name in store.names:
                    client.delete_object(Bucket='restore-rehearsal', Key=name)
                client.close()


if __name__ == '__main__':
    asyncio.run(main())
