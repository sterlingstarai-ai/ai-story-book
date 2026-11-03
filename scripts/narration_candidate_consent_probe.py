"""Exercise consent status in a candidate image using only a disposable SQLite DB."""
import asyncio
import json
import os

if os.environ.get('ASB_NARRATION_ISOLATED_PROBE') != '1':
    raise RuntimeError('This probe must run in an explicitly isolated fixture')
if os.environ.get('DATABASE_URL') != 'sqlite+aiosqlite:////tmp/fixture.db':
    raise RuntimeError('A disposable fixture database is required')

import httpx  # noqa: E402
from sqlalchemy import update  # noqa: E402

from src.core.database import AsyncSessionLocal, async_engine  # noqa: E402
from src.main import app  # noqa: E402
from src.models.db import Base, StoragePurgeTask  # noqa: E402

OWNER = '77777777-7777-4777-8777-777777777777'


async def main():
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as client:
        headers = {'X-User-Key': OWNER}
        result = await client.post('/v1/consent', headers=headers,
                                   json={'privacy': True, 'photos': True, 'data_processing': True})
        assert result.status_code == 200 and result.json()['purge_incomplete'] is False
        async with AsyncSessionLocal() as db:
            db.add(StoragePurgeTask(user_key=OWNER, reason='consent_revoke', kind='prefix',
                                    target='fixture/', status='pending'))
            await db.commit()
        result = await client.get('/v1/consent', headers=headers)
        assert result.status_code == 200 and result.json()['purge_incomplete'] is True
        async with AsyncSessionLocal() as db:
            await db.execute(update(StoragePurgeTask).where(StoragePurgeTask.user_key == OWNER)
                             .values(status='done'))
            await db.commit()
        result = await client.get('/v1/consent', headers=headers)
        assert result.status_code == 200 and result.json()['purge_incomplete'] is False
        result = await client.post('/v1/consent/revoke', headers=headers)
        assert result.status_code == 200 and result.json()['revoked'] is True
    await async_engine.dispose()
    print(json.dumps({'status': 'CONSENT_STATUS_FIXTURE_PASSED', 'synthetic_data_only': True,
                      'storage_deletion_verified': False, 'production_authorized': False}))


asyncio.run(main())
