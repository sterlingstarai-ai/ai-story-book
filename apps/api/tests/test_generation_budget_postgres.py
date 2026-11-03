"""Durable admission semantics, with no external providers or credentials."""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy import text

from src.core import cost_budget as budget
from src.core.exceptions import APIError
from tests.conftest import TestSessionLocal


@pytest.fixture
def durable(monkeypatch):
    monkeypatch.setattr(budget, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(budget.settings, "generation_budget_store", "postgres")
    monkeypatch.setattr(budget.settings, "daily_generation_budget", 3)
    monkeypatch.setattr(budget, "utcnow", lambda: datetime(2026, 11, 3, 0, 0))


async def activate(day):
    async with TestSessionLocal.begin() as db:
        await db.execute(text("INSERT INTO generation_budget_activation VALUES (1, :day, :day, 0)"), {"day": day})


@pytest.mark.asyncio
async def test_uninitialized_and_database_failure_fail_closed(db_session, durable, monkeypatch):
    assert (await budget.generation_budget_snapshot())["status"] == "unavailable"
    with pytest.raises(APIError) as err:
        await budget.consume_daily_generation_budget()
    assert err.value.status_code == 503
    def unavailable():
        raise OSError("unavailable")
    monkeypatch.setattr(budget, "AsyncSessionLocal", unavailable)
    with pytest.raises(APIError) as err:
        await budget.consume_daily_generation_budget()
    assert err.value.status_code == 503


@pytest.mark.asyncio
async def test_cutover_day_is_blocked_even_if_limit_increases(db_session, durable, monkeypatch):
    await activate("20261103")
    assert (await budget.generation_budget_snapshot())["status"] == "exhausted"
    monkeypatch.setattr(budget.settings, "daily_generation_budget", 3000)
    assert await budget.consume_daily_generation_budget() == (False, 3000)


@pytest.mark.asyncio
async def test_concurrent_admissions_are_durable_and_roll_over(db_session, durable, monkeypatch):
    await activate("20261102")
    results = await asyncio.gather(*(budget.consume_daily_generation_budget() for _ in range(12)))
    assert sum(allowed for allowed, _ in results) == 3
    assert (await budget.generation_budget_snapshot())["used"] == 3
    assert await budget.consume_daily_generation_budget() == (False, 4)
    monkeypatch.setattr(budget, "utcnow", lambda: datetime(2026, 11, 3, 15, 0))
    assert await budget.consume_daily_generation_budget() == (True, 1)


@pytest.mark.asyncio
async def test_bad_activation_date_fails_closed(db_session, durable):
    await activate("bad-date")
    with pytest.raises(APIError) as err:
        await budget.consume_daily_generation_budget()
    assert err.value.status_code == 503


@pytest.mark.asyncio
async def test_clock_regression_or_deleted_control_fails_closed(db_session, durable, monkeypatch):
    await activate("20261102")
    assert await budget.consume_daily_generation_budget() == (True, 1)
    monkeypatch.setattr(budget, "utcnow", lambda: datetime(2026, 11, 2, 0, 0))
    assert (await budget.consume_daily_generation_budget())[0] is False
    async with TestSessionLocal.begin() as db:
        await db.execute(text("DELETE FROM generation_budget_activation"))
    with pytest.raises(APIError) as err:
        await budget.consume_daily_generation_budget()
    assert err.value.status_code == 503
