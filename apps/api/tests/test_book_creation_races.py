"""Concurrent HTTP retries must resolve one real credit transaction and job."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from src.core.config import settings
from src.core.database import get_db
from src.main import app
from src.models.db import CreditTransaction, Job, UserCredits
from src.routers import books
from src.services.credits import credits_service
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
@pytest.mark.parametrize("credits", [1, 3])
async def test_simultaneous_http_retries_return_one_job(
    db_session, headers, valid_book_spec, monkeypatch, credits,
):
    owner = headers["X-User-Key"]
    db_session.add(UserCredits(user_key=owner, credits=credits))
    await db_session.commit()
    monkeypatch.setattr(settings, "daily_generation_budget", 0)
    dispatch = AsyncMock()
    monkeypatch.setattr(books, "schedule_book_generation", dispatch)
    # Force all requests past their first lookup before any job is inserted.
    barrier = asyncio.Barrier(4)
    validate = books.enforce_book_spec_access

    async def synchronized_validation(*args, **kwargs):
        result = await validate(*args, **kwargs)
        await asyncio.wait_for(barrier.wait(), 5)
        return result

    monkeypatch.setattr(books, "enforce_book_spec_access", synchronized_validation)

    async def request_session():
        async with TestSessionLocal() as session:
            yield session

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = request_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            responses = await asyncio.gather(*[
                http.post("/v1/books", json=valid_book_spec,
                          headers={**headers, "X-Idempotency-Key": "concurrent-attempt"})
                for _ in range(4)
            ])
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
    assert [r.status_code for r in responses] == [200] * 4
    assert len({r.json()["job_id"] for r in responses}) == 1
    assert await db_session.scalar(select(func.count(Job.id))) == 1
    assert await db_session.scalar(select(UserCredits.credits)) == credits - 1
    assert await db_session.scalar(select(func.count(CreditTransaction.id)).where(
        CreditTransaction.transaction_type == "usage",
    )) == 1
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_unique_constraint_race_recovers_only_same_owner_key(db_session, monkeypatch):
    owner = "race-owner"
    db_session.add_all([
        UserCredits(user_key=owner, credits=3),
        Job(id="job_winner", user_key=owner, status="done", idempotency_key="same-key"),
    ])
    await db_session.commit()
    real_lookup = books._existing_creation_response
    calls = 0

    async def miss_until_insert(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return None
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(books, "_existing_creation_response", miss_until_insert)
    response = await books._create_job_with_credit(
        db=db_session, user_key=owner, job_id="job_loser", current_step="queued",
        credit_description="test", idempotency_key="same-key",
    )
    assert response.job_id == "job_winner"
    assert await db_session.scalar(select(UserCredits.credits)) == 3
    assert await db_session.get(Job, "job_loser") is None
    assert await db_session.scalar(select(func.count(CreditTransaction.id)).where(
        CreditTransaction.transaction_type == "usage")) == 0


@pytest.mark.asyncio
async def test_last_credit_retry_recovers_winner_before_reporting_insufficient(db_session, monkeypatch):
    db_session.add_all([
        UserCredits(user_key="last-credit-owner", credits=0),
        Job(id="job_last_credit", user_key="last-credit-owner", status="queued", idempotency_key="last-key"),
    ])
    await db_session.commit()
    lookup = books._existing_creation_response
    calls = 0

    async def first_lookup_misses(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await lookup(*args, **kwargs)

    monkeypatch.setattr(books, "_existing_creation_response", first_lookup_misses)
    debit = AsyncMock()
    monkeypatch.setattr(credits_service, "use_credit", debit)
    response = await books._create_job_with_credit(
        db=db_session, user_key="last-credit-owner", job_id="job_retry",
        current_step="queued", credit_description="test", idempotency_key="last-key",
    )
    assert response.job_id == "job_last_credit"
    debit.assert_not_awaited()
