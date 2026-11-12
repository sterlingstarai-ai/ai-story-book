"""Quarantined replay prototype; these tests use only synthetic SQLite data."""

import importlib
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from src.core.exceptions import APIError
from src.models.db import (AccountIdentity, Book, BookDeletionReceipt, BookShare, Character, ChildProfile, Job, PrivacyJournalOutbox,
                           StoragePurgeTask, UserConsent, VoiceProfile)
from src.services.account_recovery import credential_hash, resolve_user_key


OWNER = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'
DEVICE = 'asb_device_' + 'A' * 43


@pytest.fixture
def modules(monkeypatch):
    class EmptyObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **_kwargs):
            return {'IsTruncated': False}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: EmptyObjectStore())
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('src.services.privacy_journal'), importlib.import_module('replay_privacy_journal')


def scan(module, *actions):
    return module.JournalScan(tuple(
        module.JournalEntry(f'{index:032x}', action, OWNER, index)
        for index, action in enumerate(actions, 1)
    ), 0)


@pytest.mark.asyncio
async def test_replayer_rejects_non_fixture_database_before_mutation(modules, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.engine import make_url

    _, replay = modules
    monkeypatch.setenv('TESTING', 'true')
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(url=make_url(
        'postgresql+asyncpg://runtime_test:disposable-runtime-password@db.example/runtime_test')))
    with pytest.raises(replay.ReplayIncomplete, match='disposable'):
        await replay._require_disposable_fixture(db)


@pytest.mark.asyncio
async def test_replayer_rejects_database_marker_for_different_storage(modules, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sqlalchemy.engine import make_url
    from src.core.config import settings

    _, replay = modules
    monkeypatch.setenv('TESTING', 'true')
    monkeypatch.setenv('ASB_DISPOSABLE_REPLAY_TOKEN', 'a' * 32)
    monkeypatch.setattr(settings, 's3_endpoint', 'http://127.0.0.1:9001')
    monkeypatch.setattr(settings, 's3_bucket', 'restore-rehearsal')
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(url=make_url(
            'postgresql+asyncpg://runtime_test:disposable-runtime-password@127.0.0.1:5432/runtime_test')),
        scalar=AsyncMock(return_value='http://127.0.0.1:9002'),
    )
    with pytest.raises(replay.ReplayIncomplete, match='storage target'):
        await replay._require_disposable_fixture(db)


async def seed(db):
    db.add_all([
        AccountIdentity(user_key=OWNER, device_key_hash=credential_hash(DEVICE, kind='device'),
                        recovery_code_hash='a' * 64, deleted=False),
        AccountIdentity(user_key=OTHER, deleted=False),
        UserConsent(user_key=OWNER, consent_version='v1', privacy=True, photos=True,
                    data_processing=True, granted=True),
        Job(id='synthetic-restore-job', status='done', user_key=OWNER),
    ])
    await db.flush()
    db.add(Book(id='synthetic-restore-book', job_id='synthetic-restore-job', user_key=OWNER,
                title='Synthetic', language='ko', target_age='3-5', style='watercolor'))
    await db.commit()


@pytest.mark.asyncio
async def test_voice_change_blocks_entire_replay_before_any_mutation(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    events = (
        journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='synthetic-restore-book'),
        journal.JournalEntry('b' * 32, 'voice_changed', OWNER, 2, resource_id='voice_synthetic'),
    )
    with pytest.raises(replay.ReplayIncomplete, match='Voice state'):
        await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None
    assert await db_session.scalar(select(PrivacyJournalOutbox.event_id)) is None


@pytest.mark.asyncio
async def test_voice_change_followed_by_erasure_does_not_require_reconstructing_voice(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    db_session.add(VoiceProfile(id='voice_synthetic', user_key=OWNER, label='Synthetic',
                                sample_audio_url='', consented=False, active=False))
    await db_session.commit()
    events = (
        journal.JournalEntry('a' * 32, 'voice_changed', OWNER, 1, resource_id='voice_synthetic'),
        journal.JournalEntry('b' * 32, 'voice_delete', OWNER, 2, resource_id='voice_synthetic'),
    )
    scan = journal.JournalScan(events, 0)
    result = await replay.replay_quarantined(db_session, scan)
    assert result['applied_count'] == 2 and result['restore_authorized'] is False
    assert await db_session.get(VoiceProfile, 'voice_synthetic') is None
    assert (await replay.replay_quarantined(db_session, scan))['applied_count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['voice_delete', 'account_delete'])
@pytest.mark.parametrize('same_bucket', [False, True])
async def test_unknown_voice_media_blocks_replay_before_any_mutation(db_session, modules, action, same_bucket):
    from src.services.storage import canonical_media_url, voice_sample_prefix

    journal, replay = modules
    await seed(db_session)
    url = (canonical_media_url(voice_sample_prefix(OTHER) + 'sample.wav') if same_bucket
           else 'https://unknown.example/sample.wav')
    db_session.add(VoiceProfile(id='voice_synthetic', user_key=OWNER, label='Synthetic',
                                sample_audio_url=url,
                                consented=True, active=True))
    await db_session.commit()
    events = (
        journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='synthetic-restore-book'),
        journal.JournalEntry('b' * 32, action, OWNER, 2,
                             resource_id='voice_synthetic' if action == 'voice_delete' else None),
    )
    with pytest.raises(replay.ReplayIncomplete, match='Voice media cannot be located'):
        await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None
    assert await db_session.get(VoiceProfile, 'voice_synthetic') is not None


@pytest.mark.asyncio
async def test_book_delete_replay_is_owner_scoped_and_idempotent(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    event = journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='synthetic-restore-book')
    result = await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert result['applied_count'] == 1
    assert await db_session.get(Book, 'synthetic-restore-book') is None
    assert (await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0)))['applied_count'] == 0


