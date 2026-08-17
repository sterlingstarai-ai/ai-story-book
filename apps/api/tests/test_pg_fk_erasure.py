"""실 PostgreSQL FK 게이트 — 아동 PII 파기 경로 (R1) + clawback 멱등 (R2-2).

**이 파일이 왜 별도로 존재하는가.**
`data_deletion.py` 독스트링이 명시하듯, 아동 PII·FK·파기 경로는 SQLite 테스트가
구조적으로 못 잡는 클래스다. conftest가 `PRAGMA foreign_keys=ON`을 켜도:

- SQLite는 `ALTER TABLE ... ADD CONSTRAINT`가 없어 `create_all` 시점의 스키마만 강제하고,
  부분 유니크 인덱스(clawback)의 동시 INSERT 충돌 타이밍이 PG와 다르다.
- 무엇보다 이 스위트의 표준 세션은 `db_session` 하나를 라우터와 검증이 공유하므로,
  운영 Postgres에서 커밋 시점에 터지는 IntegrityError 창이 재현되지 않는다.

그래서 **실 PG에 실제로 커밋**해서 확인한다. `E2E_PG_DATABASE_URL` 이 없으면 skip이다
(= 게이트가 없으면 조용히 통과하는 게 아니라 '실행되지 않았음'이 드러난다).

실행:
    E2E_PG_DATABASE_URL=postgresql+asyncpg://storybook:storybook123@localhost:5432/storybook \
      venv/bin/python -m pytest tests/test_pg_fk_erasure.py -q
"""

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.database import get_db
from src.main import app
from src.models.db import (
    Base,
    Book,
    Character,
    CreditTransaction,
    ImagePromptsDB,
    Job,
    Page,
    Series,
    StoragePurgeTask,
    StoryDraftDB,
    UserConsent,
)

PG_URL = os.getenv("E2E_PG_DATABASE_URL", "").strip()
API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

requires_pg = pytest.mark.skipif(
    not PG_URL,
    reason="E2E_PG_DATABASE_URL 미설정 — 실 PostgreSQL FK 게이트 생략(SQLite로는 못 잡는 클래스)",
)

pytestmark = requires_pg


@pytest.fixture(scope="session")
def pg_schema_at_head():
    """실 PG 스키마를 alembic head 까지 올린다 — 마이그레이션 자체의 실 PG 리허설.

    `Base.metadata.create_all` 만으로는 **이미 존재하는 테이블**에 새 컬럼·부분 유니크
    인덱스가 붙지 않는다. 그 상태로 통과하면 '모델엔 있는데 운영 DB엔 없는' 인덱스를
    green으로 위장하게 된다(R2-2가 정확히 그 클래스).
    """
    import subprocess
    import sys

    env = dict(os.environ)
    env["DATABASE_URL"] = PG_URL
    env["TESTING"] = "false"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"alembic upgrade head 실패(실 PG):\n{proc.stdout}\n{proc.stderr[-3000:]}"
    )
    return True


@pytest_asyncio.fixture
async def pg_session(pg_schema_at_head):
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_client(pg_session):
    """실 PG 세션을 주입한 앱 클라이언트 — 라우터 코드가 진짜 PG에 커밋한다."""
    from src.services.credits import credits_service

    async def override_get_db():
        yield pg_session

    original_has, original_use = credits_service.has_credits, credits_service.use_credit

    async def allow(*a, **k):
        return True

    credits_service.has_credits = allow
    credits_service.use_credit = allow
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    credits_service.has_credits = original_has
    credits_service.use_credit = original_use
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_real_storage(monkeypatch):
    """실 PG 게이트의 관심사는 FK/트랜잭션이다 — S3는 결정적 no-op으로 고정."""
    import src.services.purge_queue as purge_module

    executed: list = []

    async def fake_execute(task):
        executed.append((task.kind, task.target))
        return []

    monkeypatch.setattr(purge_module, "_execute_task", fake_execute)
    return executed


