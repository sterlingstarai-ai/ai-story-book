"""A partial or malformed storage listing must never report successful erasure."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services import storage


@pytest.fixture
def fake_storage(monkeypatch):
    client = SimpleNamespace(list_objects_v2=object(), delete_objects=object())
    monkeypatch.setattr(storage, 'get_s3_client', lambda: client)
    return client


@pytest.mark.asyncio
async def test_truncated_listing_without_next_token_is_incomplete(fake_storage, monkeypatch):
    call = AsyncMock(side_effect=[
        {'Contents': [{'Key': 'test/a'}], 'IsTruncated': True},
        {'Deleted': [{'Key': 'test/a'}]},
    ])
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == ['test/*']


@pytest.mark.asyncio
async def test_repeated_pagination_token_is_incomplete_without_unbounded_loop(fake_storage, monkeypatch):
    call = AsyncMock(side_effect=[
        {'Contents': [], 'IsTruncated': True, 'NextContinuationToken': 'same'},
        {'Contents': [], 'IsTruncated': True, 'NextContinuationToken': 'same'},
    ])
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == ['test/*']
    assert call.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    None, {}, {'Errors': None}, {'Errors': [{}]},
    {'Errors': [{'Key': 'other'}]},
    {'Deleted': [{'Key': 'test/a'}]},
    {'Deleted': [{'Key': 'test/a'}, {'Key': 'test/b'}],
     'Errors': [{'Key': 'test/a'}]},
])
async def test_ambiguous_key_delete_response_keeps_task_retryable(fake_storage, monkeypatch, response):
    monkeypatch.setattr(storage, '_call_s3', AsyncMock(return_value=response))
    assert await storage.delete_keys(['test/a', 'test/b']) == ['test/a', 'test/b']


@pytest.mark.asyncio
async def test_complete_mixed_delete_response_returns_only_failed_key(fake_storage, monkeypatch):
    monkeypatch.setattr(storage, '_call_s3', AsyncMock(return_value={
        'Deleted': [{'Key': 'test/a'}], 'Errors': [{'Key': 'test/b'}],
    }))
    assert await storage.delete_keys(['test/a', 'test/b']) == ['test/b']


@pytest.mark.asyncio
async def test_listed_object_outside_prefix_cannot_be_deleted(fake_storage, monkeypatch):
    call = AsyncMock(return_value={'Contents': [{'Key': 'other/a'}]})
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == ['test/*']
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_valid_empty_prefix_is_complete(fake_storage, monkeypatch):
    call = AsyncMock(return_value={'IsTruncated': False})
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == []
    assert call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    {}, {'Contents': []}, {'IsTruncated': None}, {'IsTruncated': 0},
    {'IsTruncated': 'false'}, {'IsTruncated': True, 'NextContinuationToken': ''},
])
async def test_unknown_listing_completion_keeps_purge_pending(fake_storage, monkeypatch, response):
    from src.services.purge_queue import KIND_PREFIX, run_purge_tasks

    monkeypatch.setattr(storage, '_call_s3', AsyncMock(return_value=response))
    task = SimpleNamespace(kind=KIND_PREFIX, target='test/', status='pending', attempts=0,
                           updated_at=None, last_error=None, id='synthetic')
    db = SimpleNamespace(commit=AsyncMock())
    assert await run_purge_tasks(db, [task]) == ['test/*']
    assert task.status == 'pending'
    assert task.attempts == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_deletion_is_confirmed_with_fresh_empty_listing(fake_storage, monkeypatch):
    call = AsyncMock(side_effect=[
        {'Contents': [{'Key': 'test/a'}], 'IsTruncated': False},
        {'Deleted': [{'Key': 'test/a'}]},
        {'IsTruncated': False},
    ])
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == []
    assert call.await_args_list[-1].kwargs['MaxKeys'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('remaining', [
    {'IsTruncated': False, 'Contents': [{'Key': 'test/skipped'}]},
    {'Contents': []},
    {'IsTruncated': True, 'NextContinuationToken': 'next'},
])
async def test_unverified_post_delete_listing_is_incomplete(fake_storage, monkeypatch, remaining):
    call = AsyncMock(side_effect=[
        {'Contents': [{'Key': 'test/a'}], 'IsTruncated': False},
        {'Deleted': [{'Key': 'test/a'}]}, remaining,
    ])
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == ['test/*']


@pytest.mark.asyncio
async def test_purge_listing_has_bounded_pages(fake_storage, monkeypatch):
    monkeypatch.setattr(storage, '_MAX_PURGE_LIST_PAGES', 2)
    call = AsyncMock(side_effect=[
        {'IsTruncated': True, 'NextContinuationToken': 'one'},
        {'IsTruncated': True, 'NextContinuationToken': 'two'},
    ])
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == ['test/*']
    assert call.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'KeyCount': 1}, {'KeyCount': True}, {'KeyCount': -1},
    {'CommonPrefixes': [{'Prefix': 'test/hidden/'}]}, {'CommonPrefixes': None},
    {'Prefix': 'wrong/'}, {'Name': 'wrong-bucket'},
    {'Contents': [{'Key': 'test/a'}, {'Key': 'test/a'}]},
])
async def test_contradictory_metadata_does_not_complete_purge(fake_storage, monkeypatch, changes):
    from src.services.purge_queue import KIND_PREFIX, run_purge_tasks

    call = AsyncMock(return_value={'IsTruncated': False, **changes})
    monkeypatch.setattr(storage, '_call_s3', call)
    task = SimpleNamespace(kind=KIND_PREFIX, target='test/', status='pending', attempts=0,
                           updated_at=None, last_error=None, id='synthetic')
    db = SimpleNamespace(commit=AsyncMock())
    assert await run_purge_tasks(db, [task]) == ['test/*']
    assert task.status == 'pending'
    assert call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'KeyCount': 1}, {'KeyCount': True},
    {'CommonPrefixes': [{'Prefix': 'test/hidden/'}]},
    {'Prefix': 'wrong/'}, {'Name': 'wrong-bucket'},
])
async def test_contradictory_post_delete_check_stays_pending(fake_storage, monkeypatch, changes):
    call = AsyncMock(side_effect=[
        {'Contents': [{'Key': 'test/a'}], 'IsTruncated': False},
        {'Deleted': [{'Key': 'test/a'}]},
        {'IsTruncated': False, **changes},
    ])
    monkeypatch.setattr(storage, '_call_s3', call)
    assert await storage._delete_prefix_keys('test/') == ['test/*']
