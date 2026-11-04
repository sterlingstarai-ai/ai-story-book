"""Concurrent HTTP retries against disposable PostgreSQL migrated to head.

Opt in with E2E_PG_DATABASE_URL. Database transactions and credits are real;
provider dispatch and the Redis budget adapter are spies, with no paid calls.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.core.database import get_db
from src.main import app
from src.models.db import AccountIdentity, ChildProfile, CreditTransaction, Job, UserCredits
from src.routers import books
from src.services import photo_lifecycle
from tests.test_pg_fk_erasure import PG_URL, pg_schema_at_head  # noqa: F401


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="E2E_PG_DATABASE_URL required for creation races"),
]


@pytest_asyncio.fixture
async def creation_pg(request):
    request.getfixturevalue("pg_schema_at_head")
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    owner = str(uuid.uuid4())
    profile_id = f"profile-{uuid.uuid4().hex}"
    try:
        yield maker, owner, profile_id
    finally:
        async with maker() as cleanup:
            for model in (CreditTransaction, Job, UserCredits, ChildProfile, AccountIdentity):
                await cleanup.execute(delete(model).where(model.user_key == owner))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.parametrize("starting_credits", [1, 3])
async def test_four_http_retries_commit_one_job_credit_budget_and_dispatch(
    creation_pg, valid_book_spec, monkeypatch, starting_credits
):
    maker, owner, profile_id = creation_pg
    async with maker() as seed:
        seed.add(UserCredits(user_key=owner, credits=starting_credits))
        seed.add(ChildProfile(id=profile_id, user_key=owner, name="합성 인물"))
        await seed.commit()

    dispatch = AsyncMock()
    budget = AsyncMock(return_value=(True, 1))
    monkeypatch.setattr(books, "schedule_book_generation", dispatch)
    monkeypatch.setattr(books, "consume_daily_generation_budget", budget)

    # Each request reaches the real advisory lock from a different PostgreSQL
    # connection at the same barrier. The nested same-transaction lock call in
    # _create_job_with_credit must not join the barrier a second time.
    barrier = asyncio.Barrier(4)
    connections = set()
    entered_sessions = set()
    real_lock = photo_lifecycle.lock_photo_account

    async def synchronized_lock(db, user_key):
        session_id = id(db)
        if session_id not in entered_sessions:
            entered_sessions.add(session_id)
            connections.add(await db.scalar(text("SELECT pg_backend_pid()")))
            await asyncio.wait_for(barrier.wait(), 10)
        await real_lock(db, user_key)

    monkeypatch.setattr(photo_lifecycle, "lock_photo_account", synchronized_lock)

    async def request_session():
        async with maker() as session:
            yield session

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = request_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            responses = await asyncio.wait_for(asyncio.gather(*[
                http.post(
                    "/v1/books", json=valid_book_spec,
                    headers={
                        "X-User-Key": owner,
                        "X-Profile-Id": profile_id,
                        "X-Idempotency-Key": "same-concurrent-attempt",
                    },
                )
                for _ in range(4)
            ]), 20)
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous

    assert len(connections) == 4
    assert [response.status_code for response in responses] == [200] * 4
    assert len({response.json()["job_id"] for response in responses}) == 1
    async with maker() as verification:
        assert await verification.scalar(select(func.count(Job.id)).where(Job.user_key == owner)) == 1
        job = await verification.scalar(select(Job).where(Job.user_key == owner))
        assert job.profile_id == profile_id
        assert await verification.scalar(select(UserCredits.credits).where(UserCredits.user_key == owner)) == starting_credits - 1
        assert await verification.scalar(select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_key == owner,
            CreditTransaction.transaction_type == "usage",
        )) == 1
    budget.assert_awaited_once()
    dispatch.assert_awaited_once()


@pytest.mark.parametrize("first_book_trial,amount,transaction_type", [(False, 2, "free_monthly"), (True, 1, "bonus")])
async def test_concurrent_free_allowance_is_claimed_once(creation_pg, monkeypatch, first_book_trial, amount, transaction_type):
    from src.services.credits import CreditsService
    monkeypatch.setattr(settings, "free_plan_first_book_trial", first_book_trial)
    maker, owner, _ = creation_pg
    service = CreditsService()
    async def read_new_balance():
        async with maker() as session:
            return await service.get_credits(session, owner)
    balances = await asyncio.wait_for(asyncio.gather(*[read_new_balance() for _ in range(6)]), 15)
    assert balances == [amount] * 6
    async with maker() as session:
        grants = (await session.execute(select(CreditTransaction).where(
            CreditTransaction.user_key == owner,
            CreditTransaction.transaction_type == transaction_type,
        ))).scalars().all()
        assert len(grants) == 1 and grants[0].amount == amount
        assert await session.scalar(select(UserCredits.credits).where(UserCredits.user_key == owner)) == amount


@pytest.mark.parametrize("first_book_trial,amount", [(False, 2), (True, 1)])
async def test_free_claim_and_balance_roll_back_together(creation_pg, monkeypatch, first_book_trial, amount):
    from src.services.credits import CreditsService
    monkeypatch.setattr(settings, "free_plan_first_book_trial", first_book_trial)
    maker, owner, _ = creation_pg
    async with maker() as session:
        result = await CreditsService().get_or_create_credits(session, owner, commit=False)
        assert result.credits == amount
        await session.rollback()
    async with maker() as session:
        assert await session.get(UserCredits, owner) is None
        assert (await session.execute(select(CreditTransaction.id).where(
            CreditTransaction.user_key == owner))).first() is None
