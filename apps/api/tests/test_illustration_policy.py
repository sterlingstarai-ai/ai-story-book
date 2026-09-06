"""Twelve-page repair policy and the real orchestrator request pool stay aligned."""

import time

import pytest

from src.core.errors import ErrorCode, ImageError
from src.models.dto import BookSpec
from src.services import orchestrator, illustration_quality_pipeline
from src.services.illustration_policy import book_image_request_limit, max_repair_pages
from src.services.image_request_budget import consume_image_request, _budget


@pytest.mark.asyncio
@pytest.mark.parametrize("pages,repairs,total", [(4, 2, 7), (8, 2, 11), (11, 2, 14), (12, 3, 16)])
async def test_orchestrator_shares_exact_initial_retry_and_repair_pool(monkeypatch, pages, repairs, total):
    assert max_repair_pages(pages) == repairs
    assert book_image_request_limit(pages) == total
    monkeypatch.setattr(illustration_quality_pipeline, "quality_enabled_for_operation", lambda: True)

    async def pipeline(*_args, **kwargs):
        current = _budget.get()
        assert current.limit == total
        assert current.deadline == kwargs["quality_deadline"]
        assert current.deadline <= time.monotonic() + 590
        for _ in range(total):
            consume_image_request()
        with pytest.raises(ImageError) as caught:
            consume_image_request()
        assert caught.value.code == ErrorCode.IMAGE_QUALITY_FAILED
        return "checked"

    monkeypatch.setattr(orchestrator, "_start_book_generation", pipeline)
    result = await orchestrator.start_book_generation(
        "inert-policy-check", BookSpec(topic="정원 모험", target_age="7-9", style="watercolor", page_count=pages), "inert-owner",
    )
    assert result == "checked" and _budget.get() is None
