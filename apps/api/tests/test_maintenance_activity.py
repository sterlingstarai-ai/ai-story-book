import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core import database, maintenance_activity as activity_module
from src.core.utils import utcnow
from src.models.db import Character, Job, PrivacyJournalOutbox, StoragePurgeTask
from src.services import job_monitor


@pytest.mark.asyncio
@pytest.mark.parametrize('when', ['before_wait', 'during_wait', 'thread'])
async def test_request_wakeup_is_not_lost(when):
    activity = activity_module.MaintenanceActivity()
    activity.bind()
    observed = activity.version
    try:
        if when == 'before_wait':
            activity.notify()
        waiter = asyncio.create_task(activity.wait(observed, 30))
        await asyncio.sleep(0)
        if when == 'during_wait':
            activity.notify()
        elif when == 'thread':
            await asyncio.to_thread(activity.notify)
        await asyncio.wait_for(waiter, .5)
        assert activity.version == observed + 1
        # A prior signal cannot cause every later cycle to run immediately.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(activity.wait(activity.version, 30), .01)
    finally:
        activity.unbind()


@pytest.mark.asyncio
async def test_only_successful_request_commits_wake_maintenance(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(activity_module.maintenance_activity, 'notify', lambda: calls.append(True))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(database, 'AsyncSessionLocal', factory)
    request = database.get_db()
    session = await request.__anext__()
    try:
        await session.rollback()
        assert calls == []
        await session.commit()
        assert calls == [True]
        async with factory() as background:
            await background.commit()
        assert calls == [True]
    finally:
        await request.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('queue', ['job', 'purge', 'avatar', 'privacy'])
async def test_any_durable_work_prevents_idle_backoff(db_session, monkeypatch, queue):
    monkeypatch.setattr(job_monitor, 'AsyncSessionLocal',
                        async_sessionmaker(db_session.bind, expire_on_commit=False))
    monkeypatch.setattr(job_monitor.settings, 'privacy_journal_enabled', True)
    monitor = job_monitor.JobMonitor()
    assert await monitor.has_pending_work() is False
    rows = {
        'job': lambda: Job(id='maintenance-job', status='queued', user_key='fixture'),
        'purge': lambda: StoragePurgeTask(reason='fixture', kind='keys', target='[]', status='pending'),
        'avatar': lambda: Character(id='fixture-avatar', name='Synthetic', master_description='fixture',
            appearance={}, clothing={}, personality_traits=[], from_photo=True,
            avatar_status='preview', avatar_expires_at=utcnow() + timedelta(hours=1), user_key='fixture'),
        'privacy': lambda: PrivacyJournalOutbox(event_id='a'*32, user_key='fixture', revision=1,
                                               action='credential_revoke'),
    }
    row = rows[queue]()
    db_session.add(row)
    await db_session.commit()
    assert await monitor.has_pending_work() is True
    if queue == 'job':
        row.status = 'done'
    elif queue == 'purge':
        row.status = 'done'
    elif queue == 'avatar':
        row.avatar_status = 'approved'
    else:
        row.published_at = utcnow()
    await db_session.commit()
    assert await monitor.has_pending_work() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(('pending', 'error', 'delay'), [(False, False, 987),
                                                       (True, False, 300), (False, True, 300)])
async def test_only_proven_idle_sweeps_use_the_aligned_long_interval(monkeypatch, pending, error, delay):
    from src.services import character_avatar, privacy_journal_runtime, purge_queue

    monitor = job_monitor.JobMonitor()
    monitor._running = True
    monkeypatch.setattr(monitor, 'check_and_recover_jobs',
                        AsyncMock(side_effect=RuntimeError('fixture') if error else None))
    monkeypatch.setattr(monitor, 'has_pending_work', AsyncMock(return_value=pending))
    monkeypatch.setattr(character_avatar, 'sweep_character_avatars', AsyncMock())
    monkeypatch.setattr(purge_queue, 'sweep_pending_purges', AsyncMock())
    monkeypatch.setattr(privacy_journal_runtime, 'configured_journal', lambda: None)
    monkeypatch.setattr(job_monitor, 'seconds_to_tick', lambda: 987)
    wait = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(activity_module.maintenance_activity, 'wait', wait)
    with pytest.raises(asyncio.CancelledError):
        await monitor._monitor_loop()
    assert wait.call_args.args == (activity_module.maintenance_activity.version, delay)


@pytest.mark.parametrize(('epoch', 'interval', 'delay'), [(0, 1800, 1800),
                                                       (1799, 1800, 1), (3601, 3600, 3599)])
def test_idle_ticks_share_calendar_boundaries(monkeypatch, epoch, interval, delay):
    monkeypatch.setattr(activity_module.time, 'time', lambda: epoch)
    assert activity_module.seconds_to_tick(interval) == delay
