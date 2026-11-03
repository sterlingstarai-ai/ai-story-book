from datetime import timedelta

import pytest

from src.core.utils import utcnow
from src.models.db import StoragePurgeTask
from src.services.privacy_purge_health import MAX_PENDING_SECONDS, SAFE_CANCELLED_GUARDS, assess_purge_queue
from src.services.purge_queue import MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_normal_guard_grace_then_unfinished_work_alerts(db_session):
    now = utcnow()
    task = StoragePurgeTask(user_key='sensitive-user', reason='consent_revoke_inflight_images',
        kind='prefix', target='sensitive-target/', status='pending', attempts=0,
        created_at=now - timedelta(minutes=15), updated_at=now - timedelta(minutes=15))
    db_session.add(task)
    await db_session.commit()
    assert await assess_purge_queue(db_session, now=now) == {'status': 'OK', 'restore_authorized': False}
    task.created_at = now - timedelta(seconds=MAX_PENDING_SECONDS + 1)
    await db_session.commit()
    assert await assess_purge_queue(db_session, now=now) == {'status': 'ALERT', 'restore_authorized': False}
    task.status = 'done'
    await db_session.commit()
    assert await assess_purge_queue(db_session, now=now) == {'status': 'OK', 'restore_authorized': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,attempts,error', [
    ('failed', MAX_ATTEMPTS, 'storage_operation_failed'),
    ('pending', MAX_ATTEMPTS, None),
    ('pending', 1, 'storage_operation_failed'),
    ('unknown', 0, None),
    ('pending', -1, None),
])
async def test_failed_unretryable_and_unknown_tasks_alert_without_disclosure(db_session, status, attempts, error):
    now = utcnow()
    db_session.add(StoragePurgeTask(user_key='sensitive-user', reason='consent_revoke', kind='prefix',
        target='sensitive-target/', status=status, attempts=attempts, last_error=error,
        created_at=now, updated_at=now))
    await db_session.commit()
    assert await assess_purge_queue(db_session, now=now) == {'status': 'ALERT', 'restore_authorized': False}


@pytest.mark.asyncio
async def test_future_or_missing_dates_and_query_failure_alert(db_session):
    now = utcnow()
    task = StoragePurgeTask(user_key='sensitive-user', reason='consent_revoke', kind='keys',
        target='sensitive-target', status='pending', attempts=0, created_at=now + timedelta(hours=1), updated_at=now)
    db_session.add(task)
    await db_session.commit()
    assert (await assess_purge_queue(db_session, now=now))['status'] == 'ALERT'

    class BrokenSession:
        async def scalar(self, statement):
            raise RuntimeError('sensitive provider diagnostic')

    result = await assess_purge_queue(BrokenSession(), now=now)
    assert result == {'status': 'ALERT', 'restore_authorized': False}
    assert (await assess_purge_queue(db_session, now='not-a-time'))['status'] == 'ALERT'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', SAFE_CANCELLED_GUARDS)
async def test_only_known_successfully_cancelled_upload_guards_are_healthy(db_session, reason):
    now = utcnow()
    db_session.add(StoragePurgeTask(user_key='sensitive-user', reason=reason, kind='prefix',
        target='sensitive-target/', status='cancelled', attempts=0, created_at=now, updated_at=now))
    await db_session.commit()
    assert (await assess_purge_queue(db_session, now=now))['status'] == 'OK'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['consent_revoke', 'consent_photos_off', 'book_delete', 'account_deletion',
                                    'unrecognized_guard'])
async def test_cancelled_real_or_unknown_erasures_alert(db_session, reason):
    now = utcnow()
    db_session.add(StoragePurgeTask(user_key='sensitive-user', reason=reason, kind='prefix',
        target='sensitive-target/', status='cancelled', attempts=0, created_at=now, updated_at=now))
    await db_session.commit()
    assert (await assess_purge_queue(db_session, now=now))['status'] == 'ALERT'
