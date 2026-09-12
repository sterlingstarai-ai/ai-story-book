"""Stable keyset pagination, including ties and filtered result sets."""

from datetime import datetime

import pytest

from src.models.db import Book
from tests.factories import make_book_rows


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["newest", "oldest", "title"])
async def test_cursor_visits_each_filtered_book_once(client, db_session, headers, sort):
    owner = headers["X-User-Key"]
    ids = ["page-c", "page-a", "page-e", "page-b", "page-d"]
    rows = make_book_rows([(key, owner) for key in ids] + [("foreign", "other")])
    for row in rows:
        if isinstance(row, Book):
            row.created_at = datetime(2026, 1, 1)
            row.title = "Alpha" if row.id in {"page-a", "page-c"} else "Beta"
    db_session.add_all(rows)
    await db_session.commit()

    seen = []
    cursor = None
    for _ in range(3):
        params = {"sort": sort, "limit": 2, "style": "watercolor"}
        if cursor:
            params["cursor"] = cursor
        response = await client.get("/v1/library", headers=headers, params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 5
        seen.extend(book["book_id"] for book in data["books"])
        cursor = data["next_cursor"]
    expected = sorted(ids, reverse=sort == "newest")
    if sort == "title":
        expected = ["page-a", "page-c", "page-b", "page-d", "page-e"]
    assert seen == expected
    assert cursor is None
    assert data["has_more"] is False
