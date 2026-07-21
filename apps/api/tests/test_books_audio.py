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


# ---- H3: 오디오 언어 5종(ja/zh/es 한국어 보이스 오합성 제거) ----


class _FakeDbSessionOK:
    """commit이 실패하지 않는 세션(H3 정상 경로 테스트용)."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._index = 0
        self.commit_calls = 0

    async def execute(self, _query):
        row = self._rows[self._index]
        self._index += 1
        return _FakeScalarResult(row)

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_ja_book_audio_uses_ja_voice_not_ko():
    """H3: ja 책은 ja 보이스로 합성되고 기본 슬롯(audio_url)에 저장된다(ko 오합성 제거)."""
    from src.routers.books import _generate_audio_pages

    page = SimpleNamespace(
        id="p1", audio_url=None, audio_url_ko=None, audio_url_en=None
    )
    fake_db = _FakeDbSessionOK([page])
    pages = [{"page_number": 1, "text": "ねこがいます", "page_id": "p1"}]

    synth = AsyncMock(return_value=b"ja-audio")
    upload = AsyncMock(return_value="https://cdn.example.com/ja.mp3")

    with patch("src.core.database.AsyncSessionLocal", new=_session_local_factory(fake_db)):
        with patch("src.routers.books.tts_service.synthesize_page", new=synth):
            with patch("src.routers.books.storage_service.upload_bytes", new=upload):
                await _generate_audio_pages("book-ja", pages, default_language="ja")

    assert synth.await_count == 1
    assert synth.call_args.kwargs["language"] == "ja"
    # ja 오디오는 기본 슬롯에만, ko 슬롯은 오염되지 않는다(MA5).
    assert page.audio_url == "https://cdn.example.com/ja.mp3"
    assert page.audio_url_ko is None


@pytest.mark.asyncio
async def test_get_page_audio_ja_uses_base_slot_and_ja_voice():
    """H3: GET audio?language=ja가 422가 아니라 ja 보이스로 합성·기본 슬롯 저장."""
    from src.routers.books import get_page_audio

    book = SimpleNamespace(
        id="b1", user_key="u1", language="ja", target_age="3-5"
    )
    page = SimpleNamespace(
        id="p1", text="ねこ", audio_url=None, audio_url_ko=None, audio_url_en=None
    )
    fake_db = _FakeDbSessionOK([book, page])

    synth = AsyncMock(return_value=b"aud")
    upload = AsyncMock(return_value="https://cdn.example.com/ja1.mp3")

    with patch("src.routers.books.tts_service.synthesize_page", new=synth):
        with patch("src.routers.books.storage_service.upload_bytes", new=upload):
            result = await get_page_audio(
                "b1", 1, language="ja", db=fake_db, user_key="u1", profile_id=None
            )

    assert result["audio_url"] == "https://cdn.example.com/ja1.mp3"
    assert synth.call_args.kwargs["language"] == "ja"
    assert page.audio_url == "https://cdn.example.com/ja1.mp3"


@pytest.mark.asyncio
async def test_get_page_audio_rejects_unsupported_language():
    """H3: 매핑 밖 언어는 조용한 ko 폴백 대신 ValidationError(fail-open 제거)."""
    from src.core.exceptions import ValidationError
    from src.routers.books import get_page_audio

    book = SimpleNamespace(id="b1", user_key="u1", language="ko", target_age="3-5")
    page = SimpleNamespace(id="p1", text="hi", audio_url=None)
    fake_db = _FakeDbSessionOK([book, page])

    with pytest.raises(ValidationError):
        await get_page_audio(
            "b1", 1, language="fr", db=fake_db, user_key="u1", profile_id=None
        )
