"""Concurrent one-time account recovery against migrated PostgreSQL, never SQLite."""

import asyncio
import secrets
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.exceptions import APIError
from src.models.db import AccountIdentity
from src.services.account_recovery import (
    issue_recovery_code,
    recover_account,
    resolve_user_key,
    revoke_deleted_account,
)
from tests.test_pg_fk_erasure import PG_URL, pg_schema_at_head  # noqa: F401

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="E2E_PG_DATABASE_URL required for recovery concurrency"),
]


@pytest_asyncio.fixture
async def recovery_pg(request):
    request.getfixturevalue("pg_schema_at_head")
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_key = str(uuid.uuid4())
    async with maker() as session:
        code, _ = await issue_recovery_code(session, user_key, user_key)
    yield maker, user_key, code
    async with maker() as session:
        await session.execute(delete(AccountIdentity).where(AccountIdentity.user_key == user_key))
        await session.commit()
    await engine.dispose()


def device():
    return "asb_device_" + secrets.token_urlsafe(32)


async def attempt(maker, code, new_key):
    async with maker() as session:
        try:
            return await recover_account(session, code, new_key)
        except APIError as exc:
            return exc.status_code


async def test_only_one_competing_device_can_redeem(recovery_pg):
    maker, user_key, code = recovery_pg
    keys = [device(), device()]
    results = await asyncio.gather(*(attempt(maker, code, key) for key in keys))
    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(result == 401 for result in results) == 1
    async with maker() as session:
        for key, result in zip(keys, results):
            if isinstance(result, tuple):
                assert await resolve_user_key(session, key) == user_key
            else:
                with pytest.raises(APIError):
                    await resolve_user_key(session, key)
        with pytest.raises(APIError):
            await resolve_user_key(session, user_key)


async def test_concurrent_exact_retry_keeps_same_session_without_secret_replay(recovery_pg):
    maker, user_key, code = recovery_pg
    key = device()
    results = await asyncio.gather(attempt(maker, code, key), attempt(maker, code, key))
    assert all(isinstance(result, tuple) for result in results)
    assert sum(result[0] is None for result in results) == 1
    async with maker() as session:
        assert await resolve_user_key(session, key) == user_key


async def test_code_rotation_and_recovery_have_single_winner(recovery_pg):
    maker, user_key, code = recovery_pg
    key = device()

    async def rotate():
        async with maker() as session:
            try:
                return await issue_recovery_code(session, user_key, user_key)
            except APIError as exc:
                return exc.status_code

    results = await asyncio.gather(attempt(maker, code, key), rotate())
    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(result == 401 for result in results) == 1


async def test_recovery_and_erasure_cannot_leave_a_live_deleted_session(recovery_pg):
    maker, user_key, code = recovery_pg
    key = device()

    async def erase():
        async with maker() as session:
            try:
                await revoke_deleted_account(session, user_key, user_key)
                await session.commit()
                return "deleted"
            except APIError as exc:
                return exc.status_code

    restored, erased = await asyncio.gather(attempt(maker, code, key), erase())
    if isinstance(restored, tuple):
        assert erased == 401
        async with maker() as session:
            assert await resolve_user_key(session, key) == user_key
    else:
        assert restored == 401 and erased == "deleted"
        async with maker() as session:
            with pytest.raises(APIError):
                await resolve_user_key(session, key)
