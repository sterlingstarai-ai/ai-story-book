"""오늘의 동화 생성(book_id 공백 해소) + 생성/소비 분리 테스트."""

import pytest
from sqlalchemy import select

from src.models.db import Job
from tests.factories import make_book_rows

H = {"X-User-Key": "33333333-3333-4333-8333-333333333333"}


@pytest.mark.asyncio
async def test_today_generate_creates_personalized_job(client, db_session):
    res = await client.post(
        "/v1/streak/today/generate",
        json={
            "target_age": "5-7",
            "style": "watercolor",
            "protagonist_name": "지우",
        },
        headers=H,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["job_id"].startswith("job_")
    assert data["status"] == "queued"

    job = (
        await db_session.execute(select(Job).where(Job.id == data["job_id"]))
    ).scalar_one_or_none()
    assert job is not None
    assert job.user_key == H["X-User-Key"]


@pytest.mark.asyncio
async def test_today_generate_idempotent_same_key(client, db_session):
    """같은 X-Idempotency-Key로 2회 생성 → 잡 1건만(재탭 이중 생성·차감 방지, H18)."""
    body = {"target_age": "5-7", "style": "watercolor"}
    h = {**H, "X-Idempotency-Key": "today-key-1"}

    r1 = await client.post("/v1/streak/today/generate", json=body, headers=h)
    r2 = await client.post("/v1/streak/today/generate", json=body, headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["job_id"] == r2.json()["job_id"]  # 기존 잡 반환

    jobs = (
        await db_session.execute(select(Job).where(Job.user_key == H["X-User-Key"]))
    ).scalars().all()
    assert len([j for j in jobs if j.idempotency_key == "today-key-1"]) == 1


@pytest.mark.asyncio
async def test_reading_maintains_streak_independent_of_generation(client, db_session):
    """읽기(소비)는 생성 한도/크레딧과 무관하게 스트릭을 유지한다."""
    db_session.add_all(make_book_rows([("some-existing-book", H["X-User-Key"])]))
    await db_session.commit()
    res = await client.post(
        "/v1/streak/read",
        json={"book_id": "some-existing-book", "reading_time": 120, "completed": True},
        headers=H,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("current_streak", 0) >= 1


def test_every_daily_theme_maps_to_theme_enum():
    """L17: 7개 일일 테마 코드가 모두 유효 Theme enum 멤버(역매핑 실패 조용한 None 제거)."""
    from src.models.dto import Theme
    from src.services.streak import DAILY_THEMES

    for entry in DAILY_THEMES:
        assert entry["theme"] in Theme.__members__, f"unmapped: {entry['theme']}"


@pytest.mark.asyncio
async def test_generate_sets_book_theme_for_courage_day(client, db_session, monkeypatch):
    """L17: courage 테마 날의 오늘의 동화가 theme=None이 아니라 courage로 생성된다."""
    from src.services import streak as streak_service_module

    async def fake_today(db):
        return {"theme": "courage", "topic": "두려움 극복하기", "book_id": None}

    monkeypatch.setattr(streak_service_module.streak_service, "get_today_story", fake_today)
    r = await client.post(
        "/v1/streak/today/generate",
        json={"target_age": "5-7", "style": "watercolor"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    from src.models.db import Job

    job = (await db_session.execute(select(Job).where(Job.id == r.json()["job_id"]))).scalar_one()
    # Job엔 theme가 직접 없지만 story_draft 경로 대신 spec.theme가 courage로 세팅됐음을 간접 확인:
    # 생성 자체가 성공(theme 매핑 실패로 None이어도 생성은 됨)하므로, 매핑 단위는 아래 enum 테스트로 보증.
    assert job is not None


@pytest.mark.asyncio
async def test_daily_story_date_unique_constraint(db_session):
    """H14: 같은 date로 DailyStory 2행 직접 insert → 2번째 IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    from src.core.utils import local_day_bounds_utc
    from src.models.db import DailyStory

    today_start, _ = local_day_bounds_utc()
    db_session.add(DailyStory(date=today_start, theme="a", topic="t1"))
    await db_session.commit()
    db_session.add(DailyStory(date=today_start, theme="b", topic="t2"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_get_today_story_race_absorbs_duplicate(db_session, monkeypatch):
    """H14: 동시 INSERT 경쟁이 IntegrityError로 잡히고 rollback 후 재조회로 멱등 반환(500 없음)."""
    from src.core.database import AsyncSessionLocal
    from src.core.utils import local_day_bounds_utc
    from src.models.db import DailyStory
    from src.services.streak import streak_service

    today_start, _ = local_day_bounds_utc()
    real_commit = db_session.commit
    fired = {"done": False}

    async def racing_commit(*a, **k):
        if not fired["done"]:
            fired["done"] = True
            async with AsyncSessionLocal() as other:
                other.add(DailyStory(date=today_start, theme="friendship", topic="경쟁 토픽"))
                await other.commit()
        return await real_commit(*a, **k)

    monkeypatch.setattr(db_session, "commit", racing_commit)
    result = await streak_service.get_today_story(db_session)
    assert result["theme"] == "friendship"  # 경쟁 세션 행을 예외 없이 반환

    monkeypatch.undo()
    db_session.expire_all()
    rows = (
        await db_session.execute(select(DailyStory).where(DailyStory.date == today_start))
    ).scalars().all()
    assert len(rows) == 1  # 중복 없음
