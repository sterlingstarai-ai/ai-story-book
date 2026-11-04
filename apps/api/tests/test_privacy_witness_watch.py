from contextlib import asynccontextmanager

import pytest

from src.services import privacy_witness_watch as watch


@pytest.mark.asyncio
async def test_snapshot_watch_alerts_when_new_source_event_is_unanchored(monkeypatch):
    @asynccontextmanager
    async def fence(db, journal, *, legacy_source=False, freeze_tables=False):
        yield {'event_count': 2}, object()

    monkeypatch.setattr(watch, 'hold_consistent_source', fence)
    monkeypatch.setattr(watch, 'verify_anchored_checkpoint', lambda *args, **kwargs:
        {'checkpoint_count': 1, 'journal_count': 2, 'restore_authorized': False})
    result = await watch.assess_witness(object(), object(), object(), object(), namespace='a' * 32,
        head_key=b'h' * 32, checkpoint_key=b'c' * 32, trusted_head={'sequence': 1, 'sha256': 'a' * 64},
        now=100, max_age=10)
    assert result == {'status': 'ALERT', 'restore_authorized': False}


@pytest.mark.asyncio
async def test_snapshot_watch_never_releases_restoration_and_fails_closed(monkeypatch):
    @asynccontextmanager
    async def fence(db, journal, *, legacy_source=False, freeze_tables=False):
        yield {'event_count': 2}, object()

    monkeypatch.setattr(watch, 'hold_consistent_source', fence)
    monkeypatch.setattr(watch, 'verify_anchored_checkpoint', lambda *args, **kwargs:
        {'checkpoint_count': 2, 'journal_count': 2, 'restore_authorized': False})
    args = {'namespace': 'a' * 32, 'head_key': b'h' * 32, 'checkpoint_key': b'c' * 32,
            'trusted_head': {'sequence': 1, 'sha256': 'a' * 64}, 'now': 100, 'max_age': 10}
    result = await watch.assess_witness(object(), object(), object(), object(), **args)
    assert result == {'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}
    fence_calls = []

    @asynccontextmanager
    async def must_not_lock(db, journal, *, legacy_source=False, freeze_tables=False):
        fence_calls.append(True)
        yield {'event_count': 2}, object()

    monkeypatch.setattr(watch, 'hold_consistent_source', must_not_lock)
    assert (await watch.assess_witness(object(), object(), object(), object(),
        **{**args, 'trusted_head': None}))['status'] == 'ALERT'
    assert not fence_calls
    assert (await watch.assess_witness(object(), object(), object(), object(),
        **{**args, 'trusted_head': None, 'head_key': args['checkpoint_key']}))['status'] == 'ALERT'

    def failed(*args, **kwargs):
        raise RuntimeError('sensitive provider detail')

    monkeypatch.setattr(watch, 'verify_anchored_checkpoint', failed)
    assert await watch.assess_witness(object(), object(), object(), object(), **args) == {
        'status': 'ALERT', 'restore_authorized': False}
