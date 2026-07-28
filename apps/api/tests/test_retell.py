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
    # 연령 변형은 원본 책으로 역링크된다(grow-with-child 묶음)
    assert new_book.retelling_source_book_id == "book-retell-src"


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


@pytest.mark.asyncio
async def test_retell_output_moderation_blocks_unsafe(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    """M12: 리텔 결과가 금칙 표현을 담으면 저장 전 SAFETY_OUTPUT으로 차단(무검사 우회 제거)."""
    await _seed_book(db_session, headers["X-User-Key"], "book-retell-unsafe")

    unsafe = RetoldStory(title="잔혹 동화", pages=["늑대가 토끼를 잔혹하게 살해했다", "쉬운 2"])
    with patch(
        "src.services.llm.call_story_retext",
        new=AsyncMock(return_value=unsafe),
    ):
        res = await client.post(
            "/v1/books/book-retell-unsafe/retell",
            json={"target_age": "3-5"},
            headers=headers,
        )

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "SAFETY_OUTPUT"

    # 새 책이 생성되지 않았다(무검사 저장 우회 제거).
    new_books = (
        await db_session.execute(
            select(Book).where(Book.retelling_source_book_id == "book-retell-unsafe")
        )
    ).scalars().all()
    assert new_books == []


@pytest.mark.asyncio
async def test_delete_original_nullifies_retell_link(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    """M10: 원본 책 삭제 시 리텔 변형본의 retelling_source_book_id가 null화(고아·FK위반 방지)."""
    await _seed_book(db_session, headers["X-User-Key"], "book-retell-origin")

    retold = RetoldStory(title="쉬운", pages=["쉬운 1", "쉬운 2"])
    with patch(
        "src.services.llm.call_story_retext",
        new=AsyncMock(return_value=retold),
    ):
        res = await client.post(
            "/v1/books/book-retell-origin/retell",
            json={"target_age": "3-5"},
            headers=headers,
        )
    assert res.status_code == 200, res.text
    variant_id = res.json()["book_id"]

    variant = (await db_session.execute(select(Book).where(Book.id == variant_id))).scalar_one()
    assert variant.retelling_source_book_id == "book-retell-origin"

    # 원본 삭제 → 변형본 링크 null화(FK/purge 동작), 삭제 자체는 성공.
    r = await client.delete("/v1/library/book-retell-origin", headers=headers)
    assert r.status_code in (200, 204), r.text

    db_session.expire_all()
    variant = (await db_session.execute(select(Book).where(Book.id == variant_id))).scalar_one()
    assert variant.retelling_source_book_id is None


@pytest.mark.asyncio
async def test_retell_is_idempotent_across_client_retry(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    """#9(H17/G19): 요청 내 동기 리텔은 클라 타임아웃 후에도 서버가 완주한다.

    같은 시도키로 재시도하면 중복 리텔 책·LLM 비용이 발생하므로, H18의 잡 멱등 패턴을
    미러해 기존 결과를 반환해야 한다.
    """
    await _seed_book(db_session, headers["X-User-Key"], "book-retell-idem")

    retold = RetoldStory(title="쉬운 동화", pages=["쉬운 1", "쉬운 2"])
    h = {**headers, "X-Idempotency-Key": "retell-attempt-1"}

    with patch(
        "src.services.llm.call_story_retext",
        new=AsyncMock(return_value=retold),
    ) as llm:
        first = await client.post(
            "/v1/books/book-retell-idem/retell", json={"target_age": "3-5"}, headers=h
        )
        second = await client.post(
            "/v1/books/book-retell-idem/retell", json={"target_age": "3-5"}, headers=h
        )

    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json()["book_id"] == second.json()["book_id"], "중복 리텔 책 생성"
    assert llm.await_count == 1, "재시도에서 LLM을 다시 호출하면 비용 낭비"

    books = (
        await db_session.execute(
            select(Book).where(Book.retelling_source_book_id == "book-retell-idem")
        )
    ).scalars().all()
    assert len(books) == 1
