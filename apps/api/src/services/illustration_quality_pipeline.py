"""Bounded prepublication illustration review and transactional edit support.

The reviewer only receives generated illustrations from authorized book/job
context. Source photographs, arbitrary URLs, and model-written repair prompts
never cross this boundary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Awaitable, Callable
import uuid

from src.core.errors import ErrorCode, StoryBookError
from src.models.dto import ImagePrompt
from src.services.storage import get_object_bytes, key_from_public_url
from src.services.image_correction import CORRECTION_INSTRUCTIONS, image_correction_scope
from src.services.illustration_diagnostics import record_illustration_diagnostic
from src.services.illustration_policy import max_repair_pages


REVIEW_TIMEOUT = 45.0
COMMIT_RESERVE_SECONDS = 5.0
MIN_REPAIR_SECONDS = 30.0
PROGRESS_VERIFY = 86
PROGRESS_REPAIR = 87
PROGRESS_REVERIFY = 88
_ISSUE_INSTRUCTIONS = CORRECTION_INSTRUCTIONS
_BLOCKING_ISSUES = {"unsafe_depiction", "uncertain"}


def quality_failure(reason: str | None = None) -> StoryBookError:
    if reason is not None:
        record_illustration_diagnostic("pipeline", reason, error_code=ErrorCode.IMAGE_QUALITY_FAILED)
    return StoryBookError(
        ErrorCode.IMAGE_QUALITY_FAILED,
        "완성된 삽화가 품질 검사를 통과하지 못했습니다. 기존 내용은 변경되지 않습니다.",
    )


def quality_enabled_for_operation() -> bool:
    """Production cannot publish through a accidentally disabled quality gate."""
    from src.core.config import settings

    enabled = bool(getattr(settings, "illustration_quality_enabled", False))
    if not enabled and not settings.testing:
        raise quality_failure("quality_disabled")
    return enabled


def seconds_remaining(deadline: float, *, reserve: float = COMMIT_RESERVE_SECONDS) -> float:
    remaining = deadline - time.monotonic() - reserve
    if remaining <= 0:
        raise quality_failure("deadline_exhausted")
    return remaining


async def queue_discarded_images(user_key: str, urls: list[str], retained_urls: set[str]) -> None:
    """Record cleanup durably; never delete assets still used by a stored book."""
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, Page
    from src.services.purge_queue import enqueue_purge_keys

    async with AsyncSessionLocal() as db:
        keys = []
        for url in set(urls) - retained_urls:
            key = key_from_public_url(url)
            if not key:
                continue
            if await db.scalar(select(Page.id).where(Page.image_url == url).limit(1)):
                continue
            if await db.scalar(select(Book.id).where(Book.cover_image_url == url).limit(1)):
                continue
            keys.append(key)
        enqueue_purge_keys(db, user_key=user_key, reason="rejected_illustration", keys=keys)
        await db.commit()


@dataclass
class VerifiedIllustrations:
    image_urls: dict[int, str]
    image_prompts: dict[int, ImagePrompt]
    discarded_urls: list[str]
    repaired_pages: list[int]


def corrected_prompt(prompt: ImagePrompt, page_text: str, issues: list[str]) -> ImagePrompt:
    """Keep the complete visual brief; corrections travel in the provider scope."""
    if not issues or any(issue not in _ISSUE_INSTRUCTIONS for issue in issues):
        raise quality_failure("correction_invalid")
    return prompt.model_copy(
        update={
            "negative_prompt": (
                "readable text, labels, duplicate people, exchanged identities, incorrect action, "
                + prompt.negative_prompt
            )[:600],
            "seed": 1 + uuid.uuid4().int % 2_147_483_646,
        }
    )


async def _load_owned_images(image_urls: dict[int, str], allowed_keys: set[str], deadline: float):
    images = {}
    for page, url in image_urls.items():
        key = key_from_public_url(url)
        # The caller's keys come only from this job's generated outputs or an
        # ownership-checked Book/Page snapshot. Never fetch arbitrary URLs.
        if not key or key not in allowed_keys or "placeholder" in url:
            raise quality_failure("asset_invalid")
        data, _stored_mime = await asyncio.wait_for(
            get_object_bytes(key), timeout=min(15.0, seconds_remaining(deadline))
        )
        # Identify original bytes without trusting old metadata/file extensions
        # and without converting or resizing the illustration.
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise quality_failure("asset_invalid")
        images[page] = (data, mime)
    return images


async def verify_and_repair_illustrations(
    *,
    title: str,
    page_texts: dict[int, str],
    image_prompts: dict[int, ImagePrompt],
    image_urls: dict[int, str],
    deadline: float,
    regenerate: Callable[[int, ImagePrompt, dict[int, str]], Awaitable[str]],
    on_progress: Callable[[str, int], Awaitable[None]] | None = None,
    repairable_pages: set[int] | None = None,
) -> VerifiedIllustrations:
    """Review, repair each affected page once within the book limit, review all again.

    A regeneration callback receives current candidate URLs, except that page 0
    is omitted when it is the repair target or has not passed the initial review.
    This prevents older cover-primary fallbacks from propagating a flagged cover.
    """
    from src.services.image_quality import review_book_illustrations

    urls = dict(image_urls)
    prompts = dict(image_prompts)
    expected = set(page_texts)
    repair_limit = max_repair_pages(len(expected) - 1)
    if expected != set(prompts) or expected != set(urls):
        raise quality_failure("page_coverage_invalid")
    allowed_keys = {key for url in urls.values() if (key := key_from_public_url(url))}
    discarded = []

    async def review():
        images = await _load_owned_images(urls, allowed_keys, deadline)
        timeout = min(REVIEW_TIMEOUT, seconds_remaining(deadline))
        result = await asyncio.wait_for(
            review_book_illustrations(
                title=title,
                page_texts=page_texts,
                image_prompts={page: prompt.positive_prompt for page, prompt in prompts.items()},
                images=images,
                timeout=timeout,
            ),
            timeout=timeout,
        )
        # Retain an independent completeness fence even if a mocked/changed
        # provider adapter accidentally weakens its output schema.
        pages = result.pages
        if len(pages) != len(expected) or {p.page_number for p in pages} != expected:
            raise quality_failure("page_coverage_invalid")
        findings = {}
        for page in pages:
            issues = [str(getattr(issue, "value", issue)) for issue in page.issues]
            if any(
                issue not in _ISSUE_INSTRUCTIONS and issue not in _BLOCKING_ISSUES
                for issue in issues
            ):
                raise quality_failure("unknown_issue")
            if issues:
                findings[page.page_number] = issues
        return findings

    try:
        if on_progress:
            await on_progress("verify_illustrations", PROGRESS_VERIFY)
        findings = await review()
        if not findings:
            return VerifiedIllustrations(urls, prompts, [], [])
        if len(findings) > repair_limit or any(
            issue in _BLOCKING_ISSUES for issues in findings.values() for issue in issues
        ):
            raise quality_failure("repair_limit_exceeded" if len(findings) > repair_limit else "blocking_issue")
        if repairable_pages is not None and not set(findings).issubset(repairable_pages):
            raise quality_failure("repair_scope_invalid")

        # Reserve the mandatory second review and commit before dividing the
        # remaining time. Edit tasks have a shorter SLA than normal generation;
        # requiring every repair's full configured timeout makes them impossible.
        # A flagged cover remains untrusted even after its one repair until the
        # mandatory whole-book recheck. Do not add a third review or spread its
        # unverified replacement to other pages in this repair batch.
        from src.core.config import settings
        from src.services.image import image_book_reference_scope, supports_image_reference

        cover_passed_review = 0 not in findings
        repair_reserve = REVIEW_TIMEOUT + COMMIT_RESERVE_SECONDS
        if seconds_remaining(deadline, reserve=repair_reserve) < len(findings) * MIN_REPAIR_SECONDS:
            raise quality_failure("repair_deadline_insufficient")
        if on_progress:
            await on_progress("repair_illustrations", PROGRESS_REPAIR)
        for index, page in enumerate(sorted(findings)):
            repair_timeout = min(
                float(settings.image_timeout),
                seconds_remaining(deadline, reserve=repair_reserve) / (len(findings) - index),
            )
            if repair_timeout < MIN_REPAIR_SECONDS:
                raise quality_failure("repair_deadline_insufficient")
            prompt = corrected_prompt(prompts[page], page_texts[page], findings[page])
            reference_urls = dict(urls)
            if page == 0 or not cover_passed_review:
                reference_urls.pop(0, None)
            book_reference = reference_urls.get(0) if supports_image_reference() else None
            with image_correction_scope(
                page_text=page_texts[page], issues=findings[page], source_image_url=urls[page],
            ), image_book_reference_scope(book_reference):
                url = await asyncio.wait_for(
                    regenerate(page, prompt, reference_urls),
                    timeout=repair_timeout,
                )
            key = key_from_public_url(url)
            if not key or not url or "placeholder" in url:
                raise quality_failure("asset_invalid")
            allowed_keys.add(key)
            if url != urls[page]:
                discarded.append(urls[page])
            urls[page] = url
            prompts[page] = prompt
        if on_progress:
            await on_progress("verify_illustrations", PROGRESS_REVERIFY)
        if await review():
            raise quality_failure("recheck_failed")
        return VerifiedIllustrations(urls, prompts, discarded, sorted(findings))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        record_illustration_diagnostic(
            "pipeline", "pipeline_exception", error_code=getattr(exc, "code", None),
        )
        raise quality_failure() from exc
