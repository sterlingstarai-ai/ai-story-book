"""Actual mutation paths with an explicitly injected synthetic journal."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.exceptions import APIError
from src.models.db import Character, ChildProfile, Job, Book, PrivacyJournalOutbox, VoiceProfile
from src.routers.characters import delete_character
from src.routers.consent import ConsentGrantRequest, grant_consent, revoke_consent
from src.routers.library import delete_book
from src.routers.profiles import delete_profile
from src.routers.shares import revoke_share
from src.routers.users import delete_my_data
from src.routers.voice_profiles import delete_voice_profile, revoke_voice_profile_consent
from src.services.account_recovery import issue_recovery_code, recover_account, credential_hash
from src.services.privacy_journal import PrivacyJournal
from src.services.privacy_journal_outbox import publish_pending_events

OWNER = '00000000-0000-4000-8000-000000000011'


class Store:
    def __init__(self):
        self.objects = {}
        self.fail_intent = False
        self.fail_commit = False

    def create(self, name, data):
        if (self.fail_intent and name.endswith('/intent')) or (self.fail_commit and name.endswith('/commit')):
            raise RuntimeError('synthetic failure')
        if name in self.objects:
            raise RuntimeError('already exists')
        self.objects[name] = data

    def read(self, name):
        return self.objects[name]

    def list_names(self, prefix):
        return [name for name in self.objects if name.startswith(prefix)]


@pytest.mark.asyncio
async def test_real_mutation_paths_publish_ordered_events(db_session):
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    await grant_consent(ConsentGrantRequest(privacy=True, photos=True, data_processing=True, consent_version='v2'),
                        db=db_session, user_key=OWNER)
    await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    await revoke_consent(db=db_session, user_key=OWNER)
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert [entry.action for entry in entries] == ['consent_grant', 'profile_delete', 'consent_revoke']
    assert entries[1].resource_id == 'profile_fixture'
    assert entries[0].consent_state.photos is True
    assert journal.scan().pending_count == 0


@pytest.mark.asyncio
async def test_missing_intent_blocks_deletion_before_commit(db_session):
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    store.fail_intent = True
    with pytest.raises(APIError) as error:
        await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    assert error.value.status_code == 503
    assert await db_session.get(ChildProfile, 'profile_fixture') is not None
    assert await db_session.scalar(select(PrivacyJournalOutbox.event_id)) is None


@pytest.mark.asyncio
async def test_enabled_journal_missing_from_session_blocks_deletion(db_session, monkeypatch):
    from src.core.config import settings

    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    monkeypatch.setattr(settings, 'privacy_journal_enabled', True)
    with pytest.raises(APIError) as error:
        await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    assert error.value.status_code == 503
    assert await db_session.get(ChildProfile, 'profile_fixture') is not None
    assert await db_session.scalar(select(PrivacyJournalOutbox.event_id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['unreadable', 'tampered'])
async def test_unverified_created_intent_blocks_database_commit(db_session, mode):
    class UnverifiedStore(Store):
        def create(self, name, data):
            super().create(name, data)
            if mode == 'tampered' and name.endswith('/intent'):
                self.objects[name] = b'corrupted synthetic bytes'

        def read(self, name):
            if mode == 'unreadable' and name.endswith('/intent'):
                raise RuntimeError('synthetic readback outage')
            return super().read(name)

    db_session.info['privacy_journal'] = PrivacyJournal(UnverifiedStore(), b'k' * 32)
    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    with pytest.raises(APIError) as error:
        await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    assert error.value.status_code == 503
    assert await db_session.get(ChildProfile, 'profile_fixture') is not None
    assert await db_session.scalar(select(PrivacyJournalOutbox.event_id)) is None


@pytest.mark.asyncio
async def test_committed_event_readback_failure_stays_pending_until_retry(db_session):
    class UnreadableCommitStore(Store):
        fail_read = True
        def read(self, name):
            if self.fail_read and name.endswith('/commit'):
                raise RuntimeError('synthetic readback outage')
            return super().read(name)

    store = UnreadableCommitStore()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    assert await db_session.get(ChildProfile, 'profile_fixture') is None
    row = await db_session.scalar(select(PrivacyJournalOutbox))
    assert row is not None and row.published_at is None
    store.fail_read = False
    assert await publish_pending_events(async_sessionmaker(db_session.bind, expire_on_commit=False), journal) == 1
    assert journal.scan().pending_count == 0 and journal.scan().restore_authorized is False


@pytest.mark.asyncio
async def test_failed_publication_keeps_committed_deletion_pending_for_retry(db_session):
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    store.fail_commit = True
    await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    assert await db_session.get(ChildProfile, 'profile_fixture') is None
    assert journal.scan().pending_count == 1
    store.fail_commit = False
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await publish_pending_events(factory, journal) == 1
    assert journal.scan().pending_count == 0


@pytest.mark.asyncio
async def test_recovery_rotation_publishes_current_verifier_hashes(db_session):
    journal = PrivacyJournal(Store(), b'k' * 32)
    db_session.info['privacy_journal'] = journal
    original_code, _ = await issue_recovery_code(db_session, OWNER, OWNER)
    new_device = 'asb_device_' + 'B' * 43
    next_code, _ = await recover_account(db_session, original_code, new_device)
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert len(entries) == 2 and all(entry.action == 'credential_revoke' for entry in entries)
    assert entries[-1].credential_state.device_hash == credential_hash(new_device, kind='device')
    assert entries[-1].credential_state.recovery_hash == credential_hash(next_code, kind='recovery')
    assert entries[-1].credential_state.previous_hash == credential_hash(original_code, kind='recovery')


@pytest.mark.asyncio
async def test_recovery_rotation_rolls_back_when_journal_intent_fails(db_session):
    from src.services.account_recovery import resolve_user_key
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    original_code, _ = await issue_recovery_code(db_session, OWNER, OWNER)
    store.fail_intent = True
    new_device = 'asb_device_' + 'B' * 43
    with pytest.raises(APIError) as error:
        await recover_account(db_session, original_code, new_device)
    assert error.value.status_code == 503
    assert await resolve_user_key(db_session, OWNER) == OWNER
    with pytest.raises(APIError):
        await resolve_user_key(db_session, new_device)
    assert len(journal.scan().committed) == 1 and journal.scan().pending_count == 0
    store.fail_intent = False
    next_code, _ = await recover_account(db_session, original_code, new_device)
    assert next_code and await resolve_user_key(db_session, new_device) == OWNER


@pytest.mark.asyncio
async def test_first_recovery_enrollment_does_not_persist_if_intent_fails(db_session):
    from src.models.db import AccountIdentity
    store = Store()
    store.fail_intent = True
    db_session.info['privacy_journal'] = PrivacyJournal(store, b'k' * 32)
    with pytest.raises(APIError) as error:
        await issue_recovery_code(db_session, OWNER, OWNER)
    assert error.value.status_code == 503
    assert await db_session.get(AccountIdentity, OWNER) is None
    assert await db_session.scalar(select(PrivacyJournalOutbox.event_id)) is None


@pytest.mark.asyncio
async def test_recovery_rotation_publication_failure_remains_pending_and_retryable(db_session):
    from src.services.account_recovery import resolve_user_key
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    original_code, _ = await issue_recovery_code(db_session, OWNER, OWNER)
    new_device = 'asb_device_' + 'B' * 43
    store.fail_commit = True
    next_code, _ = await recover_account(db_session, original_code, new_device)
    assert next_code and await resolve_user_key(db_session, new_device) == OWNER
    with pytest.raises(APIError):
        await resolve_user_key(db_session, OWNER)
    assert journal.scan().pending_count == 1
    replayed_code, _ = await recover_account(db_session, original_code, new_device)
    assert replayed_code is None
    with pytest.raises(APIError):
        await recover_account(db_session, original_code, 'asb_device_' + 'C' * 43)
    store.fail_commit = False
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await publish_pending_events(factory, journal) == 1
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert journal.scan().pending_count == 0
    assert entries[-1].credential_state.device_hash == credential_hash(new_device, kind='device')
    assert entries[-1].credential_state.recovery_hash == credential_hash(next_code, kind='recovery')


@pytest.mark.asyncio
async def test_later_rotation_does_not_hide_an_earlier_pending_record(db_session):
    from src.services.account_recovery import resolve_user_key
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    first_code, _ = await issue_recovery_code(db_session, OWNER, OWNER)
    device_b = 'asb_device_' + 'B' * 43
    device_c = 'asb_device_' + 'C' * 43
    store.fail_commit = True
    second_code, _ = await recover_account(db_session, first_code, device_b)
    store.fail_commit = False
    third_code, _ = await recover_account(db_session, second_code, device_c)
    assert journal.scan().pending_count == 1
    assert await resolve_user_key(db_session, device_c) == OWNER
    with pytest.raises(APIError):
        await resolve_user_key(db_session, device_b)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await publish_pending_events(factory, journal) == 1
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert [entry.revision for entry in entries] == [1, 2, 3]
    assert entries[-1].credential_state.device_hash == credential_hash(device_c, kind='device')
    assert entries[-1].credential_state.recovery_hash == credential_hash(third_code, kind='recovery')
    assert journal.scan().pending_count == 0


@pytest.mark.asyncio
async def test_delete_routes_publish_only_after_successful_mutations(db_session, monkeypatch):
    journal = PrivacyJournal(Store(), b'k' * 32)
    db_session.info['privacy_journal'] = journal
    async def delete_fake(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', delete_fake)
    db_session.add_all([
        Character(id='char_fixture', user_key=OWNER, name='Synthetic', master_description='Synthetic',
                  appearance={}, clothing={}, personality_traits=[]),
        Job(id='job_fixture', user_key=OWNER, status='done'),
        VoiceProfile(id='voice_fixture', user_key=OWNER, label='Synthetic', sample_audio_url='',
                     consented=True, active=True),
    ])
    await db_session.flush()
    db_session.add(Book(id='book_fixture', job_id='job_fixture', user_key=OWNER,
                        title='Synthetic', language='ko', target_age='3-5', style='watercolor'))
    await db_session.commit()
    await delete_character('char_fixture', db=db_session, user_key=OWNER)
    await revoke_share('book_fixture', db=db_session, user_key=OWNER)
    await delete_book('book_fixture', db=db_session, user_key=OWNER, profile_id=None)
    await revoke_voice_profile_consent('voice_fixture', db=db_session, user_key=OWNER)
    await delete_voice_profile('voice_fixture', db=db_session, user_key=OWNER)
    await delete_my_data(db=db_session, user_key=OWNER, x_user_key=OWNER)
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert [entry.action for entry in entries] == [
        'character_delete', 'share_revoke', 'book_delete', 'voice_revoke', 'voice_delete', 'account_delete',
    ]
    assert [entry.resource_id for entry in entries] == [
        'char_fixture', 'book_fixture', 'book_fixture', 'voice_fixture', 'voice_fixture', None,
    ]
    assert journal.scan().pending_count == 0


@pytest.mark.asyncio
async def test_monitor_retries_unpublished_privacy_event(db_session, monkeypatch):
    from src.services import job_monitor, privacy_journal_runtime

    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    db_session.add(ChildProfile(id='profile_fixture', user_key=OWNER, name='Synthetic'))
    await db_session.commit()
    store.fail_commit = True
    await delete_profile('profile_fixture', db=db_session, user_key=OWNER)
    assert journal.scan().pending_count == 1
    store.fail_commit = False
    monkeypatch.setattr(privacy_journal_runtime, 'configured_journal', lambda: journal)
    monkeypatch.setattr(job_monitor, 'AsyncSessionLocal', async_sessionmaker(db_session.bind, expire_on_commit=False))
    monitor = job_monitor.JobMonitor()
    monitor._running = True
    with patch.object(monitor, 'check_and_recover_jobs', AsyncMock()), \
         patch('src.services.character_avatar.sweep_character_avatars', AsyncMock()), \
         patch('src.services.purge_queue.sweep_pending_purges', AsyncMock()), \
         patch.object(job_monitor.asyncio, 'sleep', AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            await monitor._monitor_loop()
    assert journal.scan().pending_count == 0


@pytest.mark.asyncio
async def test_authenticated_http_changes_are_recorded(client, db_session, headers):
    journal = PrivacyJournal(Store(), b'k' * 32)
    db_session.info['privacy_journal'] = journal
    response = await client.post('/v1/consent', headers=headers,
        json={'privacy': True, 'photos': True, 'data_processing': True})
    assert response.status_code == 200
    response = await client.post('/v1/profiles', headers=headers, json={'name': 'Synthetic', 'age_band': '5-7'})
    assert response.status_code == 200
    profile_id = response.json()['id']
    assert (await client.delete('/v1/profiles/' + profile_id, headers=headers)).status_code == 200
    assert (await client.post('/v1/consent/revoke', headers=headers)).status_code == 200
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert [entry.action for entry in entries] == ['consent_grant', 'profile_delete', 'consent_revoke']
    assert entries[1].resource_id == profile_id


@pytest.mark.asyncio
async def test_voice_create_and_change_record_only_nonsecret_marker(db_session, monkeypatch):
    from src.routers import voice_profiles

    monkeypatch.setattr(voice_profiles, 'require_voice_profiles_supported', lambda: None)
    store = Store()
    journal = PrivacyJournal(store, b'k' * 32)
    db_session.info['privacy_journal'] = journal
    original = 'https://external.example/original-synthetic-sample'
    replacement = 'https://external.example/replacement-synthetic-sample'
    provider = 'synthetic-provider-secret'
    created = await voice_profiles.create_voice_profile(
        voice_profiles.VoiceProfileCreateRequest(label='Synthetic', sample_audio_url=original,
                                                 provider_voice_id=provider, consented=True),
        db=db_session, user_key=OWNER)
    await voice_profiles.update_voice_profile(
        created['id'], voice_profiles.VoiceProfileUpdateRequest(sample_audio_url=replacement, consented=True),
        db=db_session, user_key=OWNER)
    entries = sorted(journal.scan().committed, key=lambda entry: entry.revision)
    assert [item.action for item in entries] == ['voice_changed', 'voice_changed']
    assert all(item.resource_id == created['id'] for item in entries)
    assert all(original.encode() not in value and replacement.encode() not in value
               and provider.encode() not in value for value in store.objects.values())


@pytest.mark.asyncio
async def test_voice_creation_does_not_commit_if_journal_intent_fails(db_session, monkeypatch):
    from src.routers import voice_profiles

    monkeypatch.setattr(voice_profiles, 'require_voice_profiles_supported', lambda: None)
    store = Store()
    store.fail_intent = True
    db_session.info['privacy_journal'] = PrivacyJournal(store, b'k' * 32)
    with pytest.raises(APIError):
        await voice_profiles.create_voice_profile(
            voice_profiles.VoiceProfileCreateRequest(label='Synthetic',
                sample_audio_url='https://external.example/synthetic-sample', consented=True),
            db=db_session, user_key=OWNER)
    assert await db_session.scalar(select(VoiceProfile.id)) is None


@pytest.mark.asyncio
async def test_deleted_account_cannot_create_new_voice_profile(db_session, monkeypatch):
    from src.core.exceptions import AuthorizationError
    from src.models.db import AccountIdentity
    from src.routers import voice_profiles

    monkeypatch.setattr(voice_profiles, 'require_voice_profiles_supported', lambda: None)
    db_session.add(AccountIdentity(user_key=OWNER, deleted=True))
    await db_session.commit()
    with pytest.raises(AuthorizationError):
        await voice_profiles.create_voice_profile(
            voice_profiles.VoiceProfileCreateRequest(label='Synthetic',
                sample_audio_url='https://external.example/synthetic-sample', consented=True),
            db=db_session, user_key=OWNER)
    assert await db_session.scalar(select(VoiceProfile.id)) is None


@pytest.mark.asyncio
async def test_voice_upload_guard_stays_pending_until_atomic_profile_claim(db_session, monkeypatch):
    from types import SimpleNamespace
    from src.models.db import StoragePurgeTask
    from src.routers import voice_profiles

    monkeypatch.setattr(voice_profiles, 'require_voice_profiles_supported', lambda: None)
    monkeypatch.setattr(voice_profiles, 'voice_sample_prefix', lambda _owner: 'fixture/')
    monkeypatch.setattr(voice_profiles, 'key_from_public_url',
                        lambda url: url.removeprefix('https://storage.example/'))
    monkeypatch.setattr(voice_profiles, 'canonical_media_url', lambda key: 'https://storage.example/' + key)
    monkeypatch.setattr(voice_profiles, 'media_url', lambda url: url)
    monkeypatch.setattr(voice_profiles.storage_service, 'upload_bytes',
                        AsyncMock(side_effect=lambda data, key, content_type, bounded_upload: 'https://storage.example/' + key))
    upload = SimpleNamespace(content_type='audio/mpeg', filename='sample.mp3', read=AsyncMock(return_value=b'fake'))
    saved = await voice_profiles.upload_voice_sample(upload, db=db_session, user_key=OWNER)
    guard = await db_session.scalar(select(StoragePurgeTask))
    assert guard.status == 'pending' and guard.reason == 'voice_sample_upload_guard'
    await voice_profiles.create_voice_profile(
        voice_profiles.VoiceProfileCreateRequest(label='Synthetic', sample_audio_url=saved['sample_audio_url'],
                                                 consented=True), db=db_session, user_key=OWNER)
    await db_session.refresh(guard)
    assert guard.status == 'cancelled'


@pytest.mark.asyncio
async def test_expired_voice_upload_is_not_claimed(db_session, monkeypatch):
    from datetime import timedelta
    from src.core.exceptions import ValidationError
    from src.core.utils import utcnow
    from src.models.db import StoragePurgeTask
    from src.routers import voice_profiles

    monkeypatch.setattr(voice_profiles, 'voice_sample_prefix', lambda _owner: 'fixture/')
    monkeypatch.setattr(voice_profiles, 'key_from_public_url', lambda _url: 'fixture/old.mp3')
    guard = StoragePurgeTask(user_key=OWNER, reason='voice_sample_upload_guard', kind='keys',
                             target='fixture/old.mp3', status='pending', attempts=0,
                             created_at=utcnow() - timedelta(minutes=16))
    db_session.add(guard)
    await db_session.commit()
    with pytest.raises(ValidationError):
        await voice_profiles._claim_voice_upload(db_session, user_key=OWNER, url='synthetic')
    assert guard.status == 'pending'


@pytest.mark.asyncio
async def test_unknown_voice_upload_completion_remains_alerted_and_unclaimable(db_session, monkeypatch):
    from types import SimpleNamespace
    from src.models.db import StoragePurgeTask
    from src.routers import voice_profiles

    monkeypatch.setattr(voice_profiles, 'require_voice_profiles_supported', lambda: None)
    monkeypatch.setattr(voice_profiles, 'voice_sample_prefix', lambda _owner: 'fixture/')
    monkeypatch.setattr(voice_profiles.storage_service, 'upload_bytes', AsyncMock(side_effect=TimeoutError()))
    upload = SimpleNamespace(content_type='audio/mpeg', filename='sample.mp3', read=AsyncMock(return_value=b'fake'))
    with pytest.raises(APIError):
        await voice_profiles.upload_voice_sample(upload, db=db_session, user_key=OWNER)
    guard = await db_session.scalar(select(StoragePurgeTask))
    assert guard.status == 'failed' and guard.last_error == 'upload_completion_unknown'
