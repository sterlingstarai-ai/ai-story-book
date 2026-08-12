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
    from src.services.job_runners import generate_audio_pages

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
        with patch("src.services.job_runners.tts_service.synthesize_page", new=synthesize_mock):
            with patch("src.services.job_runners.storage_service.upload_bytes", new=upload_mock):
                await generate_audio_pages("book-123", pages)

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

    with patch("src.services.job_runners.tts_service.synthesize_page", new=synthesize_mock):
        with patch("src.services.job_runners.storage_service.upload_bytes", new=upload_mock):
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
    from src.services.job_runners import generate_audio_pages

    page = SimpleNamespace(
        id="p1", audio_url=None, audio_url_ko=None, audio_url_en=None
    )
    fake_db = _FakeDbSessionOK([page])
    pages = [{"page_number": 1, "text": "ねこがいます", "page_id": "p1"}]

    synth = AsyncMock(return_value=b"ja-audio")
    upload = AsyncMock(return_value="https://cdn.example.com/ja.mp3")

    with patch("src.core.database.AsyncSessionLocal", new=_session_local_factory(fake_db)):
        with patch("src.services.job_runners.tts_service.synthesize_page", new=synth):
            with patch("src.services.job_runners.storage_service.upload_bytes", new=upload):
                await generate_audio_pages("book-ja", pages, default_language="ja")

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

    with patch("src.services.job_runners.tts_service.synthesize_page", new=synth):
        with patch("src.services.job_runners.storage_service.upload_bytes", new=upload):
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


# ---- L5: 배치 오디오 실패/완료가 audio_ Job 상태로 표면화 ----


@pytest.mark.asyncio
async def test_batch_audio_marks_job_failed_on_total_failure():
    """모든 페이지 오디오가 실패하면 audio_ Job이 failed(AUDIO_FAILED)로 전이."""
    from src.services import job_runners as books

    captured = {}

    async def fake_set_status(job_id, *, status, **kw):
        captured["job_id"] = job_id
        captured["status"] = status
        captured["error_code"] = kw.get("error_code")

    async def all_fail(**_kw):
        return (0, [1, 2, 3])  # succeeded=0, 전부 실패

    with patch.object(books, "set_regen_job_status", new=fake_set_status), patch.object(
        books, "generate_audio_pages", new=all_fail
    ):
        await books.run_audio_job("book-1", [], "5-7", "ko", "audio_job_1")

    assert captured["status"] == "failed"
    assert captured["error_code"] == "AUDIO_FAILED"
    assert captured["job_id"] == "audio_job_1"


@pytest.mark.asyncio
async def test_batch_audio_marks_job_done_on_success():
    """일부라도 성공하면 audio_ Job이 done으로 전이(부분 실패는 step에 기록)."""
    from src.services import job_runners as books

    captured = {}

    async def fake_set_status(job_id, *, status, **kw):
        captured["status"] = status
        captured["step"] = kw.get("current_step")

    async def partial_ok(**_kw):
        return (2, [3])  # 2 성공, 1 실패

    with patch.object(books, "set_regen_job_status", new=fake_set_status), patch.object(
        books, "generate_audio_pages", new=partial_ok
    ):
        await books.run_audio_job("book-1", [], "5-7", "ko", "audio_job_2")

    assert captured["status"] == "done"
    assert "실패 페이지" in captured["step"]


@pytest.mark.asyncio
async def test_batch_audio_marks_job_failed_on_timeout():
    """타임아웃이면 audio_ Job이 failed(AUDIO_TIMEOUT)로 전이."""
    import asyncio

    from src.services import job_runners as books

    captured = {}

    async def fake_set_status(job_id, *, status, **kw):
        captured["status"] = status
        captured["error_code"] = kw.get("error_code")

    async def timeout_pages(**_kw):
        raise asyncio.TimeoutError()

    with patch.object(books, "set_regen_job_status", new=fake_set_status), patch.object(
        books, "generate_audio_pages", new=timeout_pages
    ):
        await books.run_audio_job("book-1", [], "5-7", "ko", "audio_job_3")

    assert captured["status"] == "failed"
    assert captured["error_code"] == "AUDIO_TIMEOUT"


@pytest.mark.asyncio
async def test_batch_audio_returns_pollable_job_id():
    """POST /audio가 폴링 가능한 audio_ job_id를 반환한다."""
    from fastapi import BackgroundTasks

    from src.routers import books

    book = SimpleNamespace(
        id="book-1", user_key="user-1", target_age="5-7", language="ko"
    )
    page = SimpleNamespace(
        id="page-1", page_number=1, text="hi", text_ko="안녕", text_en="hi"
    )

    class _OkSession:
        def __init__(self):
            self._results = [
                _FakeScalarResult(book),  # select(Book)
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [page])),  # pages
            ]
            self._i = 0
            self.added = []

        async def execute(self, _q):
            r = self._results[self._i]
            self._i += 1
            return r

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

        async def rollback(self):
            pass

    fake_db = _OkSession()

    async def _noop_enforce(*_a, **_k):
        return None

    with patch.object(books, "_enforce_free_plan_feature_access", new=_noop_enforce), patch.object(
        books, "_assert_book_profile_scope", new=lambda *a, **k: None
    ):
        result = await books.generate_book_audio(
            "book-1",
            BackgroundTasks(),
            db=fake_db,
            user_key="user-1",
            profile_id=None,
        )

    assert result["status"] == "processing"
    assert result["job_id"].startswith("audio_")
    # audio_ Job 행이 생성됨(폴링 대상).
    assert any(getattr(o, "id", "").startswith("audio_") for o in fake_db.added)
