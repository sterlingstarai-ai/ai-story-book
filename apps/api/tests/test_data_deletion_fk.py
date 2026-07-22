"""삭제/Erasure FK 정합성 회귀 테스트 (F8/N5/N6/N7).

SQLite FK 강제(conftest)가 켜진 상태에서 운영 Postgres와 동일한 FK 위반을 재현한다.
F8: 책-자식(공유/퀴즈/읽기로그/오늘의 동화) 누락 시 책/계정 삭제가 깨지는지.
N5: 계정 삭제가 voice-samples/{user_key}/ 를 파기하는지.
N6: 동의 철회가 likeness 책까지 파기하는지.
N7: 캐릭터 시트 이미지가 삭제 가능한 키 경로로 저장되는지.
"""

import uuid

import pytest
from sqlalchemy import select

from src.core.utils import utcnow
from src.models.db import (
    Book,
    BookShare,
    Character,
    DailyStory,
    Job,
    QuizAnswer,
    ReadingLog,
)

OWNER = "550e8400-e29b-41d4-a716-446655440000"
OWNER_HEADERS = {"X-User-Key": OWNER}


async def _make_book(db, user_key=OWNER, character_id=None) -> str:
    suffix = uuid.uuid4().hex[:8]
    job_id = f"job_{suffix}"
    book_id = f"book_{suffix}"
    db.add(Job(id=job_id, status="done", user_key=user_key))
    db.add(
        Book(
            id=book_id,
            job_id=job_id,
            title="테스트 책",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=user_key,
            character_id=character_id,
        )
    )
    await db.flush()
    return book_id


async def _attach_children(db, book_id: str, user_key=OWNER):
    """책을 참조하는 모든 자식 행을 1개씩 단다(FK 위반 트랩)."""
    db.add(BookShare(id=uuid.uuid4().hex, book_id=book_id, user_key=user_key))
    db.add(
        QuizAnswer(
            user_key=user_key, book_id=book_id, quiz_type="vocab", correct=True
        )
    )
    db.add(
        ReadingLog(
            user_key=user_key, book_id=book_id, read_date=utcnow(), reading_time=10
        )
    )
    db.add(
        DailyStory(date=utcnow(), theme="감정코칭", topic="우정", book_id=book_id)
    )
    await db.flush()


async def _book_count(db, book_id: str) -> int:
    return len(
        (await db.execute(select(Book.id).where(Book.id == book_id))).all()
    )


