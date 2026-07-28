"""P2-13: 인페인트(부분 재생성) — 능력 게이트 + base/mask 프롬프트 스레딩."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.db import Book, Job, Page
from src.services.image import supports_inpaint


def test_supports_inpaint_only_replicate_and_fal(monkeypatch):
    for provider, expected in [
        ("replicate", True),
        ("fal", True),
        ("openai", False),
        ("gemini", False),
        ("mock", False),
    ]:
        monkeypatch.setattr(settings, "image_provider", provider)
        assert supports_inpaint() is expected


@pytest.mark.asyncio
async def test_capabilities_endpoint_reports_inpaint_support(
    client: AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr(settings, "image_provider", "fal")
    res = await client.get("/v1/config/capabilities")
    assert res.status_code == 200
    assert res.json()["inpaint_supported"] is True

    monkeypatch.setattr(settings, "image_provider", "openai")
    res = await client.get("/v1/config/capabilities")
    assert res.json()["inpaint_supported"] is False


@pytest.mark.asyncio
async def test_inpaint_endpoint_409_when_provider_unsupported(
    client: AsyncClient,
    headers: dict,
    monkeypatch,
):
    # 기본 테스트 provider는 mock(미지원) → 409로 폴백 신호
    monkeypatch.setattr(settings, "image_provider", "mock")
    res = await client.post(
        "/v1/books/job-x/pages/1/inpaint",
        files={"mask": ("mask.png", b"\x89PNG\r\n", "image/png")},
        data={"region_prompt": "make the sky orange"},
        headers=headers,
    )
    assert res.status_code == 409
    # 봉투 위치까지 고정한다: 클라이언트는 error.code로 폴백을 판정하므로 부분문자열
    # 매칭으로는 shape 드리프트(detail vs error.code)를 잡지 못한다(L14 회귀 재발 방지).
    assert res.json()["error"]["code"] == "INPAINT_UNSUPPORTED"


@pytest.mark.asyncio
async def test_inpaint_page_threads_base_and_mask_and_updates_image(
    db_session: AsyncSession,
    headers: dict,
):
    job = Job(id="job-inpaint", status="done", user_key=headers["X-User-Key"])
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        Book(
            id="book-inpaint",
            job_id=job.id,
            title="원본",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=headers["X-User-Key"],
            cover_image_url="https://img/cover.png",
        )
    )
    db_session.add(
        Page(
            book_id="book-inpaint",
            page_number=1,
            text="원본 1",
            image_url="https://img/p1.png",
            image_prompt="a cozy forest, soft watercolor, the same child",
        )
    )
    await db_session.commit()

    captured = {}

    async def fake_generate(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return "https://img/inpainted.png"

    from src.services.orchestrator import inpaint_page

    with patch(
        "src.services.image.generate_image",
        new=AsyncMock(side_effect=fake_generate),
    ):
        await inpaint_page(
            job_id="job-inpaint",
            book_id="book-inpaint",
            page_number=1,
            mask_url="https://img/mask.png",
            region_prompt="make the sky sunset orange",
        )

    # base 이미지 + 마스크가 프롬프트에 실린다(인페인트)
    assert captured["prompt"].base_image_url == "https://img/p1.png"
    assert captured["prompt"].mask_url == "https://img/mask.png"
    assert "sunset orange" in captured["prompt"].positive_prompt

    # 페이지 이미지가 갱신된다
    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        page = (
            await session.execute(
                select(Page).where(
                    Page.book_id == "book-inpaint", Page.page_number == 1
                )
            )
        ).scalar_one()
        assert page.image_url == "https://img/inpainted.png"