@pytest.mark.asyncio
async def test_book_deletion_receipt_replays_only_after_book_erasure(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    db_session.add(ChildProfile(id='profile-a', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    info = journal.DeletionReceipt('b' * 32, 'profile-a')
    event = journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1,
                                 resource_id='synthetic-restore-book', deletion_receipt=info)
    history = journal.JournalScan((event,), 0)
    assert (await replay.replay_quarantined(db_session, history))['applied_count'] == 1
    assert await db_session.get(Book, 'synthetic-restore-book') is None
    receipt = await db_session.get(BookDeletionReceipt, (OWNER, info.request_id))
    assert receipt.book_id == 'synthetic-restore-book' and receipt.profile_id == 'profile-a'
    assert (await replay.replay_quarantined(db_session, history))['applied_count'] == 0


@pytest.mark.asyncio
async def test_failed_book_purge_cannot_create_replayed_receipt(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    async def failed(_):
        return ['synthetic']
    monkeypatch.setattr('src.services.purge_queue._execute_task', failed)
    info = journal.DeletionReceipt('b' * 32, None)
    event = journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1,
                                 resource_id='synthetic-restore-book', deletion_receipt=info)
    with pytest.raises(replay.ReplayIncomplete, match='Storage deletion is incomplete'):
        await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert await db_session.get(BookDeletionReceipt, (OWNER, info.request_id)) is None


@pytest.mark.asyncio
async def test_reused_receipt_request_in_history_blocks_before_mutation(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    info = journal.DeletionReceipt('b' * 32, None)
    events = (
        journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='synthetic-restore-book', deletion_receipt=info),
        journal.JournalEntry('c' * 32, 'book_delete', OWNER, 2, resource_id='different-book', deletion_receipt=info),
    )
    with pytest.raises(replay.ReplayIncomplete, match='requests conflict'):
        await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_profile_erasure_after_book_deletion_removes_replayed_receipt(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    db_session.add(ChildProfile(id='profile-a', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    info = journal.DeletionReceipt('b' * 32, 'profile-a')
    events = (
        journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1,
                             resource_id='synthetic-restore-book', deletion_receipt=info),
        journal.JournalEntry('c' * 32, 'profile_delete', OWNER, 2, resource_id='profile-a'),
    )
    result = await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert result['applied_count'] == 2
    assert await db_session.get(ChildProfile, 'profile-a') is None
    assert await db_session.get(BookDeletionReceipt, (OWNER, info.request_id)) is None


@pytest.mark.asyncio
async def test_tampered_checkpoint_receipt_blocks_before_mutation(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    info = journal.DeletionReceipt('b' * 32, None)
    event = journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1,
                                 resource_id='synthetic-restore-book', deletion_receipt=info)
    db_session.add(PrivacyJournalOutbox(event_id=event.event_id, user_key=OWNER, revision=1,
        action=event.action, resource_id=event.resource_id,
        deletion_receipt=journal.deletion_receipt_to_payload(journal.DeletionReceipt('c' * 32, None))))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint disagrees'):
        await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_replay_checks_backup_marker_before_mutation(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    event = journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='synthetic-restore-book')
    history = journal.JournalScan((event,), 0)
    marker = {'journal_event_count': 0, 'journal_sha256': hashlib.sha256(b'[]').hexdigest(),
              'restore_authorized': False}
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint'):
        await replay.replay_quarantined(db_session, history, backup_marker=dict(marker, journal_sha256='0' * 64))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    assert (await replay.replay_quarantined(db_session, history, backup_marker=marker))['applied_count'] == 1
    assert await db_session.get(Book, 'synthetic-restore-book') is None


@pytest.mark.asyncio
async def test_resource_replay_refuses_another_users_book(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    event = journal.JournalEntry('a' * 32, 'book_delete', OTHER, 1, resource_id='synthetic-restore-book')
    with pytest.raises(replay.ReplayIncomplete, match='ownership mismatch'):
        await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_revoked_share_link_stays_revoked_after_replay(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    db_session.add(BookShare(id='synthetic-share-token', book_id='synthetic-restore-book', user_key=OWNER))
    await db_session.commit()
    event = journal.JournalEntry('a' * 32, 'share_revoke', OWNER, 1, resource_id='synthetic-restore-book')
    await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert (await db_session.get(BookShare, 'synthetic-share-token')).revoked_at is not None


@pytest.mark.asyncio
async def test_consent_regrant_after_backup_replays_in_recorded_order(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    revoke = journal.JournalEntry('a' * 32, 'consent_revoke', OWNER, 1)
    grant = journal.JournalEntry('b' * 32, 'consent_grant', OWNER, 2,
                                 consent_state=journal.ConsentState(True, True, True, 'v2'))
    result = await replay.replay_quarantined(db_session, journal.JournalScan((grant, revoke), 0))
    active = (await db_session.scalars(select(UserConsent).where(
        UserConsent.user_key == OWNER, UserConsent.revoked_at.is_(None)))).all()
    assert len(active) == 1 and active[0].granted and active[0].photos and active[0].consent_version == 'v2'
    assert result['applied_count'] == 2 and result['restore_authorized'] is False
    assert (await replay.replay_quarantined(db_session, journal.JournalScan((grant, revoke), 0)))['applied_count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('action,model,resource_id', [
    ('character_delete', Character, 'char_fixture'),
    ('profile_delete', ChildProfile, 'profile_fixture'),
    ('voice_delete', VoiceProfile, 'voice_fixture'),
    ('voice_revoke', VoiceProfile, 'voice_fixture'),
])
async def test_individual_resource_replay(db_session, modules, action, model, resource_id):
    journal, replay = modules
    await seed(db_session)
    db_session.add_all([
        Character(id='char_fixture', user_key=OWNER, name='Synthetic', master_description='Synthetic',
                  appearance={}, clothing={}, personality_traits=[]),
        ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'),
        VoiceProfile(id='voice_fixture', user_key=OWNER, label='Synthetic', sample_audio_url='',
                     consented=True, active=True, provider_voice_id='provider-fixture'),
    ])
    await db_session.commit()
    event = journal.JournalEntry('a' * 32, action, OWNER, 1, resource_id=resource_id)
    result = await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    resource = await db_session.get(model, resource_id)
    if action == 'voice_revoke':
        assert resource is not None and not resource.consented and not resource.active
        assert resource.provider_voice_id is None and resource.sample_audio_url == ''
    else:
        assert resource is None
    assert result['restore_authorized'] is False
    assert result['voice_state_recovery_supported'] is False


@pytest.mark.asyncio
async def test_no_voice_events_still_cannot_claim_voice_state_restoration(db_session, modules):
    journal, replay = modules
    result = await replay.replay_quarantined(db_session, journal.JournalScan((), 0))
    assert result['voice_state_recovery_supported'] is False
    assert result['restore_authorized'] is False


@pytest.mark.asyncio
async def test_voice_replacement_after_backup_never_revives_old_sample(db_session, modules, monkeypatch):
    """Replacement is not recorded yet: erase old audio, admit lost newer state."""
    from src.services.storage import canonical_media_url, voice_sample_prefix

    journal, replay = modules
    old_key = voice_sample_prefix(OWNER) + 'old.wav'
    new_key = voice_sample_prefix(OWNER) + 'new.wav'
    objects = {old_key: b'old synthetic audio', new_key: b'new synthetic audio'}
    db_session.add(VoiceProfile(id='voice_fixture', user_key=OWNER, label='Synthetic',
        sample_audio_url=canonical_media_url(old_key), consented=True, active=True,
        provider_voice_id='old-fixture-provider-id'))
    await db_session.commit()

    async def delete_fixture(task):
        objects.pop(task.target, None)
        return []

    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fixture)
    revoke = journal.JournalEntry('a' * 32, 'voice_revoke', OWNER, 1, resource_id='voice_fixture')
    result = await replay.replay_quarantined(db_session, journal.JournalScan((revoke,), 0))
    profile = await db_session.get(VoiceProfile, 'voice_fixture')
    assert old_key not in objects and new_key in objects
    assert profile.sample_audio_url == '' and not profile.consented and not profile.active
    assert profile.provider_voice_id is None
    assert result['voice_state_recovery_supported'] is False and result['restore_authorized'] is False


@pytest.mark.asyncio
async def test_deleted_account_replay_removes_data_revokes_keys_and_keeps_quarantine(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    result = await replay.replay_quarantined(db_session, scan(journal, 'account_delete', 'credential_revoke'))
    assert result['restore_authorized'] is False
    assert await db_session.get(Book, 'synthetic-restore-book') is None
    assert await db_session.get(Job, 'synthetic-restore-job') is None
    identity = await db_session.get(AccountIdentity, OWNER)
    assert identity.deleted and identity.device_key_hash is None and identity.recovery_code_hash is None
    assert await db_session.scalar(select(UserConsent.id).where(UserConsent.user_key == OWNER)) is None
    assert await db_session.get(AccountIdentity, OTHER) is not None
    with pytest.raises(APIError):
        await resolve_user_key(db_session, DEVICE)
    with pytest.raises(APIError):
        await resolve_user_key(db_session, OWNER)
    repeated = await replay.replay_quarantined(db_session, scan(journal, 'account_delete', 'credential_revoke'))
    assert repeated['restore_authorized'] is False
    assert repeated['applied_count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('post_delete', ['consent_grant', 'credential_revoke'])
async def test_replay_rejects_reactivation_after_account_deletion_before_mutating(db_session, modules, post_delete):
    journal, replay = modules
    await seed(db_session)
    delete = journal.JournalEntry('a' * 32, 'account_delete', OWNER, 1)
    if post_delete == 'consent_grant':
        change = journal.JournalEntry('b' * 32, post_delete, OWNER, 2,
                                      consent_state=journal.ConsentState(True, True, True, 'v1'))
    else:
        change = journal.JournalEntry('b' * 32, post_delete, OWNER, 2,
                                      credential_state=journal.CredentialState('b' * 64, None, None, None))
    with pytest.raises(replay.ReplayIncomplete, match='Deleted account'):
        await replay.replay_quarantined(db_session, journal.JournalScan((delete, change), 0))
    # Both events must be rejected before the account deletion or any new
    # checkpoint is committed, leaving the quarantined target unchanged.
    assert await db_session.get(Book, 'synthetic-restore-book') is not None
    identity = await db_session.get(AccountIdentity, OWNER)
    assert not identity.deleted
    assert (await db_session.scalars(select(PrivacyJournalOutbox))).all() == []


@pytest.mark.asyncio
async def test_tombstone_with_remaining_owned_rows_cannot_be_treated_as_done(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    identity = await db_session.get(AccountIdentity, OWNER)
    identity.deleted = True
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='still has rows'):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('deleted', [False, True])
async def test_checkpointed_account_deletion_requires_actual_erasure(db_session, modules, deleted):
    journal, replay = modules
    await seed(db_session)
    identity = await db_session.get(AccountIdentity, OWNER)
    identity.deleted = deleted
    identity.device_key_hash = None
    identity.recovery_code_hash = None
    db_session.add(PrivacyJournalOutbox(event_id=f'{1:032x}', user_key=OWNER,
                                       revision=1, action='account_delete'))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='Deleted account'):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_checkpointed_account_deletion_rejects_leftover_credentials(db_session, modules):
    journal, replay = modules
    db_session.add(AccountIdentity(user_key=OWNER, deleted=True, recovery_code_hash='a' * 64))
    db_session.add(PrivacyJournalOutbox(event_id=f'{1:032x}', user_key=OWNER,
                                       revision=1, action='account_delete'))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='still has credentials'):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))


@pytest.mark.asyncio
async def test_checkpointed_account_deletion_allows_retry_hash_but_denies_access(db_session, modules):
    journal, replay = modules
    db_session.add(AccountIdentity(user_key=OWNER, deleted=True, device_key_hash=credential_hash(DEVICE, kind='device')))
    db_session.add(PrivacyJournalOutbox(event_id=f'{1:032x}', user_key=OWNER,
                                       revision=1, action='account_delete'))
    await db_session.commit()
    result = await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    assert result['restore_authorized'] is False and result['applied_count'] == 0
    with pytest.raises(APIError):
        await resolve_user_key(db_session, DEVICE)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['keys', 'prefix'])
async def test_done_purge_rejects_actual_remaining_object(db_session, modules, monkeypatch, kind):
    journal, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind=kind,
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **_kwargs):
            key = 'fixture/image' if kind == 'keys' else 'fixture/image/child'
            return {'IsTruncated': False, 'Contents': [{'Key': key}]}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete, match='object remains'):
        await replay.replay_quarantined(db_session, journal.JournalScan((), 0))


