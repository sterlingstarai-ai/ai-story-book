"""New-book quotas and profile scope after ancillary book operations."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.core.utils import local_day_bounds_utc
from src.models.db import Book, ChildProfile, Job, Page
from src.models.dto import RetoldStory
from src.routers import books


@pytest.mark.asyncio
async def test_page_edits_do_not_exhaust_daily_new_book_quota(
    client, db_session, headers, valid_book_spec, monkeypatch
):
    """One book plus nineteen repairs still permits the second new book."""
    user_key = headers["X-User-Key"]
    today_start, _ = local_day_bounds_utc()
    for job_id in [
        "job_first",
        *[f"regen_{number}" for number in range(19)],
        "inpaint_done", "audio_done", "retell_done",
    ]:
        db_session.add(Job(
            id=job_id, status="done", user_key=user_key, created_at=today_start
        ))
    db_session.add(Job(
        id="job_refunded", status="failed", user_key=user_key, created_at=today_start
    ))
    await db_session.commit()
    monkeypatch.setattr(settings, "daily_job_limit_per_user", 2)
    budget = AsyncMock(return_value=(True, 1))
    monkeypatch.setattr(books, "consume_daily_generation_budget", budget)

    assert await books._count_monthly_book_creations(db_session, user_key) == 1
    response = await client.post("/v1/books", json=valid_book_spec, headers=headers)
    assert response.status_code == 200, response.text
    budget.assert_awaited_once()
    assert await books._count_monthly_book_creations(db_session, user_key) == 2

    blocked = await client.post("/v1/books", json=valid_book_spec, headers=headers)
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["code"] == "DAILY_LIMIT_EXCEEDED"
    assert blocked.json()["error"]["details"]["used"] == 2
    budget.assert_awaited_once()  # Rejected requests consume no global cost budget.


@pytest.mark.asyncio
async def test_queued_and_running_series_reserve_daily_book_allowance(
    client, db_session, headers, valid_book_spec, monkeypatch
):
    user_key = headers["X-User-Key"]
    for job_id, status in [("series_running", "running"), ("job_queued", "queued")]:
        db_session.add(Job(id=job_id, status=status, user_key=user_key))
    await db_session.commit()
    monkeypatch.setattr(settings, "daily_job_limit_per_user", 2)

    assert await books._count_monthly_book_creations(db_session, user_key) == 2
    response = await client.post("/v1/books", json=valid_book_spec, headers=headers)
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "DAILY_LIMIT_EXCEEDED"
    assert response.json()["error"]["details"]["used"] == 2


async def _seed_profile_book(db, user_key, *, shared=False):
    for profile_id in ["child-a", "child-b"]:
        db.add(ChildProfile(id=profile_id, user_key=user_key, name=f"테스트 {profile_id}"))
    scope = None if shared else "child-a"
    db.add(Job(id="job_source", status="done", user_key=user_key, profile_id=scope))
    await db.flush()
    db.add(Book(
        id="book-source", job_id="job_source", title="함께 읽는 이야기",
        language="ko", target_age="5-7", style="watercolor", user_key=user_key,
        profile_id=scope, cover_image_url="https://img/cover.png",
    ))
    await db.flush()
    db.add(Page(
        book_id="book-source", page_number=1, text="친구와 책을 읽어요.",
        image_url="https://img/page.png",
    ))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_retell_inherits_source_scope_and_retries_without_another_call(
    client, db_session, headers, monkeypatch, shared
):
    await _seed_profile_book(db_session, headers["X-User-Key"], shared=shared)
    retell = AsyncMock(return_value=RetoldStory(title="쉬운 이야기", pages=["책을 봐요."]))
    monkeypatch.setattr("src.services.llm.call_story_retext", retell)
    selected = {**headers, "X-Profile-Id": "child-a", "X-Idempotency-Key": "retell-once"}
    response = await client.post(
        "/v1/books/book-source/retell", json={"target_age": "3-5"}, headers=selected
    )
    assert response.status_code == 200, response.text
    new_book = await db_session.get(Book, response.json()["book_id"])
    new_job = await db_session.get(Job, new_book.job_id)
    assert new_book.profile_id == new_job.profile_id == (None if shared else "child-a")
    assert (await client.get(f"/v1/books/{new_job.id}", headers=selected)).status_code == 200

    retry = await client.post(
        "/v1/books/book-source/retell", json={"target_age": "3-5"}, headers=selected
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["book_id"] == new_book.id
    retell.assert_awaited_once()

    other_child = {**selected, "X-Profile-Id": "child-b"}
    expected = 200 if shared else 403
    assert (await client.get(f"/v1/books/{new_job.id}", headers=other_child)).status_code == expected
    replay = await client.post(
        "/v1/books/book-source/retell", json={"target_age": "3-5"}, headers=other_child
    )
    assert replay.status_code == expected, replay.text
    retell.assert_awaited_once()


@pytest.mark.asyncio
async def test_retell_rejects_other_child_before_provider_or_budget(
    client, db_session, headers, monkeypatch
):
    await _seed_profile_book(db_session, headers["X-User-Key"])
    retell = AsyncMock()
    budget = AsyncMock()
    monkeypatch.setattr("src.services.llm.call_story_retext", retell)
    monkeypatch.setattr(books, "consume_generation_budget", budget)
    response = await client.post(
        "/v1/books/book-source/retell", json={"target_age": "3-5"},
        headers={**headers, "X-Profile-Id": "child-b"},
    )
    assert response.status_code == 403, response.text
    retell.assert_not_awaited()
    budget.assert_not_awaited()
    assert await db_session.scalar(select(func.count(Book.id))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_audio_job_inherits_source_scope_for_polling(
    client, db_session, headers, monkeypatch, shared
):
    await _seed_profile_book(db_session, headers["X-User-Key"], shared=shared)
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    dispatch = AsyncMock()
    monkeypatch.setattr(books, "_dispatch_long_running_job", dispatch)
    selected = {**headers, "X-Profile-Id": "child-a"}
    response = await client.post("/v1/books/book-source/audio", headers=selected)
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    job = await db_session.get(Job, job_id)
    assert job.profile_id == (None if shared else "child-a")
    dispatch.assert_awaited_once()
    assert (await client.get(f"/v1/books/{job_id}", headers=selected)).status_code == 200
    other_child = {**headers, "X-Profile-Id": "child-b"}
    assert (await client.get(f"/v1/books/{job_id}", headers=other_child)).status_code == (200 if shared else 403)
