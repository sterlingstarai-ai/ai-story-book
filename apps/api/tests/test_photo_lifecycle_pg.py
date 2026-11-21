"""Photo publication/withdrawal concurrency on disposable migrated PostgreSQL.

Opt in with the existing E2E_PG_DATABASE_URL contract. The runtime harness supplies
its isolated local PostgreSQL container; no ordinary pytest run connects to a
database here. Every test owns fresh UUID users and removes only its own rows.
AI and object storage are never contacted.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.core.consent import _has_active_photo_consent, require_photo_consent
from src.core.exceptions import AuthorizationError
from src.models.db import AccountIdentity, Book, Character, Job, Page, StoragePurgeTask, UserConsent
from src.routers.consent import revoke_consent
from src.services.account_recovery import credential_hash
from src.services.photo_lifecycle import lock_photo_account
from tests.test_pg_fk_erasure import PG_URL, pg_schema_at_head  # noqa: F401

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="E2E_PG_DATABASE_URL required for photo lifecycle concurrency"),
]


@pytest_asyncio.fixture
async def photo_pg(request, monkeypatch):
    request.getfixturevalue("pg_schema_at_head")
    from src.services import purge_queue

    monkeypatch.setattr(settings, "require_parental_consent_enabled", True)
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    deleted_assets = []

    async def erase_synthetic_asset(task):
        deleted_assets.append((task.kind, task.target))
        return []

    monkeypatch.setattr(purge_queue, "_execute_task", erase_synthetic_asset)
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    owners = [str(uuid.uuid4()), str(uuid.uuid4())]
    try:
        yield maker, owners, deleted_assets
    finally:
        async with maker() as cleanup:
            owned_books = select(Book.id).where(Book.user_key.in_(owners))
            await cleanup.execute(delete(Page).where(Page.book_id.in_(owned_books)))
            await cleanup.execute(delete(Book).where(Book.user_key.in_(owners)))
            for model in (Job, Character, UserConsent, StoragePurgeTask, AccountIdentity):
                await cleanup.execute(delete(model).where(model.user_key.in_(owners)))
            await cleanup.commit()
        await engine.dispose()


async def _start_waiter(maker, owner):
    """Expose its backend pid before waiting, so PG itself proves lock contention."""
    started = asyncio.get_running_loop().create_future()

    async def acquire():
        async with maker() as session:
            started.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
            await lock_photo_account(session, owner)
            await session.commit()

    task = asyncio.create_task(acquire())
    try:
        pid = await asyncio.wait_for(asyncio.shield(started), 5)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    return task, pid


async def _assert_waiting_in_postgres(maker, pid, task):
    """Poll a database lock condition, not an arbitrary delay or scheduler guess."""
    async with asyncio.timeout(5):
        async with maker() as observer:
            while True:
                assert not task.done(), "Same-owner publication escaped the held transaction lock"
                blocked = await observer.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                    "WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                ), {"pid": pid})
                if blocked:
                    return
                await asyncio.sleep(0.01)


async def _finish(task):
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _grant(maker, owner):
    async with maker() as session:
        session.add(UserConsent(
            user_key=owner, privacy=True, photos=True,
            data_processing=True, granted=True,
        ))
        await session.commit()


def _portrait(owner, identifier):
    return Character(
        id=identifier, user_key=owner, name="합성 인물",
        master_description="synthetic avatar only", appearance={}, clothing={},
        personality_traits=[], from_photo=True, avatar_status="approved",
    )


@pytest.mark.parametrize("enrolled", [False, True])
async def test_same_owner_serializes_with_or_without_identity_row(photo_pg, enrolled):
    maker, (owner, _), _ = photo_pg
    if enrolled:
        async with maker() as session:
            session.add(AccountIdentity(
                user_key=owner, device_key_hash=credential_hash(owner, kind="device")
            ))
            await session.commit()
    async with maker() as holder:
        await lock_photo_account(holder, owner)
        task, pid = await _start_waiter(maker, owner)
        try:
            await _assert_waiting_in_postgres(maker, pid, task)
            await holder.commit()
            await asyncio.wait_for(task, 5)
        finally:
            await _finish(task)
    async with maker() as verification:
        # Locking an unenrolled account must not create an identity or change
        # legacy authentication merely to obtain a mutex.
        assert (await verification.get(AccountIdentity, owner) is not None) is enrolled


async def test_different_owners_do_not_block_each_other(photo_pg):
    maker, (first_owner, other_owner), _ = photo_pg
    async with maker() as holder:
        await lock_photo_account(holder, first_owner)
        task, _ = await _start_waiter(maker, other_owner)
        try:
            await asyncio.wait_for(task, 5)
            assert holder.in_transaction()
        finally:
            await _finish(task)
            await holder.rollback()


async def test_rollback_releases_legacy_owner_transaction_lock(photo_pg):
    maker, (owner, _), _ = photo_pg
    async with maker() as holder:
        await lock_photo_account(holder, owner)
        task, pid = await _start_waiter(maker, owner)
        try:
            await _assert_waiting_in_postgres(maker, pid, task)
            await holder.rollback()
            await asyncio.wait_for(task, 5)
        finally:
            await _finish(task)


async def test_portrait_published_before_withdrawal_is_seen_and_erased(photo_pg):
    maker, (owner, _), deleted_assets = photo_pg
    await _grant(maker, owner)
    identifier = f"char-pg-{uuid.uuid4().hex}"
    started = asyncio.get_running_loop().create_future()

    async def withdraw():
        async with maker() as request:
            started.set_result(await request.scalar(text("SELECT pg_backend_pid()")))
            return await revoke_consent(db=request, user_key=owner)

    async with maker() as publishing:
        await lock_photo_account(publishing, owner)
        await require_photo_consent(publishing, owner)
        task = asyncio.create_task(withdraw())
        try:
            pid = await asyncio.wait_for(asyncio.shield(started), 5)
            await _assert_waiting_in_postgres(maker, pid, task)
            publishing.add(_portrait(owner, identifier))
            await publishing.commit()
            response = await asyncio.wait_for(task, 5)
            assert response.revoked is True
        finally:
            await _finish(task)

    async with maker() as verification:
        assert await verification.get(Character, identifier) is None
        assert await _has_active_photo_consent(verification, owner) is False
    assert ("prefix", f"characters/{identifier}/") in deleted_assets


async def test_withdrawal_committed_first_blocks_waiting_publication(photo_pg):
    maker, (owner, _), _ = photo_pg
    await _grant(maker, owner)
    identifier = f"char-pg-{uuid.uuid4().hex}"
    started = asyncio.get_running_loop().create_future()

    async def publish():
        async with maker() as request:
            started.set_result(await request.scalar(text("SELECT pg_backend_pid()")))
            await lock_photo_account(request, owner)
            await require_photo_consent(request, owner)
            request.add(_portrait(owner, identifier))
            await request.commit()

    async with maker() as withdrawal:
        await lock_photo_account(withdrawal, owner)
        task = asyncio.create_task(publish())
        try:
            pid = await asyncio.wait_for(asyncio.shield(started), 5)
            await _assert_waiting_in_postgres(maker, pid, task)
            response = await revoke_consent(db=withdrawal, user_key=owner)
            assert response.revoked is True
            with pytest.raises(AuthorizationError):
                await asyncio.wait_for(task, 5)
        finally:
            await _finish(task)

    async with maker() as verification:
        assert await verification.get(Character, identifier) is None
        assert await _has_active_photo_consent(verification, owner) is False
        assert list((await verification.execute(
            select(StoragePurgeTask).where(StoragePurgeTask.user_key == owner)
        )).scalars()) == []


async def test_book_delete_waits_for_verified_edit_and_erases_latest_image(photo_pg, monkeypatch):
    """The real delete route waits at the owner lock, before its child-first SQL."""
    from src.routers.library import delete_book
    from src.services import illustration_quality_edits
    from src.services.storage import canonical_media_url
    from tests.factories import make_book_rows

    maker, (owner, _), deleted_assets = photo_pg
    await _grant(maker, owner)
    book_id = f"book-pg-{uuid.uuid4().hex}"
    page_key = f"images/synthetic/{book_id}/edited.png"
    monkeypatch.setattr(illustration_quality_edits, "AsyncSessionLocal", maker)
    async with maker() as seed:
        rows = make_book_rows([(book_id, owner)])
        next(row for row in rows if isinstance(row, Job)).photo_derived = True
        seed.add_all(rows)
        await seed.flush()
        seed.add(Page(book_id=book_id, page_number=1, text="Synthetic story."))
        await seed.commit()
    snapshot = await illustration_quality_edits.load_book_snapshot(book_id, user_key=owner)
    started = asyncio.get_running_loop().create_future()

    async def erase_book():
        async with maker() as request:
            started.set_result(await request.scalar(text("SELECT pg_backend_pid()")))
            return await delete_book(book_id, db=request, user_key=owner, profile_id=None)

    async with maker() as editing:
        _, pages = await illustration_quality_edits._locked_snapshot(editing, snapshot)
        task = asyncio.create_task(erase_book())
        try:
            pid = await asyncio.wait_for(asyncio.shield(started), 5)
            await _assert_waiting_in_postgres(maker, pid, task)
            # Erasure must inventory this newly committed key, not its old snapshot.
            pages[1].image_url = canonical_media_url(page_key)
            await editing.commit()
            response = await asyncio.wait_for(task, 5)
            assert response["status"] == "success"
            assert response["purge_retry_pending"] is False
        finally:
            await _finish(task)

    async with maker() as verification:
        assert await verification.get(Book, book_id) is None
        assert await verification.scalar(select(Page.id).where(Page.book_id == book_id)) is None
    assert ("keys", page_key) in deleted_assets


async def test_withdrawal_waits_for_http_body_but_not_model_response(photo_pg, monkeypatch):
    """Real HTTPX/HTTPCore events on loopback, real PG locks, synthetic bytes."""
    import httpx
    from src.core import database
    from src.core.exceptions import APIError
    from src.services.generation_consent import post_with_consent, provider_consent_scope, require_active_book_job

    maker, (owner, _), _ = photo_pg
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    await _grant(maker, owner)
    job_id = f"job_{uuid.uuid4().hex}"
    async with maker() as db:
        db.add(Job(id=job_id, user_key=owner, status="running"))
        await db.commit()

    sending, allow_body, received, allow_response = (asyncio.Event() for _ in range(4))
    requests = []

    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            requests.append(await reader.readuntil(b"\r\n0\r\n\r\n"))
            received.set()
            await allow_response.wait()
            writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def payload():
        sending.set()
        await allow_body.wait()
        yield b"synthetic"

    async def authorize(db):
        await require_active_book_job(db, job_id, owner)

    started = asyncio.get_running_loop().create_future()

    async def withdraw():
        async with maker() as db:
            started.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            await revoke_consent(db=db, user_key=owner)

    async with await asyncio.start_server(handle, "127.0.0.1", 0) as server:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
        async with httpx.AsyncClient(trust_env=False) as client:
            with provider_consent_scope(authorize):
                request = asyncio.create_task(post_with_consent(client, url, content=payload()))
                withdrawal = None
                try:
                    await asyncio.wait_for(sending.wait(), 5)
                    withdrawal = asyncio.create_task(withdraw())
                    await _assert_waiting_in_postgres(maker, await started, withdrawal)
                    allow_body.set()
                    await asyncio.wait_for(received.wait(), 5)
                    await asyncio.wait_for(withdrawal, 5)
                    assert not request.done()
                    with pytest.raises(APIError) as denied:
                        await post_with_consent(client, url, content=b"synthetic")
                    assert denied.value.error_code == "PARENTAL_CONSENT_REQUIRED"
                    allow_response.set()
                    assert (await asyncio.wait_for(request, 5)).status_code == 204
                    assert len(requests) == 1
                finally:
                    allow_body.set()
                    allow_response.set()
                    await _finish(request)
                    if withdrawal is not None:
                        await _finish(withdrawal)


async def test_sla_monitor_does_not_hold_job_row_while_waiting_for_withdrawal(photo_pg):
    from src.services.job_monitor import job_monitor

    maker, (owner, _), _ = photo_pg
    await _grant(maker, owner)
    job_id = f"job_{uuid.uuid4().hex}"
    async with maker() as setup:
        setup.add(Job(id=job_id, user_key=owner, status="running"))
        await setup.commit()
    started = asyncio.get_running_loop().create_future()

    async def expire():
        async with maker() as db:
            job = await db.get(Job, job_id)
            started.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            await job_monitor._mark_job_failed(db, job, "SLA_BREACH", "synthetic timeout")
            await db.commit()

    async with maker() as withdrawal:
        await lock_photo_account(withdrawal, owner)
        task = asyncio.create_task(expire())
        try:
            await _assert_waiting_in_postgres(maker, await started, task)
            await asyncio.wait_for(revoke_consent(db=withdrawal, user_key=owner), 5)
            await asyncio.wait_for(task, 5)
        finally:
            await _finish(task)
    async with maker() as verification:
        assert await verification.get(Job, job_id) is None


@pytest.mark.parametrize("tracked", [False, True])
async def test_narration_dispatch_completes_with_one_connection(photo_pg, monkeypatch, tracked):
    from unittest.mock import AsyncMock

    import httpx
    from sqlalchemy.pool import AsyncAdaptedQueuePool
    from src.core import database
    from src.core.rate_limit import rate_limiter
    from src.routers.books import get_page_audio
    from src.services.job_runners import generate_audio_pages
    from src.services.storage import storage_service
    from src.services.tts import OpenAITTSProvider, tts_service
    from tests.factories import make_book_rows
    from tests.test_narration_voices import _LockRedis

    setup, (owner, _), _ = photo_pg
    await _grant(setup, owner)
    book_id, operation = f"book-{uuid.uuid4().hex}", f"audio_{uuid.uuid4().hex}"
    async with setup() as db:
        rows = make_book_rows([(book_id, owner)])
        book = next(row for row in rows if isinstance(row, Book))
        book.target_age = "3-5"
        db.add_all(rows)
        db.add(Job(id=operation, user_key=owner, status="running"))
        await db.flush()
        page = Page(book_id=book_id, page_number=1, text="합성 본문")
        db.add(page)
        await db.commit()
        page_id = page.id

    engine = create_async_engine(PG_URL, poolclass=AsyncAdaptedQueuePool, pool_size=1,
                                 max_overflow=0, pool_timeout=1)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=_LockRedis()))
    monkeypatch.setattr(settings, "openai_tts_api_key", "synthetic")
    monkeypatch.setattr(tts_service, "_provider", OpenAITTSProvider())
    monkeypatch.setattr("src.services.tts.require_daily_generation_budget", AsyncMock())
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(return_value="https://example.invalid/voice.mp3"))
    send = AsyncMock(return_value=httpx.Response(200, content=b"ID3-test", headers={"content-type": "audio/mpeg"}))
    monkeypatch.setattr(httpx.AsyncClient, "post", send)
    try:
        if tracked:
            result = await generate_audio_pages(book_id, [{"page_id": page_id, "page_number": 1}],
                                                audio_job_id=operation)
            assert result == (1, [])
        else:
            async with maker() as db:
                result = await get_page_audio(book_id, 1, language="ko", db=db, user_key=owner, profile_id=None)
                assert result["audio_url"].endswith("voice.mp3")
        send.assert_awaited_once()
    finally:
        await engine.dispose()
