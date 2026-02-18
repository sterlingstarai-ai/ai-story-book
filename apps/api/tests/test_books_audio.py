from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class _FakeScalarResult:
    def __init__(self, page):
        self._page = page

    def scalar_one_or_none(self):
        return self._page


class _FakeDbSession:
    def __init__(self, pages):
        self._pages = list(pages)
        self._index = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, _query):
        page = self._pages[self._index]
        self._index += 1
        return _FakeScalarResult(page)

    async def commit(self):
        self.commit_calls += 1
        if self.commit_calls == 1:
            raise RuntimeError("commit failed")

    async def rollback(self):
        self.rollback_calls += 1


class _FakeSessionContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _session_local_factory(db):
    def _factory():
        return _FakeSessionContext(db)

    return _factory


@pytest.mark.asyncio
async def test_generate_audio_pages_rolls_back_and_continues_after_commit_failure():
    from src.routers.books import _generate_audio_pages

    page_one = SimpleNamespace(id="page-1", audio_url=None)
    page_two = SimpleNamespace(id="page-2", audio_url=None)
    fake_db = _FakeDbSession([page_one, page_two])

    pages = [
        {"page_number": 1, "text": "one", "page_id": "page-1"},
        {"page_number": 2, "text": "two", "page_id": "page-2"},
    ]
    synthesize_mock = AsyncMock(side_effect=[b"audio-1", b"audio-2"])
    upload_mock = AsyncMock(
        side_effect=[
            "https://cdn.example.com/audio-1.mp3",
            "https://cdn.example.com/audio-2.mp3",
        ]
    )

    with patch("src.core.database.AsyncSessionLocal", new=_session_local_factory(fake_db)):
        with patch("src.routers.books.tts_service.synthesize_page", new=synthesize_mock):
            with patch("src.routers.books.storage_service.upload_bytes", new=upload_mock):
                await _generate_audio_pages("book-123", pages)

    assert fake_db.commit_calls == 2
    assert fake_db.rollback_calls == 1
    assert synthesize_mock.await_count == 2
    assert upload_mock.await_count == 2
    assert page_two.audio_url == "https://cdn.example.com/audio-2.mp3"


@pytest.mark.asyncio
async def test_get_page_audio_rolls_back_when_commit_fails():
    from src.core.exceptions import InternalServerError
    from src.routers.books import get_page_audio

    book = SimpleNamespace(id="book-123", user_key="user-123")
    page = SimpleNamespace(id="page-1", text="hello", audio_url=None)
    fake_db = _FakeDbSession([book, page])

    synthesize_mock = AsyncMock(return_value=b"audio-1")
    upload_mock = AsyncMock(return_value="https://cdn.example.com/audio-1.mp3")

    with patch("src.routers.books.tts_service.synthesize_page", new=synthesize_mock):
        with patch("src.routers.books.storage_service.upload_bytes", new=upload_mock):
            with pytest.raises(InternalServerError):
                await get_page_audio("book-123", 1, db=fake_db, user_key="user-123")

    assert fake_db.commit_calls == 1
    assert fake_db.rollback_calls == 1