async def _seed_photo_character_world(session, user_key: str) -> dict:
    """사진동의 → from-photo 캐릭터 → 시리즈 → 책(스칼라/다중 참조) → 파생 텍스트."""
    ids = {
        "char": f"char_{uuid.uuid4().hex[:10]}",
        "series": f"series_{uuid.uuid4().hex[:10]}",
        "job_a": f"job_{uuid.uuid4().hex[:10]}",
        "job_b": f"job_{uuid.uuid4().hex[:10]}",
        "book_a": f"book_{uuid.uuid4().hex[:10]}",
        "book_b": f"book_{uuid.uuid4().hex[:10]}",
    }

    session.add(
        UserConsent(
            user_key=user_key,
            consent_version="v2",
            privacy=True,
            photos=True,
            data_processing=True,
            granted=True,
        )
    )
    session.add(
        Character(
            id=ids["char"],
            name="아이",
            master_description="a child derived from an uploaded photo",
            appearance={"face": "round"},
            clothing={"top": "tee"},
            personality_traits=["kind"],
            user_key=user_key,
            from_photo=True,
            source_image_url="https://cdn.example.com/characters/x/photo.jpg",
        )
    )
    await session.flush()

    # H1: 시리즈가 캐릭터를 하드 FK로 붙든다 — 철회 경로가 이 FK를 풀지 않으면 PG가 500.
    session.add(
        Series(
            id=ids["series"],
            title="시리즈",
            language="ko",
            target_age="5-7",
            style="watercolor",
            character_id=ids["char"],
            user_key=user_key,
        )
    )

    for job_id, book_id, scalar_ref in (
        (ids["job_a"], ids["book_a"], True),
        (ids["job_b"], ids["book_b"], False),
    ):
        session.add(Job(id=job_id, status="done", user_key=user_key))
        await session.flush()
        session.add(
            Book(
                id=book_id,
                job_id=job_id,
                title="아이 이야기",
                language="ko",
                target_age="5-7",
                style="watercolor",
                user_key=user_key,
                series_id=ids["series"],
                # H2: book_b 는 스칼라 FK가 아니라 character_ids(가족 다중)로만 참조한다.
                character_id=ids["char"] if scalar_ref else None,
                character_ids=None if scalar_ref else ["other_char", ids["char"]],
            )
        )
        # M7: 아동 얼굴의 텍스트 묘사·이름이 담긴 파생 텍스트.
        session.add(StoryDraftDB(job_id=job_id, draft={"title": "아이 이야기"}))
        session.add(ImagePromptsDB(job_id=job_id, prompts={"cover": "a child face"}))
        await session.flush()
        session.add(Page(book_id=book_id, page_number=1, text="p1"))

    await session.commit()
    return ids


async def _cleanup(session, user_key: str, ids: dict) -> None:
    await session.rollback()
    await session.execute(
        text("DELETE FROM storage_purge_tasks WHERE user_key = :uk"), {"uk": user_key}
    )
    await session.execute(
        text("DELETE FROM credit_transactions WHERE user_key = :uk"), {"uk": user_key}
    )
    await session.execute(text("DELETE FROM pages WHERE book_id = ANY(:b)"),
                          {"b": [ids.get("book_a"), ids.get("book_b")]})
    await session.execute(text("DELETE FROM books WHERE user_key = :uk"), {"uk": user_key})
    await session.execute(text("DELETE FROM series WHERE user_key = :uk"), {"uk": user_key})
    await session.execute(text("DELETE FROM story_drafts WHERE job_id = ANY(:j)"),
                          {"j": [ids.get("job_a"), ids.get("job_b")]})
    await session.execute(text("DELETE FROM image_prompts WHERE job_id = ANY(:j)"),
                          {"j": [ids.get("job_a"), ids.get("job_b")]})
    await session.execute(text("DELETE FROM jobs WHERE user_key = :uk"), {"uk": user_key})
    await session.execute(
        text("DELETE FROM characters WHERE user_key = :uk"), {"uk": user_key}
    )
    await session.execute(
        text("DELETE FROM user_consents WHERE user_key = :uk"), {"uk": user_key}
    )
    await session.commit()


# ════════════════════════════ R1: 동의 철회 cascade ════════════════════════════


