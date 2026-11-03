"""Simulate source loss around a successful deletion, using disposable data only."""
import asyncio
import hashlib
import os
import secrets

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    import asyncpg
    import boto3
    from botocore.config import Config
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from sqlalchemy import select
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.core.database import Base
    from src.models.db import ChildProfile, PrivacyJournalOutbox
    from src.routers.profiles import delete_profile
    from src.services.privacy_checkpoint_head import append_checkpoint_head
    from src.services.privacy_journal import JournalScan, PrivacyJournal
    from src.services.privacy_journal_checkpoint import _encode
    from src.services.privacy_journal_outbox import DisposableMemoryJournalStore
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore
    from src.services.privacy_journal_verify import fingerprint_entries
    from src.services.privacy_witness_receipt import sign_receipt
    from independent_journal_evidence import IndependentJournalEvidenceError, verify_witnessed_journal

    original = make_url(os.environ['DATABASE_URL'])
    dbname = 'asb_loss_' + secrets.token_hex(8)
    owner = '00000000-0000-4000-8000-000000000094'
    profile_id = 'synthetic_loss_' + secrets.token_hex(8)
    admin = await asyncpg.connect(host=original.host, port=original.port, user=original.username,
                                  password=original.password, database=original.database)
    engine = None
    created = False
    client = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'], aws_access_key_id='runtime_test',
        aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
        config=Config(signature_version='s3v4', proxies={}, s3={'addressing_style': 'path'},
                      connect_timeout=5, read_timeout=10))
    bucket = 'restore-rehearsal'
    base = S3ImmutableJournalStore(client, bucket)

    class MissingCommit:
        def __init__(self):
            self.names = set()
        def create(self, name, data):
            if name.endswith('/commit'):
                raise RuntimeError('synthetic commit publication failure')
            base.create(name, data)
            self.names.add(name)
        def read(self, name):
            return base.read(name)
        def list_names(self, prefix):
            return base.list_names(prefix)

    store = MissingCommit()
    journal = PrivacyJournal(store, b'j' * 32)
    try:
        # The identifier consists only of our fixed prefix and random hex.
        await admin.execute(f'CREATE DATABASE "{dbname}"')
        created = True
        engine = create_async_engine(original.set(database=dbname), pool_pre_ping=True)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Retain an independently signed, but deliberately older, empty head.
        checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
        namespace = 'a' * 32
        checkpoint_key, head_key = b'c' * 32, b'h' * 32
        empty = JournalScan((), 0)
        checkpoint = {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'restore_authorized': False,
                      'event_count': 0, 'journal_sha256': fingerprint_entries(())}
        name, ciphertext = _encode(namespace, 1, checkpoint_key, checkpoint, empty, 100)
        checkpoints.create(name, ciphertext)
        ref = {'status': 'FENCED_WITNESS_CHECKPOINT_STORED', 'restore_authorized': False,
               'namespace': namespace, 'generation': 1, 'sha256': hashlib.sha256(ciphertext).hexdigest()}
        head = append_checkpoint_head(heads, namespace=namespace, key=head_key, checkpoint=ref)
        signing = Ed25519PrivateKey.generate()
        receipt = sign_receipt(signing, namespace=namespace, head=head, observed_at=100,
            observation={'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False})
        args = {'journal': journal, 'head_store': heads, 'checkpoint_store': checkpoints,
                'public_key': signing.public_key(), 'receipt': receipt, 'namespace': namespace,
                'trusted_head': head, 'candidate_head': head, 'head_key': head_key,
                'checkpoint_key': checkpoint_key, 'now': 101, 'max_age': 10}

        async with factory() as db:
            db.add(ChildProfile(id=profile_id, user_key=owner, name='Synthetic'))
            await db.commit()
            db.info['privacy_journal'] = journal
            result = await delete_profile(profile_id, db=db, user_key=owner)
            row = await db.scalar(select(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            if not isinstance(result, dict) or await db.get(ChildProfile, profile_id) is not None:
                raise RuntimeError('Synthetic deletion did not succeed')
            if row is None or row.published_at is not None or journal.scan().pending_count != 1:
                raise RuntimeError('Synthetic missing commit was not retained')
        # Close all connections before destroying only the database created by this run.
        await engine.dispose()
        engine = None
        await admin.execute(f'DROP DATABASE "{dbname}"')
        created = False
        try:
            verify_witnessed_journal(**args)
        except IndependentJournalEvidenceError:
            pass
        else:
            raise RuntimeError('A pending intent was accepted after synthetic source loss')

        # Simulate loss of the one independently written intent. The prior
        # signed anchor still verifies, but explicitly does not claim latestness
        # or permission to replay/publish the restored backup.
        if len(store.names) != 1:
            raise RuntimeError('Synthetic journal ownership is ambiguous')
        for owned in store.names:
            client.delete_object(Bucket=bucket, Key=owned)
        store.names.clear()
        result = verify_witnessed_journal(**args)
        if result != {'status': 'WITNESSED_JOURNAL_PREFIX_VERIFIED', 'latest_head_verified': False,
                      'privacy_replay_authorized': False, 'restore_authorized': False}:
            raise RuntimeError('Historical head falsely authorized restoration')
        print('Synthetic source-loss pending intent blocked; missing-intent history remained unproven')
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            await admin.execute(f'DROP DATABASE "{dbname}"')
        await admin.close()
        for owned in store.names:
            client.delete_object(Bucket=bucket, Key=owned)
        client.close()


if __name__ == '__main__':
    asyncio.run(main())
