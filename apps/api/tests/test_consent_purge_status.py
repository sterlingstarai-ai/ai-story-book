"""Consent stays committed while unresolved photo erasure remains visible."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from src.models.db import Job, StoragePurgeTask
from src.routers.consent import _photo_purge_incomplete
from src.services import purge_queue
from tests.test_parental_consent import _character

OWNER = '77777777-7777-4777-8777-777777777777'
OTHER = '88888888-8888-4888-8888-888888888888'
HEADERS = {'X-User-Key': OWNER}
GRANT = {'privacy': True, 'photos': True, 'data_processing': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['revoke', 'photos_off'])
async def test_failed_purge_is_visible_and_persists_after_successful_consent(client, db_session, monkeypatch, operation):
    assert (await client.post('/v1/consent', headers=HEADERS, json=GRANT)).json()['purge_incomplete'] is False
    db_session.add(_character('photo-consent-fixture', OWNER, True))
    await db_session.commit()

    async def failed(task):
        raise RuntimeError('sensitive provider diagnostic')

    monkeypatch.setattr(purge_queue, '_execute_task', failed)
    if operation == 'revoke':
        response = await client.post('/v1/consent/revoke', headers=HEADERS)
        assert response.json()['revoked'] is True
        assert response.json()['granted'] is False
    else:
        response = await client.post('/v1/consent', headers=HEADERS, json={**GRANT, 'photos': False})
        assert response.json()['granted'] is True
        assert response.json()['photos'] is False
    assert response.status_code == 200
    assert response.json()['purge_incomplete'] is True
    assert 'sensitive provider diagnostic' not in response.text
    assert (await client.get('/v1/consent', headers=HEADERS)).json()['purge_incomplete'] is True
    rows = (await db_session.execute(select(StoragePurgeTask).where(StoragePurgeTask.user_key == OWNER))).scalars().all()
    assert rows and any(task.status == 'pending' for task in rows)
    for task in rows:
        task.status = 'done'
    await db_session.commit()
    assert (await client.get('/v1/consent', headers=HEADERS)).json()['purge_incomplete'] is False


@pytest.mark.asyncio
async def test_delayed_generation_guards_and_prior_failed_tasks_are_scoped_to_owner(client, db_session, monkeypatch):
    async def successful(task):
        return []

    monkeypatch.setattr(purge_queue, '_execute_task', successful)
    assert (await client.post('/v1/consent', headers=HEADERS, json=GRANT)).status_code == 200
    char = _character('photo-inflight-fixture', OWNER, True)
    char.avatar_status = 'generating'
    db_session.add(char)
    db_session.add(Job(id='job-inflight-fixture', user_key=OWNER, status='running', photo_derived=True))
    await db_session.commit()
    response = await client.post('/v1/consent', headers=HEADERS, json={**GRANT, 'photos': False})
    assert response.status_code == 200 and response.json()['purge_incomplete'] is True
    tasks = (await db_session.execute(select(StoragePurgeTask).where(StoragePurgeTask.user_key == OWNER))).scalars().all()
    deferred = {task.reason for task in tasks if task.status == 'pending'}
    assert {'consent_photos_off_inflight_images', 'consent_photos_off_inflight_avatar'} <= deferred
    assert (await client.get('/v1/consent', headers={'X-User-Key': OTHER})).json()['purge_incomplete'] is False

    # A regrant cannot erase awareness of the old unresolved photo tasks.
    assert (await client.post('/v1/consent', headers=HEADERS, json=GRANT)).json()['purge_incomplete'] is True
    for task in tasks:
        if task.status == 'pending':
            task.status = 'failed'
    await db_session.commit()
    assert (await client.get('/v1/consent', headers=HEADERS)).json()['purge_incomplete'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['unknown', 'failed', 'cancelled'])
async def test_unknown_status_or_failed_status_query_is_never_reported_complete(db_session, status):
    db_session.add(StoragePurgeTask(user_key=OWNER, reason='consent_revoke', kind='prefix',
                                    target='private-test/', status=status))
    await db_session.commit()
    assert await _photo_purge_incomplete(db_session, OWNER) is True

    class BrokenSession:
        async def execute(self, statement):
            raise SQLAlchemyError('sensitive database diagnostic')

    assert await _photo_purge_incomplete(BrokenSession(), OWNER) is True