@pytest.mark.asyncio
async def test_revoke_with_series_completes_on_real_postgres(pg_client, pg_session):
    """H1/R1-1: 시리즈에 묶인 사진 캐릭터가 있어도 철회가 500 없이 완주한다.

    red-proof: `purge_photo_derived_data`의 `detach_series_from_characters(...)` 호출을
    지우면 이 테스트가 실 PG에서 `IntegrityError: violates foreign key constraint
    "series_character_id_fkey"` 로 FAIL한다(SQLite에서는 통과 — 그래서 이 게이트가 있다).
    """
    user_key = str(uuid.uuid4())
    ids = await _seed_photo_character_world(pg_session, user_key)
    try:
        r = await pg_client.post(
            "/v1/consent/revoke", headers={"X-User-Key": user_key}
        )
        assert r.status_code == 200, r.text

        pg_session.expire_all()
        # 캐릭터·책 전부 파기
        assert (
            await pg_session.execute(
                select(Character).where(Character.user_key == user_key)
            )
        ).scalars().all() == []
        assert (
            await pg_session.execute(select(Book).where(Book.user_key == user_key))
        ).scalars().all() == []
        # 시리즈는 남되 캐릭터 참조가 해제됨(FK 위반 없음)
        series = (
            await pg_session.execute(select(Series).where(Series.id == ids["series"]))
        ).scalar_one()
        assert series.character_id is None
    finally:
        await _cleanup(pg_session, user_key, ids)


@pytest.mark.asyncio
async def test_revoke_purges_multi_character_books_on_real_postgres(
    pg_client, pg_session
):
    """H2/R1-2: `character_ids`(가족 다중)로만 참조된 책도 파기된다(얼굴 렌더 잔존 방지).

    red-proof: `collect_books_referencing_characters`의 JSON 배열 스캔을 지우고
    스칼라 FK만 남기면 book_b 가 살아남아 이 테스트가 FAIL한다.
    """
    user_key = str(uuid.uuid4())
    ids = await _seed_photo_character_world(pg_session, user_key)
    try:
        r = await pg_client.post(
            "/v1/consent/revoke", headers={"X-User-Key": user_key}
        )
        assert r.status_code == 200, r.text

        pg_session.expire_all()
        remaining = (
            await pg_session.execute(
                select(Book.id).where(Book.id.in_([ids["book_a"], ids["book_b"]]))
            )
        ).all()
        assert remaining == [], f"다중 캐릭터 참조 책이 잔존: {remaining}"
    finally:
        await _cleanup(pg_session, user_key, ids)


@pytest.mark.asyncio
async def test_revoke_purges_derived_text_on_real_postgres(pg_client, pg_session):
    """M7/R1-4: 아동 얼굴 묘사·이름이 담긴 잡·초안·이미지프롬프트도 함께 파기된다.

    red-proof: `purge_book_generation_artifacts(...)` 호출을 지우면 story_drafts /
    image_prompts 행이 남아 FAIL한다.
    """
    user_key = str(uuid.uuid4())
    ids = await _seed_photo_character_world(pg_session, user_key)
    try:
        r = await pg_client.post(
            "/v1/consent/revoke", headers={"X-User-Key": user_key}
        )
        assert r.status_code == 200, r.text

        pg_session.expire_all()
        job_ids = [ids["job_a"], ids["job_b"]]
        assert (
            await pg_session.execute(
                select(StoryDraftDB.id).where(StoryDraftDB.job_id.in_(job_ids))
            )
        ).all() == []
        assert (
            await pg_session.execute(
                select(ImagePromptsDB.id).where(ImagePromptsDB.job_id.in_(job_ids))
            )
        ).all() == []
        assert (
            await pg_session.execute(select(Job.id).where(Job.id.in_(job_ids)))
        ).all() == []
    finally:
        await _cleanup(pg_session, user_key, ids)