@pytest.mark.asyncio
@pytest.mark.parametrize('versioning', ['Enabled', 'Suspended', None])
async def test_done_purge_rejects_versioned_bucket(db_session, modules, monkeypatch, versioning):
    journal, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind='keys',
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {'Status': versioning}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete, match='Versioned storage'):
        await replay.replay_quarantined(db_session, journal.JournalScan((), 0))


@pytest.mark.asyncio
async def test_done_key_purge_checks_all_listing_pages(db_session, modules, monkeypatch):
    journal, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind='keys',
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **kwargs):
            if 'ContinuationToken' not in kwargs:
                return {'IsTruncated': True, 'NextContinuationToken': 'next',
                        'Contents': [{'Key': 'fixture/image-extra'}]}
            return {'IsTruncated': False, 'Contents': [{'Key': 'fixture/image'}]}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete, match='object remains'):
        await replay.replay_quarantined(db_session, journal.JournalScan((), 0))


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['permission', 'invalid_page', 'repeated_token'])
async def test_done_purge_unverifiable_listing_keeps_quarantine(db_session, modules, monkeypatch, failure):
    journal, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind='keys',
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **_kwargs):
            if failure == 'permission':
                raise PermissionError('sensitive provider details')
            if failure == 'invalid_page':
                return {}
            return {'IsTruncated': True, 'NextContinuationToken': 'same'}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete, match='could not be verified') as exc:
        await replay.replay_quarantined(db_session, journal.JournalScan((), 0))
    assert 'sensitive provider details' not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('page', [
    {'IsTruncated': False, 'KeyCount': 1},
    {'IsTruncated': False, 'Prefix': 'another-prefix'},
    {'IsTruncated': False, 'Name': 'another-bucket'},
    {'IsTruncated': False, 'CommonPrefixes': [{'Prefix': 'fixture/image/hidden/'}]},
    {'IsTruncated': False, 'NextContinuationToken': 'unexpected'},
    {'IsTruncated': False, 'Contents': [{'Key': 'fixture/image-extra'}, {'Key': 'fixture/image-extra'}]},
])
async def test_done_purge_rejects_contradictory_listing_metadata(db_session, modules, monkeypatch, page):
    _, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind='keys',
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **_kwargs):
            return page

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete, match='could not be verified'):
        await replay._verify_completed_purges(db_session)


