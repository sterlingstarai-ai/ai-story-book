"""A shared request/deadline budget for one bounded illustration operation."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import time

from src.core.errors import ErrorCode, ImageError


@dataclass
class ImageRequestBudget:
    limit: int
    deadline: float
    used: int = 0
    retry_not_before: float = 0.0

    def consume(self) -> None:
        # No await between check and increment: all child tasks share this object.
        if self.used >= self.limit or time.monotonic() >= self.deadline:
            raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 요청 한도를 초과했습니다.")
        self.used += 1


_budget: ContextVar[ImageRequestBudget | None] = ContextVar("image_request_budget", default=None)


@contextmanager
def image_request_budget(limit: int, deadline: float):
    existing = _budget.get()
    if existing is not None:
        yield existing
        return
    budget = ImageRequestBudget(limit=limit, deadline=deadline)
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


def consume_image_request() -> None:
    budget = _budget.get()
    if budget is not None:
        budget.consume()


def defer_image_requests(seconds: float) -> None:
    budget = _budget.get()
    if budget is not None:
        budget.retry_not_before = max(budget.retry_not_before, time.monotonic() + seconds)


def image_retry_fits(seconds: float) -> bool:
    budget = _budget.get()
    return budget is None or time.monotonic() + seconds < budget.deadline


async def wait_for_image_cooldown(max_wait: float) -> None:
    budget = _budget.get()
    if budget is None:
        return
    while (delay := budget.retry_not_before - time.monotonic()) > 0:
        if delay >= max_wait or budget.retry_not_before >= budget.deadline:
            raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 요청 대기 시간이 작업 한도를 초과했습니다.")
        await asyncio.sleep(delay)


def remaining_image_requests(default: int) -> int:
    """Read the shared allowance without consuming it (mocks retain a local cap)."""
    budget = _budget.get()
    return max(0, budget.limit - budget.used) if budget is not None else default
