"""Real PostgreSQL concurrency probe; use only with a disposable isolated DB."""
import asyncio
import json
import os

if os.environ.get('ASB_RECEIPT_RACE_FIXTURE') != '1':
    raise RuntimeError('Explicit disposable fixture environment required')
if os.environ.get('DATABASE_URL') != 'postgresql://fixture:fixture@127.0.0.1:5432/fixture':
    raise RuntimeError('Unexpected fixture database identity')

from sqlalchemy import text  # noqa: E402
from src.core.database import AsyncSessionLocal, async_engine  # noqa: E402
from src.core.exceptions import ValidationError  # noqa: E402
from src.models.db import Base, Book, BookDeletionReceipt, ChildProfile, Job  # noqa: E402
from src.routers import library, profiles  # noqa: E402


async def no_storage(_db, _tasks):
    # This test exercises database ordering, never object storage.
    return []


async def wait_for_database_waiter():
    for _ in range(100):
        async with AsyncSessionLocal() as db:
            count = await db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted"))
        if count:
            return
        await asyncio.sleep(.05)
    raise RuntimeError('Expected PostgreSQL advisory lock wait was not observed')


async def setup(prefix):
    user = prefix + '-owner'
    profile = prefix + '-profile'
    book = prefix + '-book'
    request = ('a' if prefix == 'first' else 'b') * 32
    async with AsyncSessionLocal() as db:
        db.add(ChildProfile(id=profile, user_key=user, name='fixture', age_band='5-7', is_default=False))
        db.add(Job(id=prefix + '-job', user_key=user, status='completed'))
        await db.flush()
        db.add(Book(id=book, job_id=prefix + '-job', user_key=user, profile_id=profile,
                    title='fixture', language='ko', target_age='5-7', style='watercolor'))
        await db.commit()
    return user, profile, book, request


async def book_first():
    user, profile, book, request = await setup('first')
    acquired, release = asyncio.Event(), asyncio.Event()
    original = library.lock_photo_account

    async def pause(db, user_key):
        await original(db, user_key)
        acquired.set()
        await asyncio.wait_for(release.wait(), timeout=10)

    library.lock_photo_account = pause
    try:
        async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
            one = asyncio.create_task(library.delete_book(book, db=first, user_key=user,
                                                         profile_id=profile, x_deletion_request_id=request))
            await asyncio.wait_for(acquired.wait(), timeout=10)
            two = asyncio.create_task(profiles.delete_profile(profile, db=second, user_key=user))
            await wait_for_database_waiter()
            assert not two.done()
            release.set()
            result = await asyncio.wait_for(one, timeout=15)
            assert result['deletion_committed'] is True
            await asyncio.wait_for(two, timeout=15)
        async with AsyncSessionLocal() as verify:
            assert await verify.get(Book, book) is None
            assert await verify.get(ChildProfile, profile) is None
            assert await verify.get(BookDeletionReceipt, (user, request)) is None
    finally:
        release.set()
        library.lock_photo_account = original


async def profile_first():
    user, profile, book, request = await setup('second')
    acquired, release = asyncio.Event(), asyncio.Event()
    original = profiles.lock_photo_account

    async def pause(db, user_key):
        await original(db, user_key)
        acquired.set()
        await asyncio.wait_for(release.wait(), timeout=10)

    profiles.lock_photo_account = pause
    try:
        async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
            one = asyncio.create_task(profiles.delete_profile(profile, db=first, user_key=user))
            await asyncio.wait_for(acquired.wait(), timeout=10)
            two = asyncio.create_task(library.delete_book(book, db=second, user_key=user,
                                                         profile_id=profile, x_deletion_request_id=request))
            await wait_for_database_waiter()
            assert not two.done()
            release.set()
            await asyncio.wait_for(one, timeout=15)
            try:
                await asyncio.wait_for(two, timeout=15)
            except ValidationError:
                await second.rollback()
            else:
                raise AssertionError('Deletion accepted a deleted profile')
        async with AsyncSessionLocal() as verify:
            assert await verify.get(ChildProfile, profile) is None
            assert await verify.get(Book, book) is not None
            assert await verify.get(BookDeletionReceipt, (user, request)) is None
    finally:
        release.set()
        profiles.lock_photo_account = original


async def main():
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    library.run_purge_tasks = no_storage
    try:
        await book_first()
        await profile_first()
    finally:
        await async_engine.dispose()
    print(json.dumps({'status': 'RECEIPT_POSTGRES_RACE_PASSED', 'synthetic_data_only': True,
                      'real_storage_verified': False, 'production_authorized': False}))


asyncio.run(main())
