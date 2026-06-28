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