@pytest.mark.asyncio
async def test_done_purge_rejects_duplicates_across_pages(db_session, modules, monkeypatch):
    _, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind='keys',
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **kwargs):
            if 'ContinuationToken' not in kwargs:
                return {'IsTruncated': True, 'NextContinuationToken': 'next',
                        'Contents': [{'Key': 'fixture/image-extra'}]}
            return {'IsTruncated': False, 'Contents': [{'Key': 'fixture/image-extra'}]}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete, match='could not be verified'):
        await replay._verify_completed_purges(db_session)


@pytest.mark.asyncio
async def test_done_purge_rejects_inventory_larger_than_memory_limit(db_session, modules, monkeypatch):
    _, replay = modules
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='account_deletion', kind='keys',
                                   target='fixture/image', status='done'))
    await db_session.commit()

    class ObjectStore:
        def get_bucket_versioning(self, **_kwargs):
            return {}

        def list_objects_v2(self, **_kwargs):
            return {'IsTruncated': False, 'Contents': [
                {'Key': 'fixture/image-extra-1'}, {'Key': 'fixture/image-extra-2'},
            ]}

    monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    monkeypatch.setattr(replay, '_MAX_PURGE_LIST_KEYS', 1)
    with pytest.raises(replay.ReplayIncomplete, match='could not be verified'):
        await replay._verify_completed_purges(db_session)


