"""P1-7: 연령 리텔 — 같은 책을 다른 연령대 본문으로 다시 써 새 책으로 저장(삽화 재사용)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import Book, Job, Page
from src.models.dto import RetoldStory


async def _seed_book(db_session, user_key: str, book_id: str):
    job = Job(id=f"job-{book_id}", status="done", user_key=user_key)
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        Book(
            id=book_id,
            job_id=job.id,
            title="원본 동화",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=user_key,
            cover_image_url="https://img/cover.png",
        )
    )
    db_session.add(
        Page(book_id=book_id, page_number=1, text="원본 1",
             image_url="https://img/p1.png", image_prompt="x")
    )
    db_session.add(
        Page(book_id=book_id, page_number=2, text="원본 2",
             image_url="https://img/p2.png", image_prompt="x")
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_retell_creates_new_book_reusing_images(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    await _seed_book(db_session, headers["X-User-Key"], "book-retell-src")

    retold = RetoldStory(title="쉬운 동화", pages=["쉬운 1", "쉬운 2"])
    with patch(
        "src.services.llm.call_story_retext",
        new=AsyncMock(return_value=retold),
    ):
        res = await client.post(
            "/v1/books/book-retell-src/retell",
            json={"target_age": "3-5"},
            headers=headers,
        )

    assert res.status_code == 200
    new_id = res.json()["book_id"]
    assert new_id != "book-retell-src"
    assert res.json()["target_age"] == "3-5"

    new_pages = (
        await db_session.execute(
            select(Page).where(Page.book_id == new_id).order_by(Page.page_number)
        )
    ).scalars().all()
    # 삽화는 그대로 재사용, 본문은 새 연령대 텍스트
    assert [p.image_url for p in new_pages] == [
        "https://img/p1.png",
        "https://img/p2.png",
    ]
    assert new_pages[0].text == "쉬운 1"
    assert new_pages[1].text == "쉬운 2"

    new_book = (
        await db_session.execute(select(Book).where(Book.id == new_id))
    ).scalar_one()
    assert new_book.target_age == "3-5"
    assert new_book.cover_image_url == "https://img/cover.png"
    assert new_book.title == "쉬운 동화"


@pytest.mark.asyncio
async def test_retell_rejects_other_users_book(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    await _seed_book(db_session, "someone-else", "book-retell-other")

    res = await client.post(
        "/v1/books/book-retell-other/retell",
        json={"target_age": "3-5"},
        headers=headers,
    )
    assert res.status_code in (401, 403, 404)
