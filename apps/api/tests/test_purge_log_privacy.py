"""Purge failures must remain retryable without leaking sensitive provider data."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services import purge_queue


@pytest.mark.asyncio
@pytest.mark.parametrize('raises', [False, True])
async def test_failed_purge_does_not_log_sensitive_object_or_exception(monkeypatch, raises):
    secret = 'fixture-private-object-and-secret'
    task = SimpleNamespace(id=42, target=secret, attempts=0, last_error=None,
                           updated_at=None, status='pending')
    session = SimpleNamespace(commit=AsyncMock())
    seen = []
    monkeypatch.setattr(purge_queue.logger, 'warning', lambda *args, **kwargs: seen.append((args, kwargs)))
    if raises:
        execute = AsyncMock(side_effect=RuntimeError(secret))
    else:
        execute = AsyncMock(return_value=[secret])
    monkeypatch.setattr(purge_queue, '_execute_task', execute)

    assert await purge_queue.run_purge_tasks(session, [task]) == [secret]
    assert task.status == 'pending' and task.attempts == 1
    assert secret not in repr(seen) and secret not in task.last_error
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_failure_does_not_persist_provider_exception(monkeypatch):
    secret = 'fixture-private-provider-credential'
    task = SimpleNamespace(id=1, target='fixture-key', attempts=1, last_error=None,
                           updated_at=None, status='pending')
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))
    session = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock())

    class Factory:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            return False

    import src.core.database as database
    monkeypatch.setattr(database, 'AsyncSessionLocal', Factory)
    monkeypatch.setattr(purge_queue, '_execute_task', AsyncMock(side_effect=RuntimeError(secret)))
    assert await purge_queue.sweep_pending_purges() == 0
    assert task.status == 'pending' and task.attempts == 2
    assert secret not in task.last_error
    session.commit.assert_awaited_once()
