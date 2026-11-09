"""Legacy unassigned books remain usable without exposing another child's books."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from src.models.db import Book, ChildProfile, Job, Page
from src.routers import books


OTHER_OWNER = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


async def _seed(db, owner):
    for profile_id, account in [("child-a", owner), ("child-b", owner), ("child-c", OTHER_OWNER)]:
        db.add(ChildProfile(id=profile_id, user_key=account, name=f"테스트 {profile_id}"))
    for name, scope, account in [
        ("shared", None, owner), ("a", "child-a", owner),
        ("b", "child-b", owner), ("other", "child-c", OTHER_OWNER),
    ]:
        job = Job(id=f"job_{name}", status="done", user_key=account, profile_id=scope)
        db.add(job)
        await db.flush()
        db.add(Book(
            id=f"book-{name}", job_id=job.id, title=f"이야기 {name}",
            language="ko", target_age="5-7", style="watercolor",
            user_key=account, profile_id=scope,
            cover_image_url=f"https://img/{name}/cover.png",
        ))
        await db.flush()
        db.add(Page(
            book_id=f"book-{name}", page_number=1, text="친구와 읽어요.",
            image_url=f"https://img/{name}/page.png",
        ))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("newest", ["book-shared", "book-a"]),
        ("oldest", ["book-a", "book-shared"]),
        ("title", ["book-a", "book-shared"]),
    ],
)
async def test_library_total_survives_end_of_scoped_page(
    client, db_session, headers, sort, expected,
):
    await _seed(db_session, headers["X-User-Key"])
    await db_session.execute(
        update(Book).values(title="Same title", created_at=datetime(2026, 1, 1))
    )
    await db_session.commit()
    selected = {**headers, "X-Profile-Id": "child-a"}
    query = {"sort": sort, "style": "watercolor", "target_age": "5-7", "limit": 1}

    async def listing(**page):
        result = await client.get("/v1/library", headers=selected, params={**query, **page})
        assert result.status_code == 200, result.text
        return result.json()

    for cursor in ("book-other", "book-b", "missing-book"):
        fallback = await listing(cursor=cursor, offset=1)
        assert [book["book_id"] for book in fallback["books"]] == expected[:1]

    first = await listing()
    assert first["total"] == 2
    assert first["has_more"] and first["next_cursor"] == expected[0]
    second = await listing(cursor=first["next_cursor"])
    assert [book["book_id"] for book in first["books"] + second["books"]] == expected
    assert second["total"] == 2
    assert not second["has_more"] and second["next_cursor"] is None

    empty = {"books": [], "total": 2, "has_more": False, "next_cursor": None}
    assert await listing(offset=2) == empty
    assert await listing(cursor=expected[-1]) == empty
    assert await listing(target_age="7-9") == {**empty, "total": 0}


@pytest.mark.asyncio
async def test_legacy_book_survives_profile_selection_and_remains_manageable(
    client, db_session, headers, monkeypatch
):
    await _seed(db_session, headers["X-User-Key"])
    monkeypatch.setattr(books.pdf_service, "generate_pdf", AsyncMock(return_value=b"%PDF-test"))
    for child in ["a", "b"]:
        selected = {**headers, "X-Profile-Id": f"child-{child}"}
        listing = await client.get("/v1/library", headers=selected)
        assert listing.status_code == 200, listing.text
        assert {book["book_id"] for book in listing.json()["books"]} == {"book-shared", f"book-{child}"}
        assert listing.json()["total"] == 2
        assert (await client.get("/v1/books/job_shared", headers=selected)).status_code == 200
        assert (await client.get("/v1/books/book-shared/detail", headers=selected)).status_code == 200
        assert (await client.get("/v1/books/book-shared/pdf", headers=selected)).status_code == 200
        updated = await client.patch(
            "/v1/library/book-shared", json={"title": f"공용 이야기 {child}"}, headers=selected,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["title"] == f"공용 이야기 {child}"

    deleted = await client.delete(
        "/v1/library/book-shared", headers={**headers, "X-Profile-Id": "child-b"}
    )
    assert deleted.status_code == 200, deleted.text
    assert await db_session.get(Book, "book-shared") is None
    assert await db_session.get(Book, "book-a") is not None
    assert await db_session.get(Book, "book-b") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("other_account", [False, True])
async def test_shared_access_keeps_assigned_and_other_account_books_private(
    client, db_session, headers, monkeypatch, other_account
):
    await _seed(db_session, headers["X-User-Key"])
    selected = (
        {"X-User-Key": OTHER_OWNER, "X-Profile-Id": "child-c"}
        if other_account else {**headers, "X-Profile-Id": "child-b"}
    )
    budget = AsyncMock()
    dispatch = AsyncMock()
    pdf = AsyncMock()
    monkeypatch.setattr(books, "consume_generation_budget", budget)
    monkeypatch.setattr(books, "_dispatch_long_running_job", dispatch)
    monkeypatch.setattr(books.pdf_service, "generate_pdf", pdf)

    listing = await client.get("/v1/library", headers=selected)
    assert listing.status_code == 200, listing.text
    visible = {book["book_id"] for book in listing.json()["books"]}
    assert visible == ({"book-other"} if other_account else {"book-b", "book-shared"})
    for url in ["/v1/books/job_a", "/v1/books/book-a/detail", "/v1/books/book-a/pdf"]:
        assert (await client.get(url, headers=selected)).status_code == 403
    rename = await client.patch("/v1/library/book-a", json={"title": "변경 시도"}, headers=selected)
    assert rename.status_code == 403, rename.text
    regenerate = await client.post(
        "/v1/books/job_a/pages/1/regenerate", json={"mode": "image"}, headers=selected,
    )
    assert regenerate.status_code == 403, regenerate.text
    assert (await client.delete("/v1/library/book-a", headers=selected)).status_code == 403
    assert (await db_session.get(Book, "book-a")).title == "이야기 a"
    budget.assert_not_awaited()
    dispatch.assert_not_awaited()
    pdf.assert_not_awaited()
