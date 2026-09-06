"""Disabled voice collection, opaque storage paths and durable erasure."""
import json

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.logging import redact_log_data
from src.models.db import StoragePurgeTask, VoiceProfile
from src.services import storage
from src.services.purge_queue import run_purge_tasks


@pytest.mark.asyncio
async def test_voice_upload_never_exposes_account_credential(client, headers):
    response = await client.post('/v1/voice-profiles/upload-sample', headers=headers,
                                 files={'sample': ('parent.wav', b'sample', 'audio/wav')})
    assert response.status_code == 200
    assert headers['X-User-Key'] not in response.text
    key = storage.key_from_public_url(response.json()['sample_audio_url'])
    assert key.startswith(storage.voice_sample_prefix(headers['X-User-Key']))
    assert 'X-Amz-Signature' in response.json()['sample_audio_url']


@pytest.mark.asyncio
async def test_disabled_voice_blocks_collection_but_preserves_erasure(client, headers, db_session, monkeypatch):
    profile = VoiceProfile(id='old-voice', user_key=headers['X-User-Key'], label='Parent',
                           sample_audio_url=storage.canonical_media_url('voice-samples/' + headers['X-User-Key'] + '/old.wav'),
                           consented=True, active=True)
    db_session.add(profile)
    await db_session.commit()
    monkeypatch.setattr(settings, 'audio_feature_enabled', False)
    listed = await client.get('/v1/voice-profiles', headers=headers)
    assert listed.status_code == 200
    assert headers['X-User-Key'] not in listed.text
    assert listed.json()['profiles'][0]['sample_audio_url'] == ''
    upload = await client.post('/v1/voice-profiles/upload-sample', headers=headers,
                               files={'sample': ('voice.wav', b'voice', 'audio/wav')})
    assert upload.status_code == 409
    create = await client.post('/v1/voice-profiles', headers=headers, json={
        'label': 'Parent', 'sample_audio_url': 'https://example.com/a.wav', 'consented': True,
    })
    assert create.status_code == 409
    activated = await client.patch('/v1/voice-profiles/old-voice', headers=headers, json={'active': True})
    assert activated.status_code == 409
    revoked = await client.post('/v1/voice-profiles/old-voice/revoke-consent', headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()['profile']['active'] is False
    assert (await client.delete('/v1/voice-profiles/old-voice', headers=headers)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['delete', 'revoke-consent', 'patch'])
async def test_failed_voice_erasure_survives_reference_removal(
    client, headers, db_session, monkeypatch, action,
):
    key = storage.voice_sample_prefix(headers['X-User-Key']) + 'sample.wav'
    profile = VoiceProfile(id='voice-retry', user_key=headers['X-User-Key'], label='Parent',
                           sample_audio_url=storage.canonical_media_url(key), consented=True, active=True)
    db_session.add(profile)
    await db_session.commit()

    async def unavailable(keys):
        return list(keys)
    monkeypatch.setattr(storage, 'delete_keys', unavailable)
    endpoint = '/v1/voice-profiles/voice-retry'
    if action == 'delete':
        response = await client.delete(endpoint, headers=headers)
    elif action == 'patch':
        response = await client.patch(endpoint, headers=headers, json={'consented': False})
    else:
        response = await client.post(endpoint + '/revoke-consent', headers=headers)
    assert response.status_code == 200
    assert response.json()['purge_retry_pending'] is True
    tasks = list((await db_session.execute(select(StoragePurgeTask).where(
        StoragePurgeTask.target == key, StoragePurgeTask.status == 'pending',
    ))).scalars())
    assert len(tasks) == 1
    deleted = []

    async def recovered(keys):
        deleted.extend(keys)
        return []
    monkeypatch.setattr(storage, 'delete_keys', recovered)
    assert await run_purge_tasks(db_session, tasks) == []
    assert deleted == [key]
    assert tasks[0].status == 'done'


def test_log_privacy_removes_credentials_child_payloads_and_signed_urls():
    user_key = '550e8400-e29b-41d4-a716-446655440000'
    event = {
        'event': 'provider failed', 'request_id': user_key, 'user_key': user_key,
        'error': 'Provider said private child description',
        'nested': {'payload': {'name': 'Private child'}, 'api_key': 'key-secret'},
        'url': 'https://media.example/photo?X-Amz-Signature=secret',
        'failed_keys': [f'voice-samples/{user_key}/sample.wav'],
        'error_code': 'IMAGE_FAILED', 'status': 503,
    }
    clean = redact_log_data(None, 'warning', event)
    assert clean['request_id'] == user_key  # correlation is a separate non-credential field
    assert clean['user_key'] == '[redacted]'
    assert clean['error_code'] == 'IMAGE_FAILED'
    clean.pop('request_id')
    encoded = json.dumps(clean)
    for secret in [user_key, 'Private child', 'private child description', 'key-secret', 'X-Amz-Signature']:
        assert secret not in encoded
