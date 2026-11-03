"""Failures in one durable maintenance queue must not suppress another."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.services import job_monitor


class MaintenanceSweepIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def run_cycles(self, *, job_failure=False, avatar_failure=False, purge_fails_once=False):
        monitor = job_monitor.JobMonitor()
        monitor._running = True
        job = AsyncMock(side_effect=RuntimeError("synthetic-secret-job") if job_failure else None)
        avatar = AsyncMock(side_effect=RuntimeError("synthetic-secret-avatar") if avatar_failure else None)
        purge = AsyncMock(side_effect=[RuntimeError("synthetic-secret-purge"), None]
                          if purge_fails_once else None)
        sleeps = [None, asyncio.CancelledError()] if purge_fails_once else [asyncio.CancelledError()]
        with patch.object(monitor, "check_and_recover_jobs", job), \
             patch("src.services.character_avatar.sweep_character_avatars", avatar), \
             patch("src.services.purge_queue.sweep_pending_purges", purge), \
             patch.object(job_monitor.asyncio, "sleep", AsyncMock(side_effect=sleeps)) as sleep, \
             patch.object(job_monitor.logger, "error") as error:
            with self.assertRaises(asyncio.CancelledError):
                await monitor._monitor_loop()
        self.assertNotIn("synthetic-secret", str(error.call_args_list))
        for call in sleep.call_args_list:
            self.assertEqual(call.args, (job_monitor.MONITOR_INTERVAL_SECONDS,))
        return job, avatar, purge

    async def test_avatar_failure_does_not_skip_purge_queue(self):
        job, avatar, purge = await self.run_cycles(avatar_failure=True)
        job.assert_awaited_once()
        avatar.assert_awaited_once()
        purge.assert_awaited_once()

    async def test_job_failure_does_not_skip_either_purge_queue(self):
        job, avatar, purge = await self.run_cycles(job_failure=True)
        job.assert_awaited_once()
        avatar.assert_awaited_once()
        purge.assert_awaited_once()

    async def test_failed_purge_is_retried_on_the_next_cycle(self):
        job, avatar, purge = await self.run_cycles(purge_fails_once=True)
        self.assertEqual(job.await_count, 2)
        self.assertEqual(avatar.await_count, 2)
        self.assertEqual(purge.await_count, 2)


@pytest.mark.asyncio
async def test_avatar_error_still_completes_persisted_purge(db_session, monkeypatch):
    """A real outbox row advances even if a different sweep raises."""
    from src.core import database
    from src.models.db import StoragePurgeTask
    from src.services import purge_queue

    task = StoragePurgeTask(user_key=None, reason="consent_revoke", kind="keys",
                            target='["synthetic-object"]', status="pending", attempts=1)
    db_session.add(task)
    await db_session.commit()
    task_id = task.id
    monkeypatch.setattr(database, "AsyncSessionLocal",
                        async_sessionmaker(db_session.bind, expire_on_commit=False))
    monitor = job_monitor.JobMonitor()
    monitor._running = True
    with patch.object(monitor, "check_and_recover_jobs", AsyncMock()), \
         patch("src.services.character_avatar.sweep_character_avatars",
               AsyncMock(side_effect=RuntimeError("synthetic-avatar-failure"))), \
         patch.object(purge_queue, "_execute_task", AsyncMock(return_value=[])) as delete, \
         patch.object(job_monitor.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            await monitor._monitor_loop()
    db_session.expire_all()
    stored = (await db_session.execute(select(StoragePurgeTask).where(
        StoragePurgeTask.id == task_id))).scalar_one()
    assert (stored.status, stored.attempts) == ("done", 2)
    delete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
