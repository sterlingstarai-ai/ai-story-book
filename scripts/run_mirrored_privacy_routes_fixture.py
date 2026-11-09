"""Exercise privacy mutations against PostgreSQL and two disposable S3 stores."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
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
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.exceptions import APIError
    from src.models.db import (AccountIdentity, Book, BookShare, Character, ChildProfile, Job,
                               PrivacyJournalOutbox, StoragePurgeTask, VoiceProfile)
    from src.routers.characters import delete_character
    from src.routers.consent import ConsentGrantRequest, grant_consent, revoke_consent
    from src.routers.library import delete_book
    from src.routers.profiles import delete_profile
    from src.routers.shares import revoke_share
    from src.routers.users import delete_my_data
    from src.routers.voice_profiles import revoke_voice_profile_consent
    from src.services.account_recovery import issue_recovery_code, recover_account
    from src.services.privacy_journal import JournalError, PrivacyJournal
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_outbox import publish_pending_events
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore
    from src.services.privacy_journal_verify import verify_current_outbox
    from src.services import privacy_journal_gcs
    from automatic_backup import run_guarded_backup
    from backup_service_guard import BackupServiceGuard
    from publish_backup_gcs import BackupPublishError
    from run_scheduled_backup import build_backup_journal

    class Runtime:
        def __init__(self):
            self.states = {'asb-pilot-api': True, 'asb-pilot-worker': True}
        def running(self, name):
            return self.states[name]
        def stop(self, name):
            self.states[name] = False
        def start(self, name):
            self.states[name] = True
        def reload_proxy(self):
            pass
        def verify_recovery(self):
            assert all(self.states.values())

    class Store:
        def __init__(self):
            self.writes, self.marker = [], None
        def put_verified(self, name, path, **kwargs):
            self.writes.append(name)
            if name.endswith('/verified.json'):
                self.marker = json.loads(Path(path).read_text())

    def backup(folder):
        folder.mkdir()
        (folder / 'objects').mkdir()
        payload = b'synthetic-database'
        (folder / 'database.dump').write_bytes(payload)
        manifest = {'format_version': 1, 'database_scope': 'public',
                    'requires_latest_deletion_and_identity_revocations': True,
                    'database': {'file': 'database.dump', 'size': len(payload),
                                 'sha256': hashlib.sha256(payload).hexdigest()}, 'objects': []}
        (folder / 'manifest.json').write_text(json.dumps(manifest))

    def connect(endpoint):
        return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id='runtime_test',
            aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
            config=Config(signature_version='s3v4', proxies={}, s3={'addressing_style': 'path'},
                          connect_timeout=5, read_timeout=10))
    clients = [connect(os.environ['S3_ENDPOINT']), connect(os.environ['ASB_SECOND_FIXTURE_S3'])]
    bucket = 'restore-rehearsal'
    owner = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:12]
    profile_id, character_id, book_id = 'profile_' + suffix, 'char_' + suffix, 'book_' + suffix
    job_id, share_id, voice_id = 'job_' + suffix, 'share_' + suffix, 'voice_' + suffix

    class FixtureStore:
        def __init__(self, delegate):
            self.delegate = delegate
            self.names = set()
            self.fail = False
            self.fail_commit = False
        def create(self, name, data):
            if self.fail or (self.fail_commit and name.endswith('/commit')):
                raise RuntimeError('synthetic witness outage')
            self.delegate.create(name, data)
            self.names.add(name)
        def read(self, name):
            return self.delegate.read(name)
        def list_names(self, prefix):
            return self.delegate.list_names(prefix)

    stores = [FixtureStore(S3ImmutableJournalStore(client, bucket)) for client in clients]
    journal = PrivacyJournal(MirroredJournalStore(*stores), b'k' * 32)
    try:
        async with AsyncSessionLocal() as db:
            db.info['privacy_journal'] = journal
            db.add_all([ChildProfile(id=profile_id, user_key=owner, name='Synthetic'),
                        Character(id=character_id, user_key=owner, name='Synthetic',
                                  master_description='Synthetic', appearance={}, clothing={}, personality_traits=[]),
                        Job(id=job_id, status='done', user_key=owner),
                        VoiceProfile(id=voice_id, user_key=owner, label='Synthetic', sample_audio_url='',
                                     consented=True, active=True)])
            await db.flush()
            db.add(Book(id=book_id, job_id=job_id, user_key=owner,
                        title='Synthetic', language='ko', target_age='3-5', style='watercolor'))
            await db.flush()
            db.add(BookShare(id=share_id, book_id=book_id, user_key=owner))
            await db.commit()

            # If either provider refuses intent creation, the requested profile
            # deletion must not commit. Remove only this fixture's orphan after
            # explicitly proving it blocks the mirrored scan.
            stores[1].fail = True
            try:
                await delete_profile(profile_id, db=db, user_key=owner)
            except APIError as exc:
                if exc.status_code != 503:
                    raise
            else:
                raise RuntimeError('Synthetic witness failure did not block deletion')
            if await db.get(ChildProfile, profile_id) is None or len(stores[0].names) != 1 or stores[1].names:
                raise RuntimeError('Synthetic witness failure committed a mutation')
            for name in stores[0].names:
                clients[0].delete_object(Bucket=bucket, Key=name)
            stores[0].names.clear()
            stores[1].fail = False

            # A failed second witness must not persist initial recovery-key
            # enrollment or return a new recovery secret.
            stores[1].fail = True
            try:
                await issue_recovery_code(db, owner, owner)
            except APIError as exc:
                if exc.status_code != 503:
                    raise
            else:
                raise RuntimeError('Synthetic recovery enrollment ignored witness outage')
            if await db.get(AccountIdentity, owner) is not None or len(stores[0].names) != 1:
                raise RuntimeError('Synthetic recovery enrollment committed without witnesses')
            for name in stores[0].names:
                clients[0].delete_object(Bucket=bucket, Key=name)
            stores[0].names.clear()
            stores[1].fail = False
            recovery_code, _ = await issue_recovery_code(db, owner, owner)
            next_device = 'asb_device_' + 'Q' * 43
            await recover_account(db, recovery_code, next_device)

            await grant_consent(ConsentGrantRequest(privacy=True, photos=True, data_processing=True,
                consent_version='v2'), db=db, user_key=owner)
            await delete_profile(profile_id, db=db, user_key=owner)
            await delete_character(character_id, db=db, user_key=owner)
            await revoke_share(book_id, db=db, user_key=owner)
            await revoke_voice_profile_consent(voice_id, db=db, user_key=owner)
            await delete_book(book_id, db=db, user_key=owner, profile_id=None, x_deletion_request_id=None)
            stores[1].fail_commit = True
            await revoke_consent(db=db, user_key=owner)
            try:
                journal.scan()
            except JournalError:
                pass
            else:
                raise RuntimeError('Partial synthetic commit was accepted')
            stores[1].fail_commit = False
            if await publish_pending_events(AsyncSessionLocal, journal) != 1:
                raise RuntimeError('Synthetic mirrored publication retry failed')
            await delete_my_data(db=db, user_key=owner, x_user_key=next_device)
            identity = await db.get(AccountIdentity, owner)
            if (identity is None or not identity.deleted or identity.recovery_code_hash is not None
                    or identity.previous_recovery_code_hash is not None):
                raise RuntimeError('Synthetic credential revocation did not persist')
            scan = journal.scan()
            actions = [entry.action for entry in sorted(scan.committed, key=lambda item: item.revision)]
            if actions != ['credential_revoke', 'credential_revoke', 'consent_grant',
                           'profile_delete', 'character_delete', 'share_revoke',
                           'voice_revoke', 'book_delete', 'consent_revoke', 'account_delete']:
                raise RuntimeError('Synthetic mirrored mutation history differs')
            result = await verify_current_outbox(db, scan)
            if result['event_count'] != len(actions) or result['restore_authorized'] is not False:
                raise RuntimeError('Synthetic outbox and mirrored journal disagree')
            if stores[0].names != stores[1].names:
                raise RuntimeError('Synthetic mirror object sets differ')
            for name in stores[0].names:
                if stores[0].read(name) != stores[1].read(name):
                    raise RuntimeError('Synthetic mirror bytes differ')

            # Exercise the backup's actual construction and before/after guard.
            # The GCS adapter is substituted with the first disposable MinIO;
            # the S3 client points to the second. HTTPS endpoint validation is
            # still exercised, and only this synthetic client is redirected.
            original_gcs, original_boto = privacy_journal_gcs.GCSImmutableStore, boto3.client
            def synthetic_s3(_service, **_kwargs):
                return original_boto('s3', endpoint_url=os.environ['ASB_SECOND_FIXTURE_S3'],
                    aws_access_key_id='runtime_test', aws_secret_access_key='disposable-runtime-password',
                    region_name='us-east-1', config=Config(signature_version='s3v4', proxies={},
                        s3={'addressing_style': 'path'}, connect_timeout=5, read_timeout=10))
            privacy_journal_gcs.GCSImmutableStore = lambda name: S3ImmutableJournalStore(clients[0], name)
            boto3.client = synthetic_s3
            backup_store = None
            backup_engine = create_async_engine(os.environ['DATABASE_URL'], poolclass=NullPool)
            try:
                witness_config = {'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT': 'https://synthetic-witness.invalid',
                    'PRIVACY_JOURNAL_WITNESS_S3_BUCKET': bucket, 'PRIVACY_JOURNAL_WITNESS_S3_REGION': 'us-east-1',
                    'PRIVACY_JOURNAL_WITNESS_S3_ACCESS_KEY': 'fixture-witness-access',
                    'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY': 'fixture-witness-secret'}
                app_config = {'S3_ENDPOINT': 'https://synthetic-app.invalid', 'S3_BUCKET': 'other-bucket',
                              'S3_ACCESS_KEY': 'fixture-app-access', 'S3_SECRET_KEY': 'fixture-app-secret'}
                backup_journal, backup_store = build_backup_journal(bucket, '', witness_config, app_config, b'k' * 32)
                backup_factory = async_sessionmaker(backup_engine, expire_on_commit=False)
                commit_name = next(name for name in stores[1].names if name.endswith('/commit'))
                saved = stores[1].read(commit_name)
                with tempfile.TemporaryDirectory(prefix='asb-synthetic-mirror-backup-') as directory:
                    output = Path(directory)
                    folder = output / 'external-fixture'
                    backup(folder)
                    runtime = Runtime()
                    guard = BackupServiceGuard(output / 'state', runtime)
                    remote = Store()
                    def verify():
                        async def check():
                            current = await asyncio.to_thread(backup_journal.scan)
                            async with backup_factory() as backup_db:
                                return await verify_current_outbox(backup_db, current)
                        return asyncio.run(check())
                    def take_with_failure():
                        clients[1].delete_object(Bucket=bucket, Key=commit_name)
                        return {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'backup_set': folder.name}
                    def failure_cycle():
                        try:
                            run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=verify,
                                take_backup=take_with_failure, output_dir=output, store=remote, run_id='a' * 32)
                        except JournalError:
                            pass
                        else:
                            raise RuntimeError('Synthetic changed witness allowed backup publication')
                        if not all(runtime.states.values()) or remote.writes:
                            raise RuntimeError('Synthetic backup failure did not restart safely')
                    await asyncio.to_thread(failure_cycle)
                    stores[1].delegate.create(commit_name, saved)

                    class LosesWitnessDuringUpload(Store):
                        def put_verified(self, name, path, **kwargs):
                            super().put_verified(name, path, **kwargs)
                            if name.endswith('/manifest.json'):
                                clients[1].delete_object(Bucket=bucket, Key=commit_name)

                    def publication_failure_cycle():
                        interrupted = LosesWitnessDuringUpload()
                        try:
                            run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=verify,
                                take_backup=lambda: {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED',
                                                     'backup_set': folder.name},
                                output_dir=output, store=interrupted, run_id='c' * 32)
                        except BackupPublishError:
                            pass
                        else:
                            raise RuntimeError('Synthetic witness loss during upload allowed completion')
                        if (interrupted.marker is not None or not interrupted.writes[-1].endswith('/manifest.json')
                                or not all(runtime.states.values())):
                            raise RuntimeError('Synthetic upload failure did not recover without publishing a marker')

                    await asyncio.to_thread(publication_failure_cycle)
                    stores[1].delegate.create(commit_name, saved)
                    def success_cycle():
                        timings = {}
                        result = run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=verify,
                            take_backup=lambda: {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED',
                                                 'backup_set': folder.name},
                            output_dir=output, store=remote, run_id='b' * 32, timings_ms=timings)
                        if result['restore_authorized'] is not False or remote.marker is None:
                            raise RuntimeError('Synthetic verified backup was not quarantined')
                        if (set(timings) != {'guarded_cycle', 'guarded_idle', 'privacy_checkpoint', 'capture', 'publication'}
                                or timings['guarded_cycle'] < max(timings.values())):
                            raise RuntimeError('Synthetic guarded backup phase timings were incomplete')
                        print(json.dumps({'backup_timings_ms': timings}, sort_keys=True))
                    await asyncio.to_thread(success_cycle)
            finally:
                if backup_store is not None:
                    backup_store.close()
                await backup_engine.dispose()
                privacy_journal_gcs.GCSImmutableStore = original_gcs
                boto3.client = original_boto
            await db.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == owner))
            await db.execute(delete(StoragePurgeTask).where(StoragePurgeTask.user_key == owner))
            await db.execute(delete(AccountIdentity).where(AccountIdentity.user_key == owner))
            await db.commit()
        print('Synthetic mirrored privacy routes and witness outage verified')
    finally:
        for client, store in zip(clients, stores):
            for name in store.names:
                client.delete_object(Bucket=bucket, Key=name)
            client.close()
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