@pytest.mark.asyncio
async def test_revoke_writes_durable_purge_tasks_on_real_postgres(
    pg_client, pg_session
):
    """M8/R1-5: 파기 지시가 삭제와 같은 커밋으로 DB에 남는다(중단돼도 되찾을 수 있음).

    red-proof: `enqueue_purge_prefix/-keys` 호출을 지우면 storage_purge_tasks 가 비어
    FAIL한다 — 그 상태가 곧 '행을 지운 뒤 파기 지시가 메모리에만 있던' 원래 결함이다.
    """
    user_key = str(uuid.uuid4())
    ids = await _seed_photo_character_world(pg_session, user_key)
    try:
        r = await pg_client.post(
            "/v1/consent/revoke", headers={"X-User-Key": user_key}
        )
        assert r.status_code == 200, r.text

        pg_session.expire_all()
        tasks = (
            await pg_session.execute(
                select(StoragePurgeTask).where(StoragePurgeTask.user_key == user_key)
            )
        ).scalars().all()
        targets = {t.target for t in tasks}
        assert f"characters/{ids['char']}/" in targets
        assert f"books/{ids['book_a']}/" in targets
        assert f"books/{ids['book_b']}/" in targets
        # 인라인 실행에 성공했으므로 done 으로 종결(스윕 재실행 대상 아님)
        assert all(t.status == "done" for t in tasks), [
            (t.target, t.status) for t in tasks
        ]
    finally:
        await _cleanup(pg_session, user_key, ids)


@pytest.mark.asyncio
async def test_photos_off_regrant_purges_on_real_postgres(pg_client, pg_session):
    """M9/R1-6: photos=false 재-grant도 철회와 **같은 경로**로 파기한다.

    red-proof: grant_consent의 `photos_revoked` 분기를 지우면 캐릭터·책이 살아남아 FAIL.
    """
    user_key = str(uuid.uuid4())
    ids = await _seed_photo_character_world(pg_session, user_key)
    try:
        r = await pg_client.post(
            "/v1/consent",
            headers={"X-User-Key": user_key},
            json={"privacy": True, "photos": False, "data_processing": True},
        )
        assert r.status_code == 200, r.text

        pg_session.expire_all()
        assert (
            await pg_session.execute(
                select(Character).where(Character.user_key == user_key)
            )
        ).scalars().all() == []
        assert (
            await pg_session.execute(select(Book).where(Book.user_key == user_key))
        ).scalars().all() == []
    finally:
        await _cleanup(pg_session, user_key, ids)


# ════════════════════════ R2-2: clawback 부분 유니크 ════════════════════════


@pytest.mark.asyncio
async def test_clawback_partial_unique_blocks_double_insert_on_real_postgres(
    pg_session,
):
    """M2/R2-2: 같은 (user_key, reference_id) clawback 2행은 DB가 거부한다.

    앱 레벨 check-then-write는 트랜잭션 밖이라 동시 환불 웹훅 두 건이 **모두** 통과할 수
    있다 — 마지막 방어선은 부분 유니크 인덱스다. refund/purchase에는 있었고 clawback만
    없었다(alembic f6a1b2c3d4e5).

    red-proof: 마이그레이션 b1c2d3e4f5a6 의 `uq_credit_transactions_clawback` 생성을
    지우고(= 인덱스 DROP) 실행하면 두 번째 INSERT가 성공해 이 테스트가 FAIL한다.
    """
    user_key = str(uuid.uuid4())
    ref = f"txn_{uuid.uuid4().hex[:12]}"

    # 모델 정의로 create_all 된 인덱스가 실제 PG에 존재하는지 먼저 확인(게이트 자체 봉인).
    idx = (
        await pg_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'credit_transactions' "
                "AND indexname = 'uq_credit_transactions_clawback'"
            )
        )
    ).first()
    assert idx is not None, "clawback 부분 유니크 인덱스가 실 PG에 없다"

    def _row():
        return CreditTransaction(
            user_key=user_key,
            amount=-5,
            balance_after=0,
            transaction_type="clawback",
            description="환불 회수",
            reference_id=ref,
        )

    try:
        pg_session.add(_row())
        await pg_session.commit()

        pg_session.add(_row())
        with pytest.raises(IntegrityError):
            await pg_session.commit()
        await pg_session.rollback()

        rows = (
            await pg_session.execute(
                select(CreditTransaction.id).where(
                    CreditTransaction.user_key == user_key,
                    CreditTransaction.transaction_type == "clawback",
                )
            )
        ).all()
        assert len(rows) == 1, f"clawback 이중 회수: {rows}"
    finally:
        await pg_session.rollback()
        await pg_session.execute(
            text("DELETE FROM credit_transactions WHERE user_key = :uk"),
            {"uk": user_key},
        )
        await pg_session.commit()