@pytest.mark.asyncio
async def test_consent_and_credential_replay_preserves_other_users(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    result = await replay.replay_quarantined(db_session, scan(journal, 'consent_revoke', 'credential_revoke'))
    consent = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
    identity = await db_session.get(AccountIdentity, OWNER)
    assert not consent.granted and consent.revoked_at is not None
    assert not identity.deleted and identity.device_key_hash is None and identity.recovery_code_hash is None
    assert await db_session.get(AccountIdentity, OTHER) is not None
    assert result['restore_authorized'] is False
    with pytest.raises(APIError):
        await resolve_user_key(db_session, DEVICE)
    with pytest.raises(APIError):
        await resolve_user_key(db_session, OWNER)


@pytest.mark.asyncio
async def test_replay_keeps_new_device_credential_but_rejects_old_one(db_session, modules):
    from datetime import datetime
    journal, replay = modules
    await seed(db_session)
    new_device = 'asb_device_' + 'B' * 43
    new_recovery = 'ASB-R1-' + 'C' * 43
    state = journal.CredentialState(
        credential_hash(new_device, kind='device'), credential_hash(new_recovery, kind='recovery'),
        'a' * 64, datetime(2026, 11, 2),
    )
    entry = journal.JournalEntry(f'{1:032x}', 'credential_revoke', OWNER, 1, state)
    result = await replay.replay_quarantined(db_session, journal.JournalScan((entry,), 0))
    assert result['restore_authorized'] is False
    with pytest.raises(APIError):
        await resolve_user_key(db_session, DEVICE)
    assert await resolve_user_key(db_session, new_device) == OWNER
    identity = await db_session.get(AccountIdentity, OWNER)
    assert identity.recovery_code_hash == credential_hash(new_recovery, kind='recovery')
    assert identity.previous_recovery_code_hash == 'a' * 64


@pytest.mark.asyncio
async def test_pending_event_rejects_before_any_mutation(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    pending = journal.JournalScan(scan(journal, 'account_delete').committed, 1)
    with pytest.raises(replay.ReplayIncomplete):
        await replay.replay_quarantined(db_session, pending)
    assert await db_session.get(Book, 'synthetic-restore-book') is not None
    assert not (await db_session.get(AccountIdentity, OWNER)).deleted


@pytest.mark.asyncio
async def test_missing_or_duplicate_revisions_reject_before_any_mutation(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    for revisions in ((1, 3), (1, 1)):
        events = tuple(journal.JournalEntry(f'{i:032x}', 'account_delete', OWNER, revision)
                       for i, revision in enumerate(revisions, 1))
        with pytest.raises(replay.ReplayIncomplete, match='revisions are incomplete'):
            await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_checkpointed_recorded_regrant_does_not_undo_later_consent(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    grant_state = journal.ConsentState(True, True, True, 'v1')
    db_session.add_all([
        PrivacyJournalOutbox(event_id=f'{1:032x}', user_key=OWNER, revision=1, action='consent_revoke'),
        PrivacyJournalOutbox(event_id=f'{2:032x}', user_key=OWNER, revision=2, action='consent_grant',
                             consent_state=journal.consent_state_to_payload(grant_state)),
    ])
    await db_session.commit()
    history = journal.JournalScan((journal.JournalEntry(f'{1:032x}', 'consent_revoke', OWNER, 1),
        journal.JournalEntry(f'{2:032x}', 'consent_grant', OWNER, 2, consent_state=grant_state)), 0)
    result = await replay.replay_quarantined(db_session, history)
    consent = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
    assert result['applied_count'] == 0 and consent.granted and consent.photos
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['consent_revoke', 'consent_grant', 'credential_revoke'])
async def test_inconsistent_checkpoint_state_blocks_replay_before_mutation(db_session, modules, action):
    journal, replay = modules
    await seed(db_session)
    kwargs = {}
    if action == 'consent_grant':
        kwargs['consent_state'] = journal.ConsentState(True, False, True, 'v1')
    elif action == 'credential_revoke':
        kwargs['credential_state'] = journal.CredentialState('b' * 64, None, None, None)
    event = journal.JournalEntry(f'{1:032x}', action, OWNER, 1, **kwargs)
    db_session.add(PrivacyJournalOutbox(event_id=event.event_id, user_key=OWNER, revision=1, action=action,
        consent_state=journal.consent_state_to_payload(event.consent_state),
        credential_state=journal.credential_state_to_payload(event.credential_state)))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint state'):
        await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_later_subject_bad_checkpoint_blocks_earlier_subject_mutation(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    db_session.add(UserConsent(user_key=OTHER, consent_version='v1', privacy=True, photos=True,
                               data_processing=True, granted=True))
    db_session.add(PrivacyJournalOutbox(event_id='b' * 32, user_key=OTHER,
                                       revision=1, action='consent_revoke'))
    await db_session.commit()
    events = (
        journal.JournalEntry('a' * 32, 'book_delete', OWNER, 1, resource_id='synthetic-restore-book'),
        journal.JournalEntry('b' * 32, 'consent_revoke', OTHER, 1),
    )
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint state'):
        await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_later_resource_ownership_mismatch_blocks_all_replay(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    original_hash = credential_hash(DEVICE, kind='device')
    events = (
        journal.JournalEntry('a' * 32, 'credential_revoke', OWNER, 1),
        journal.JournalEntry('b' * 32, 'book_delete', OTHER, 1, resource_id='synthetic-restore-book'),
    )
    with pytest.raises(replay.ReplayIncomplete, match='ownership mismatch'):
        await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    assert (await db_session.get(AccountIdentity, OWNER)).device_key_hash == original_hash
    assert (await db_session.scalars(select(PrivacyJournalOutbox))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'done'])
async def test_prior_unresolved_or_ineffective_purge_blocks_any_replay(db_session, modules, monkeypatch, status):
    journal, replay = modules
    await seed(db_session)
    db_session.add(StoragePurgeTask(user_key=OTHER, reason='fixture', kind='keys',
                                   target='fixture/image', status=status))
    await db_session.commit()
    if status == 'done':
        class ObjectStore:
            def get_bucket_versioning(self, **_kwargs):
                return {}

            def list_objects_v2(self, **_kwargs):
                return {'IsTruncated': False, 'Contents': [{'Key': 'fixture/image'}]}
        monkeypatch.setattr('src.services.storage.get_s3_client', lambda: ObjectStore())
    with pytest.raises(replay.ReplayIncomplete):
        await replay.replay_quarantined(db_session, scan(journal, 'credential_revoke'))
    assert (await db_session.get(AccountIdentity, OWNER)).device_key_hash == credential_hash(DEVICE, kind='device')
    assert (await db_session.scalars(select(PrivacyJournalOutbox))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('photos_enabled', [False, True])
async def test_checkpointed_photo_revoke_requires_photos_disabled(db_session, modules, photos_enabled):
    journal, replay = modules
    await seed(db_session)
    consent = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
    consent.photos = photos_enabled
    grant_state = journal.ConsentState(True, True, True, 'v1')
    events = (
        journal.JournalEntry(f'{1:032x}', 'consent_grant', OWNER, 1, consent_state=grant_state),
        journal.JournalEntry(f'{2:032x}', 'photo_revoke', OWNER, 2),
    )
    for event in events:
        db_session.add(PrivacyJournalOutbox(event_id=event.event_id, user_key=OWNER,
            revision=event.revision, action=event.action,
            consent_state=journal.consent_state_to_payload(event.consent_state)))
    await db_session.commit()
    if photos_enabled:
        with pytest.raises(replay.ReplayIncomplete, match='checkpoint state'):
            await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
    else:
        result = await replay.replay_quarantined(db_session, journal.JournalScan(events, 0))
        assert result['applied_count'] == 0 and result['restore_authorized'] is False


async def _seed_photo_checkpoint(db, journal, *, action, residual, regrant=False, grant_state=None):
    from src.core.utils import utcnow
    from src.services.privacy_journal_verify import fingerprint_entries

    await seed(db)
    consent = await db.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
    if action == 'consent_revoke':
        consent.revoked_at = utcnow()
        consent.granted = False
    else:
        consent.photos = False
    state = (grant_state or journal.ConsentState(True, False, True, 'v1')) if action == 'consent_grant' else None
    if state is not None:
        consent.privacy, consent.photos, consent.data_processing = state.privacy, state.photos, state.data_processing
        consent.granted = state.privacy and state.data_processing
    events = [journal.JournalEntry('d' * 32, action, OWNER, 1, consent_state=state)]
    if regrant:
        consent.revoked_at = None
        consent.granted = consent.photos = True
        events.append(journal.JournalEntry('e' * 32, 'consent_grant', OWNER, 2,
            consent_state=journal.ConsentState(True, True, True, 'v1')))
    if residual == 'character':
        db.add(Character(id='synthetic-photo-residual', name='Synthetic', user_key=OWNER,
            master_description='Synthetic fixture', appearance={}, clothing={}, personality_traits=[],
            from_photo=True, source_image_url='https://synthetic.invalid/photo.png'))
    else:
        (await db.get(Job, 'synthetic-restore-job')).photo_derived = True
    for event in events:
        db.add(PrivacyJournalOutbox(event_id=event.event_id, user_key=OWNER,
            revision=event.revision, action=event.action, published_at=utcnow(),
            consent_state=journal.consent_state_to_payload(event.consent_state)))
    await db.commit()
    return journal.JournalScan(tuple(events), 0), {
        'journal_event_count': len(events), 'journal_sha256': fingerprint_entries(events),
        'restore_authorized': False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['consent_revoke', 'photo_revoke', 'consent_grant'])
@pytest.mark.parametrize('residual', ['character', 'job'])
async def test_checkpointed_photo_erasure_rejects_derived_rows_without_purge_intent(
        db_session, modules, action, residual):
    journal, replay = modules
    history, marker = await _seed_photo_checkpoint(db_session, journal, action=action, residual=residual)
    assert await db_session.scalar(select(StoragePurgeTask.id)) is None
    with pytest.raises(replay.ReplayIncomplete, match='Photo-derived checkpoint state'):
        await replay.replay_quarantined(db_session, history, backup_marker=marker)
    assert await db_session.get(Book, 'synthetic-restore-book') is not None
    if residual == 'character':
        assert await db_session.get(Character, 'synthetic-photo-residual') is not None
    else:
        assert (await db_session.get(Job, 'synthetic-restore-job')).photo_derived


@pytest.mark.asyncio
@pytest.mark.parametrize('residual', ['character', 'job'])
async def test_checkpointed_photo_regrant_allows_current_authorized_derived_state(db_session, modules, residual):
    """Preserve current permission; this does not attest a row's consent generation."""
    journal, replay = modules
    history, marker = await _seed_photo_checkpoint(db_session, journal,
        action='photo_revoke', residual=residual, regrant=True)
    result = await replay.replay_quarantined(db_session, history, backup_marker=marker)
    assert result['applied_count'] == 0 and result['restore_authorized'] is False
    if residual == 'character':
        assert await db_session.get(Character, 'synthetic-photo-residual') is not None
    else:
        assert (await db_session.get(Job, 'synthetic-restore-job')).photo_derived


@pytest.mark.asyncio
@pytest.mark.parametrize('privacy,data_processing', [(False, True), (True, False)])
@pytest.mark.parametrize('residual', ['character', 'job'])
async def test_checkpointed_partial_grant_does_not_authorize_photo_residuals(
        db_session, modules, privacy, data_processing, residual):
    journal, replay = modules
    history, marker = await _seed_photo_checkpoint(db_session, journal,
        action='consent_grant', residual=residual,
        grant_state=journal.ConsentState(privacy, True, data_processing, 'v1'))
    consent = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
    assert consent.photos and not consent.granted
    assert await db_session.scalar(select(StoragePurgeTask.id)) is None
    with pytest.raises(replay.ReplayIncomplete, match='Photo-derived checkpoint state'):
        await replay.replay_quarantined(db_session, history, backup_marker=marker)
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_checkpointed_credential_rotation_preserves_recorded_new_key(db_session, modules):
    from datetime import datetime
    journal, replay = modules
    await seed(db_session)
    new_device = 'asb_device_' + 'B' * 43
    state = journal.CredentialState(credential_hash(new_device, kind='device'), 'b' * 64,
                                    'a' * 64, datetime(2026, 11, 2))
    identity = await db_session.get(AccountIdentity, OWNER)
    identity.device_key_hash = state.device_hash
    identity.recovery_code_hash = state.recovery_hash
    identity.previous_recovery_code_hash = state.previous_hash
    identity.recovery_code_created_at = state.recovery_created_at
    db_session.add(PrivacyJournalOutbox(event_id=f'{1:032x}', user_key=OWNER,
        revision=1, action='credential_revoke', credential_state=journal.credential_state_to_payload(state)))
    await db_session.commit()
    event = journal.JournalEntry(f'{1:032x}', 'credential_revoke', OWNER, 1, credential_state=state)
    result = await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert result['applied_count'] == 0 and await resolve_user_key(db_session, new_device) == OWNER
    with pytest.raises(APIError):
        await resolve_user_key(db_session, DEVICE)


@pytest.mark.asyncio
async def test_ineffective_consent_replay_never_reports_success(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)

    async def ineffective_revoke(**_kwargs):
        return None

    monkeypatch.setattr('src.routers.consent.revoke_consent', ineffective_revoke)
    with pytest.raises(replay.ReplayIncomplete, match='replay state'):
        await replay.replay_quarantined(db_session, scan(journal, 'consent_revoke'))


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['book_delete', 'share_revoke'])
async def test_checkpointed_resource_privacy_change_must_match_backup(db_session, modules, action):
    journal, replay = modules
    await seed(db_session)
    if action == 'share_revoke':
        db_session.add(BookShare(id='synthetic-share-token', book_id='synthetic-restore-book', user_key=OWNER))
    event = journal.JournalEntry(f'{1:032x}', action, OWNER, 1, resource_id='synthetic-restore-book')
    db_session.add(PrivacyJournalOutbox(event_id=event.event_id, user_key=OWNER, revision=1,
                                       action=action, resource_id=event.resource_id))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint state'):
        await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('active', [False, True])
async def test_checkpointed_voice_revocation_requires_no_active_voice(db_session, modules, active):
    journal, replay = modules
    db_session.add(VoiceProfile(id='voice_fixture', user_key=OWNER, label='Synthetic',
        sample_audio_url='fixture.wav' if active else '', consented=active, active=active))
    event = journal.JournalEntry(f'{1:032x}', 'voice_revoke', OWNER, 1, resource_id='voice_fixture')
    db_session.add(PrivacyJournalOutbox(event_id=event.event_id, user_key=OWNER, revision=1,
                                       action=event.action, resource_id=event.resource_id))
    await db_session.commit()
    if active:
        with pytest.raises(replay.ReplayIncomplete, match='Voice checkpoint state'):
            await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
    else:
        result = await replay.replay_quarantined(db_session, journal.JournalScan((event,), 0))
        assert result['applied_count'] == 0 and result['voice_state_recovery_supported'] is False


@pytest.mark.asyncio
async def test_backup_checkpoint_mismatch_blocks_all_replay(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    db_session.add(PrivacyJournalOutbox(event_id='f' * 32, user_key=OWNER,
        revision=1, action='consent_revoke'))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint disagrees'):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_missing_entire_subject_history_blocks_all_replay(db_session, modules):
    journal, replay = modules
    await seed(db_session)
    db_session.add(PrivacyJournalOutbox(event_id='f' * 32, user_key=OTHER,
        revision=1, action='credential_revoke'))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='checkpoint disagrees'):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    assert await db_session.get(Book, 'synthetic-restore-book') is not None


@pytest.mark.asyncio
async def test_photo_revoke_retains_other_consent_but_disables_photo_permission(db_session, modules, monkeypatch):
    journal, replay = modules
    await seed(db_session)
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    await replay.replay_quarantined(db_session, scan(journal, 'photo_revoke'))
    consent = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
    assert consent.granted and consent.privacy and not consent.photos
    assert await db_session.get(AccountIdentity, OTHER) is not None


@pytest.mark.asyncio
async def test_storage_failure_leaves_deleted_account_and_pending_queue_quarantined(db_session, modules, monkeypatch):
    from src.services.purge_queue import run_purge_tasks
    journal, replay = modules
    await seed(db_session)
    async def delete_fails(_):
        return ['synthetic-failure']
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fails)
    with pytest.raises(replay.ReplayIncomplete):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    identity = await db_session.get(AccountIdentity, OWNER)
    assert identity.deleted
    tasks = list((await db_session.scalars(select(StoragePurgeTask).where(
        StoragePurgeTask.user_key == OWNER, StoragePurgeTask.status == 'pending'))).all())
    assert tasks
    with pytest.raises(replay.ReplayIncomplete, match='Storage deletion is incomplete'):
        await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))

    async def delete_recovers(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_recovers)
    tasks = list((await db_session.scalars(select(StoragePurgeTask).where(
        StoragePurgeTask.user_key == OWNER, StoragePurgeTask.status == 'pending'))).all())
    assert await run_purge_tasks(db_session, tasks) == []
    result = await replay.replay_quarantined(db_session, scan(journal, 'account_delete'))
    assert result['applied_count'] == 1 and result['restore_authorized'] is False
    assert (await replay.replay_quarantined(db_session, scan(journal, 'account_delete')))['applied_count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('task_owner', [OTHER, None])
@pytest.mark.parametrize('status', ['pending', 'failed', 'unknown'])
async def test_unrelated_or_ownerless_unresolved_purge_blocks_empty_replay(db_session, modules, task_owner, status):
    journal, replay = modules
    db_session.add(StoragePurgeTask(user_key=task_owner, reason='fixture', kind='keys',
                                    target='synthetic-object', status=status))
    await db_session.commit()
    with pytest.raises(replay.ReplayIncomplete, match='Storage deletion is incomplete'):
        await replay.replay_quarantined(db_session, journal.JournalScan((), 0))
