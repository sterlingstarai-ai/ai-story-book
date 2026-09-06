"""A shared request/deadline budget for one bounded illustration operation."""

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
