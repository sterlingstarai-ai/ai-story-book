"""Source fences remain evidence only and never authorize a restore."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services import privacy_restore_source_guard as guard


def fake_session(dialect='postgresql', active=False):
    @asynccontextmanager
    async def transaction():
        yield
    return SimpleNamespace(in_transaction=lambda: active,
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect)),
        begin=transaction, execute=AsyncMock())


@pytest.mark.asyncio
async def test_rejects_non_postgres_or_existing_transaction():
    for db in (fake_session('sqlite'), fake_session(active=True)):
        with pytest.raises(guard.SourceGuardError):
            async with guard.hold_consistent_source(db, Mock()):
                pass
        db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_changed_source_or_journal_fails_closed(monkeypatch):
    db = fake_session()
    journal = SimpleNamespace(scan=Mock(return_value=object()))
    first = {'event_count': 1, 'journal_sha256': 'a' * 64, 'restore_authorized': False}
    changed = dict(first, journal_sha256='b' * 64)
    monkeypatch.setattr(guard, 'verify_current_outbox', AsyncMock(side_effect=[first, changed]))
    with pytest.raises(guard.SourceGuardError, match='changed'):
        async with guard.hold_consistent_source(db, journal) as (checkpoint, _scan):
            assert checkpoint == first
    assert journal.scan.call_count == 2