# ───────────────────── F8: 단건 책 삭제 ─────────────────────
@pytest.mark.asyncio
async def test_delete_book_with_children_succeeds_under_fk(client, db_session):
    book_id = await _make_book(db_session)
    await _attach_children(db_session, book_id)
    await db_session.commit()

    r = await client.delete(f"/v1/library/{book_id}", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert await _book_count(db_session, book_id) == 0
    assert (
        await db_session.execute(select(BookShare).where(BookShare.book_id == book_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(QuizAnswer).where(QuizAnswer.book_id == book_id))
    ).scalar_one_or_none() is None
    # DailyStory는 보존하되 book_id만 해제(NULL)
    ds = (
        await db_session.execute(select(DailyStory).where(DailyStory.topic == "우정"))
    ).scalar_one()
    assert ds.book_id is None


# ───────────────────── F8: 계정 전체 삭제 ─────────────────────
@pytest.mark.asyncio
async def test_account_deletion_with_shares_and_quiz_succeeds(client, db_session):
    book_id = await _make_book(db_session)
    await _attach_children(db_session, book_id)
    await db_session.commit()

    r = await client.delete("/v1/users/me", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert await _book_count(db_session, book_id) == 0
    assert (
        await db_session.execute(select(BookShare).where(BookShare.user_key == OWNER))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(QuizAnswer).where(QuizAnswer.user_key == OWNER))
    ).scalar_one_or_none() is None


# ───────────────────── N5: 음성 샘플 파기 ─────────────────────
@pytest.mark.asyncio
async def test_account_deletion_purges_voice_samples(client, db_session, monkeypatch):
    from src.services import storage as storage_module

    deleted_prefixes = []

    async def spy_delete_prefix(prefix):
        deleted_prefixes.append(prefix)
        return 0

    monkeypatch.setattr(
        storage_module.storage_service, "delete_prefix", spy_delete_prefix
    )

    r = await client.delete("/v1/users/me", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text
    assert f"voice-samples/{OWNER}/" in deleted_prefixes


# ───────────────────── N6: 동의 철회가 likeness 책 파기 ─────────────────────
@pytest.mark.asyncio
async def test_revoke_consent_deletes_likeness_books(client, db_session, monkeypatch):
    from src.services import storage as storage_module

    async def noop_delete_prefix(prefix):
        return 0

    async def noop_delete_book_files(book_id):
        return None

    monkeypatch.setattr(
        storage_module.storage_service, "delete_prefix", noop_delete_prefix
    )
    monkeypatch.setattr(storage_module, "delete_book_files", noop_delete_book_files)
    # consent 라우터가 import한 심볼도 교체
    import src.routers.consent as consent_module

    monkeypatch.setattr(consent_module, "delete_book_files", noop_delete_book_files)

    char_id = f"char_{uuid.uuid4().hex[:8]}"
    db_session.add(
        Character(
            id=char_id,
            name="아이",
            master_description="from photo child",
            appearance={},
            clothing={},
            personality_traits=[],
            user_key=OWNER,
            from_photo=True,
        )
    )
    await db_session.flush()
    book_id = await _make_book(db_session, character_id=char_id)
    db_session.add(BookShare(id=uuid.uuid4().hex, book_id=book_id, user_key=OWNER))
    await db_session.commit()

    r = await client.post("/v1/consent/revoke", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert await _book_count(db_session, book_id) == 0
    assert (
        await db_session.execute(select(Character).where(Character.id == char_id))
    ).scalar_one_or_none() is None


# ───────────────────── N7: 시트 이미지 키 경로 ─────────────────────
def test_sheet_image_key_is_under_character_prefix():
    from src.services.image import _make_image_key, image_storage_scope

    # 스코프 밖: 추적 불가 경로
    assert _make_image_key("openai", "png").startswith("images/openai/")

    # 스코프 안: 삭제 가능한 캐릭터 경로
    with image_storage_scope("characters/char_abc/sheets"):
        key = _make_image_key("openai", "png")
    assert key.startswith("characters/char_abc/sheets/")


# ==================== H7: series FK 미처리로 인한 erasure 500 ====================


async def _make_character(db, user_key=OWNER) -> str:
    from src.models.db import Character

    cid = f"char_{uuid.uuid4().hex[:8]}"
    db.add(
        Character(
            id=cid,
            name="토리",
            master_description="a white rabbit",
            appearance={"face": "round"},
            clothing={"top": "vest"},
            personality_traits=["brave"],
            user_key=user_key,
        )
    )
    await db.flush()
    return cid


async def _make_series(db, character_id, user_key=OWNER) -> str:
    from src.models.db import Series

    sid = f"series_{uuid.uuid4().hex[:8]}"
    db.add(
        Series(
            id=sid,
            title="시리즈",
            language="ko",
            target_age="5-7",
            style="watercolor",
            character_id=character_id,
            user_key=user_key,
        )
    )
    await db.flush()
    return sid


@pytest.mark.asyncio
async def test_account_deletion_with_series_succeeds(client, db_session):
    """H7: 시리즈 사용 이력이 있어도 계정 삭제가 200(FK 순서 위반 없음)."""
    from src.models.db import Series

    cid = await _make_character(db_session)
    sid = await _make_series(db_session, cid)
    book_id = await _make_book(db_session, character_id=cid)
    book = (await db_session.execute(select(Book).where(Book.id == book_id))).scalar_one()
    book.series_id = sid
    await db_session.commit()

    r = await client.delete("/v1/users/me", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert (await db_session.execute(select(Series).where(Series.user_key == OWNER))).scalars().all() == []
    assert (await db_session.execute(select(Book).where(Book.user_key == OWNER))).scalars().all() == []


@pytest.mark.asyncio
async def test_delete_character_with_series_nullifies_series(client, db_session):
    """H7: 시리즈를 만든 캐릭터 삭제가 200 + series.character_id null화."""
    from src.models.db import Character, Series

    cid = await _make_character(db_session)
    sid = await _make_series(db_session, cid)
    await db_session.commit()

    r = await client.delete(f"/v1/characters/{cid}", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    series = (await db_session.execute(select(Series).where(Series.id == sid))).scalar_one()
    assert series.character_id is None
    assert (await db_session.execute(select(Character).where(Character.id == cid))).scalar_one_or_none() is None


# ==================== H8: 스토리지 파기 실패 표면화(status partial) ====================


@pytest.mark.asyncio
async def test_delete_book_files_returns_failed_keys(monkeypatch):
    """H8: delete_objects의 per-key Errors를 삼키지 않고 실패키로 반환."""
    from src.services import storage as storage_module

    class _FakeS3:
        def list_objects_v2(self, **kw):
            return {"Contents": [{"Key": "books/x/cover.png"}], "IsTruncated": False}

        def delete_objects(self, **kw):
            return {"Errors": [{"Key": "books/x/cover.png", "Code": "AccessDenied"}]}

    monkeypatch.setattr(storage_module, "get_s3_client", lambda: _FakeS3())
    failed = await storage_module.delete_book_files("x")
    assert failed == ["books/x/cover.png"]


@pytest.mark.asyncio
async def test_account_deletion_reports_storage_failure_as_partial(
    client, db_session, monkeypatch
):
    """H8: 스토리지 파기 실패 시 응답 status='partial' + storage_delete_failures>0."""
    from src.services import storage as storage_module

    async def failing_delete_prefix(prefix):
        return [f"{prefix}orphan.png"]  # 실패키 표면화

    monkeypatch.setattr(
        storage_module.storage_service, "delete_prefix", failing_delete_prefix
    )

    r = await client.delete("/v1/users/me", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "partial"
    assert body["storage_delete_failures"] > 0


# ==================== N1: 파이프라인 이미지 삭제 추적성 ====================


@pytest.mark.asyncio
async def test_collect_book_image_keys_derives_from_url(db_session):
    """N1: 표지·페이지 image_url(추적 불가 prefix 포함)에서 S3 키를 역산."""
    from src.core.config import settings
    from src.models.db import Page
    from src.services.data_deletion import collect_book_image_keys

    base = settings.s3_public_url.rstrip("/")
    book_id = await _make_book(db_session)
    book = (await db_session.execute(select(Book).where(Book.id == book_id))).scalar_one()
    book.cover_image_url = f"{base}/images/replicate/cover-xyz.png"
    db_session.add(Page(book_id=book_id, page_number=1, text="p1",
                        image_url=f"{base}/images/fal/page1-abc.png"))
    await db_session.commit()

    keys = await collect_book_image_keys(db_session, [book_id])
    assert "images/replicate/cover-xyz.png" in keys
    assert "images/fal/page1-abc.png" in keys


@pytest.mark.asyncio
async def test_account_deletion_purges_pipeline_image_keys(client, db_session, monkeypatch):
    """N1: 계정 삭제가 books/{id}/ prefix 밖 파이프라인 이미지 키를 실제로 파기한다."""
    from src.core.config import settings
    from src.models.db import Page
    from src.routers import users as users_module

    base = settings.s3_public_url.rstrip("/")
    book_id = await _make_book(db_session)
    book = (await db_session.execute(select(Book).where(Book.id == book_id))).scalar_one()
    book.cover_image_url = f"{base}/images/replicate/cover-n1.png"
    db_session.add(Page(book_id=book_id, page_number=1, text="p1",
                        image_url=f"{base}/images/fal/page1-n1.png"))
    await db_session.commit()

    deleted = {}

    async def spy_delete_keys(keys):
        deleted["keys"] = list(keys)
        return []

    monkeypatch.setattr(users_module, "delete_keys", spy_delete_keys)

    r = await client.delete("/v1/users/me", headers=OWNER_HEADERS)
    assert r.status_code == 200, r.text
    assert "images/replicate/cover-n1.png" in deleted.get("keys", [])
    assert "images/fal/page1-n1.png" in deleted.get("keys", [])
