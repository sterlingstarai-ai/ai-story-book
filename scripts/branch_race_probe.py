"""Exercise branch graph locking against a disposable PostgreSQL database only."""
import asyncio
import json
import os

if os.environ.get('ASB_BRANCH_RACE_FIXTURE') != '1':
    raise RuntimeError('Explicit disposable fixture environment required')
if os.environ.get('DATABASE_URL') != 'postgresql://fixture:fixture@127.0.0.1:5432/fixture':
    raise RuntimeError('Unexpected fixture database identity')

from sqlalchemy import select, text  # noqa: E402
from src.core.database import AsyncSessionLocal, async_engine  # noqa: E402
from src.core.exceptions import ValidationError  # noqa: E402
from src.models.db import Base, Book, BranchStoryNode, Job  # noqa: E402
from src.routers import branch  # noqa: E402


def payload(key, overwrite=False):
    return branch.BranchInitializeRequest(nodes=[{'node_key': key, 'page_number': 1,
                                                  'text': key, 'options': []}],
                                          overwrite=overwrite)


async def wait_for_lock():
    for _ in range(100):
        async with AsyncSessionLocal() as db:
            waiting = await db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%books%FOR %'"))
        if waiting:
            return
        await asyncio.sleep(.05)
    raise RuntimeError('Expected PostgreSQL row lock wait was not observed')


async def main():
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        db.add(Job(id='fixture-job', user_key='fixture-owner', status='completed'))
        await db.flush()
        db.add(Book(id='fixture-book', job_id='fixture-job', user_key='fixture-owner',
                    title='fixture', language='ko', target_age='5-7', style='watercolor'))
        await db.commit()
    original = branch._owned_image_keys
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_after_lock(db, book):
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=10)
        return await original(db, book)

    try:
        branch._owned_image_keys = pause_after_lock
        async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
            one = asyncio.create_task(branch.initialize_branch_story('fixture-book', payload('first'), first, 'fixture-owner', None))
            await asyncio.wait_for(entered.wait(), timeout=10)
            two = asyncio.create_task(branch.initialize_branch_story('fixture-book', payload('second'), second, 'fixture-owner', None))
            await wait_for_lock()
            assert not two.done()
            release.set()
            await asyncio.wait_for(one, timeout=10)
            try:
                await asyncio.wait_for(two, timeout=10)
            except ValidationError:
                await second.rollback()
            else:
                raise AssertionError('Concurrent non-overwrite initialization was accepted')
        async with AsyncSessionLocal() as db:
            keys = (await db.scalars(select(BranchStoryNode.node_key))).all()
            assert keys == ['first'], keys
        entered.clear()
        release.clear()
        async with AsyncSessionLocal() as writer, AsyncSessionLocal() as reader:
            one = asyncio.create_task(branch.initialize_branch_story('fixture-book', payload('replacement', True), writer, 'fixture-owner', None))
            await asyncio.wait_for(entered.wait(), timeout=10)
            two = asyncio.create_task(branch.get_branch_story_graph('fixture-book', reader, 'fixture-owner', None))
            await wait_for_lock()
            assert not two.done()
            release.set()
            await asyncio.wait_for(one, timeout=10)
            graph = await asyncio.wait_for(two, timeout=10)
            assert [node['node_key'] for node in graph['nodes']] == ['replacement']
    finally:
        release.set()
        branch._owned_image_keys = original
        await async_engine.dispose()
    print(json.dumps({'status': 'BRANCH_POSTGRES_RACE_PASSED', 'synthetic_data_only': True}))


asyncio.run(main())
