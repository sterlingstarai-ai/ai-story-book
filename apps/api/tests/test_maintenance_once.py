"""One-shot maintenance invokes all existing durable recovery routines."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.ops.maintenance_once import run_once


def test_cli_returns_failure_when_recovery_remains(monkeypatch, capsys):
    from src.ops import maintenance_once

    monkeypatch.setattr(maintenance_once, "run_once", AsyncMock(return_value={
        "jobs_and_refunds": "ok", "recovery_debt": "failed",
    }))
    assert maintenance_once.main() == 1
    assert '"recovery_debt": "failed"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_failure_does_not_prevent_other_routines_or_log_the_error(monkeypatch):
    from src.ops import maintenance_once
    from src.services import character_avatar, job_monitor, periodic_credits, purge_queue

    calls = []

    async def failed():
        calls.append("jobs")
        raise RuntimeError("synthetic-private-value")

    async def avatar():
        calls.append("avatar")

    async def purge():
        calls.append("purge")

    async def refill(_session):
        calls.append("refill")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    from src.core import database
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    monkeypatch.setattr(job_monitor.job_monitor, "check_and_recover_jobs", failed)
    monkeypatch.setattr(character_avatar, "sweep_character_avatars", avatar)
    monkeypatch.setattr(purge_queue, "sweep_pending_purges", purge)
    monkeypatch.setattr(periodic_credits.periodic_credits, "grant_due_refills", refill)
    monkeypatch.setattr(maintenance_once, "_check_recovery_debt", AsyncMock())
    with patch.object(maintenance_once.logger, "error") as error:
        result = await run_once()
    assert calls == ["jobs", "avatar", "purge", "refill"]
    assert result == {"jobs_and_refunds": "failed", "character_avatars": "ok",
                      "storage_purges": "ok", "periodic_credits": "ok", "recovery_debt": "ok"}
    assert "synthetic-private-value" not in str(error.call_args_list)


@pytest.mark.asyncio
async def test_one_shot_retries_purge_and_refunds_failed_job_once(db_session, monkeypatch):
    from src.core import database
    from src.models.db import CreditTransaction, Job, StoragePurgeTask, UserCredits
    from src.services import character_avatar, job_monitor, purge_queue
    from src.services.credits import credits_service

    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(job_monitor, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(character_avatar, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(purge_queue, "_execute_task", AsyncMock(side_effect=[["synthetic-object"], []]))
    user = "synthetic-owner"
    await credits_service.get_or_create_credits(db_session, user)
    db_session.add(Job(id="synthetic-failed-job", user_key=user, status="failed"))
    db_session.add(StoragePurgeTask(user_key=None, reason="consent_revoke", kind="keys",
                                   target='["synthetic-object"]', status="pending", attempts=1))
    await db_session.commit()
    await credits_service.use_credit(db_session, user, reference_id="synthetic-failed-job")
    await db_session.rollback()

    first, second = await run_once(), await run_once()
    assert first["recovery_debt"] == "failed"
    assert all(value == "ok" for key, value in first.items() if key != "recovery_debt")
    assert all(value == "ok" for value in second.values())
    db_session.expire_all()
    assert (await db_session.get(UserCredits, user)).credits == 2
    assert await db_session.scalar(select(func.count(CreditTransaction.id)).where(
        CreditTransaction.transaction_type == "refund")) == 1
    purge = (await db_session.execute(select(StoragePurgeTask))).scalar_one()
    assert (purge.status, purge.attempts) == ("done", 3)


@pytest.mark.asyncio
async def test_suppressed_refund_failure_is_reported_and_recovered(db_session, monkeypatch):
    from src.core import database
    from src.models.db import CreditTransaction, Job, UserCredits
    from src.services import character_avatar, job_monitor
    from src.services.credits import credits_service

    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(job_monitor, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(character_avatar, "AsyncSessionLocal", sessions)
    user = "synthetic-owner"
    await credits_service.get_or_create_credits(db_session, user)
    db_session.add(Job(id="synthetic-refund-job", user_key=user, status="failed"))
    await db_session.commit()
    await credits_service.use_credit(db_session, user, reference_id="synthetic-refund-job")
    await db_session.rollback()
    with monkeypatch.context() as temporary:
        temporary.setattr(credits_service, "refund_for_job",
                          AsyncMock(side_effect=RuntimeError("synthetic-error")))
        first = await run_once()
    assert first["jobs_and_refunds"] == "ok"  # the existing sweeper catches individual failures
    assert first["recovery_debt"] == "failed"
    second = await run_once()
    assert all(value == "ok" for value in second.values())
    db_session.expire_all()
    assert (await db_session.get(UserCredits, user)).credits == 2
    assert await db_session.scalar(select(func.count(CreditTransaction.id)).where(
        CreditTransaction.transaction_type == "refund")) == 1


@pytest.mark.asyncio
async def test_unresolved_due_refill_is_reported(db_session, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import update

    from src.core import database
    from src.models.db import Subscription
    from src.services import character_avatar, job_monitor, periodic_credits
    from src.services.credits import credits_service

    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(job_monitor, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(character_avatar, "AsyncSessionLocal", sessions)
    sub = await credits_service.create_subscription(db_session, "synthetic-owner", "basic")
    await db_session.execute(update(Subscription).where(Subscription.id == sub.id).values(
        current_period_end=periodic_credits._db_utcnow() - timedelta(days=1)))
    await db_session.commit()
    monkeypatch.setattr(periodic_credits.periodic_credits, "grant_due_refills", AsyncMock(return_value=0))
    result = await run_once()
    assert result["periodic_credits"] == "ok"
    assert result["recovery_debt"] == "failed"
