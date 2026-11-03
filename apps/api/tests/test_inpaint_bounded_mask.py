"""Regression: hosted APIs must bound the in-memory read of an inpaint mask."""

from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import UploadFile

from src.core.config import settings
from src.models.db import Book, Job, Page
from src.routers import books


@pytest.mark.asyncio
async def test_oversized_inpaint_mask_is_bounded_before_paid_work(
    client, db_session, headers, monkeypatch
):
    monkeypatch.setattr(settings, "image_provider", "fal")
    monkeypatch.setattr(books, "_MAX_MASK_BYTES", 8)
    user_key = headers["X-User-Key"]
    db_session.add(Job(id="bounded-mask-job", status="done", user_key=user_key))
    await db_session.flush()
    db_session.add(Book(id="bounded-mask-book", job_id="bounded-mask-job", title="test",
                        language="ko", target_age="5-7", style="watercolor", user_key=user_key))
    db_session.add(Page(book_id="bounded-mask-book", page_number=1, text="test",
                        image_url="https://img.example/p.png", image_prompt="test"))
    await db_session.commit()

    original_read = UploadFile.read
    read_sizes = []

    async def observed_read(upload, size=-1):
        read_sizes.append(size)
        return await original_read(upload, size)

    monkeypatch.setattr(UploadFile, "read", observed_read)
    upload = AsyncMock()
    budget = AsyncMock()
    monkeypatch.setattr(books.storage_service, "upload_bytes", upload)
    monkeypatch.setattr(books, "consume_daily_generation_budget", budget)

    response = await client.post(
        "/v1/books/bounded-mask-job/pages/1/inpaint",
        files={"mask": ("mask.png", b"x" * 32, "image/png")},
        data={"region_prompt": "make the sky orange"},
        headers=headers,
    )

    assert response.status_code in (400, 413, 422)
    assert read_sizes == [9]
    upload.assert_not_awaited()
    budget.assert_not_awaited()
