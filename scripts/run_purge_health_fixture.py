"""Exercise privacy purge monitoring only in the local disposable fixture."""
import asyncio
from datetime import timedelta

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    from sqlalchemy import text
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.utils import utcnow
    from src.models.db import StoragePurgeTask
    from src.services.privacy_purge_health import MAX_PENDING_SECONDS, assess_purge_queue
    from src.services.purge_queue import MAX_ATTEMPTS

    now = utcnow()
    try:
        async with AsyncSessionLocal() as db:
            if (await assess_purge_queue(db, now=now))['status'] != 'OK':
                raise RuntimeError('Fresh synthetic purge queue is unhealthy')
            task = StoragePurgeTask(user_key='00000000-0000-4000-8000-000000000009',
                reason='consent_revoke_inflight_images', kind='prefix', target='synthetic-private/',
                status='pending', attempts=0, created_at=now, updated_at=now)
            db.add(task)
            await db.commit()
            if (await assess_purge_queue(db, now=now))['status'] != 'OK':
                raise RuntimeError('Synthetic grace period was rejected')
            task.created_at = now - timedelta(seconds=MAX_PENDING_SECONDS + 1)
            await db.commit()
            if (await assess_purge_queue(db, now=now))['status'] != 'ALERT':
                raise RuntimeError('Synthetic stale task was accepted')
            task.created_at = now
            task.attempts = MAX_ATTEMPTS
            await db.commit()
            if (await assess_purge_queue(db, now=now))['status'] != 'ALERT':
                raise RuntimeError('Synthetic exhausted task was accepted')
            task.status = 'failed'
            await db.commit()
            if (await assess_purge_queue(db, now=now))['status'] != 'ALERT':
                raise RuntimeError('Synthetic failed task was accepted')
            task.status = 'cancelled'
            await db.commit()
            if (await assess_purge_queue(db, now=now))['status'] != 'ALERT':
                raise RuntimeError('Synthetic cancelled erasure was accepted')
            task.reason = 'character_source_upload_guard'
            await db.commit()
            if (await assess_purge_queue(db, now=now))['status'] != 'OK':
                raise RuntimeError('Synthetic cancelled upload guard was rejected')
            task.status = 'done'
            await db.commit()
            if (await assess_purge_queue(db, now=now)) != {'status': 'OK', 'restore_authorized': False}:
                raise RuntimeError('Completed synthetic task remains unhealthy')
            await db.delete(task)
            await db.commit()
            await db.execute(text('SET TRANSACTION READ ONLY'))
            await db.execute(text('SET LOCAL search_path = pg_catalog, public'))
            if ((await db.scalar(text('SHOW transaction_read_only'))) != 'on'
                    or (await assess_purge_queue(db, now=now))['status'] != 'OK'):
                raise RuntimeError('Synthetic read-only monitor check failed')
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
