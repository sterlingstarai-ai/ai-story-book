"""Bounded prepublication illustration review and transactional edit support.

The reviewer only receives generated illustrations from authorized book/job
context. Source photographs, arbitrary URLs, and model-written repair prompts
never cross this boundary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import time
from typing import Awaitable, Callable
import uuid

from src.core.errors import ErrorCode, StoryBookError
from src.models.dto import ImagePrompt
from src.services.storage import ObjectReadCache, get_object_bytes, key_from_public_url, object_read_connection_scope
from src.services.image_correction import CORRECTION_INSTRUCTIONS, image_correction_scope
from src.services.illustration_diagnostics import record_illustration_diagnostic
from src.services.illustration_policy import max_repair_pages
from src.services.openai_contract import MAX_REVIEW_IMAGE_BYTES, MAX_REVIEW_TOTAL_IMAGE_BYTES


REVIEW_TIMEOUT = 45.0
COMMIT_RESERVE_SECONDS = 5.0
MIN_REPAIR_SECONDS = 30.0
REVIEW_DOWNLOAD_CONCURRENCY = 3
MAX_PARALLEL_REPAIRS = 2
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


async def enqueue_discarded_images(db, user_key: str, urls: list[str | None], retained_urls: set[str]) -> None:
    """Add cleanup for discarded media to the caller's transaction."""
    from sqlalchemy import select
    from src.models.db import Book, Page
    from src.services.purge_queue import enqueue_purge_keys

    retained_keys = {key_from_public_url(url) for url in retained_urls}
    candidates = {
        url: key for url in set(urls)
        if (key := key_from_public_url(url)) and key not in retained_keys
    }
    if not candidates:
        return
    referenced = await db.scalars(
        select(Page.image_url).where(Page.image_url.in_(candidates)).union(
            select(Book.cover_image_url).where(Book.cover_image_url.in_(candidates))
        )
    )
    referenced_keys = {candidates[url] for url in referenced}
    enqueue_purge_keys(db, user_key=user_key, reason="rejected_illustration",
                       keys=set(candidates.values()) - referenced_keys)


async def queue_discarded_images(user_key: str, urls: list[str], retained_urls: set[str]) -> None:
    """Persist cleanup for rejected images of a new book before packaging."""
    from src.core.database import AsyncSessionLocal

    if not urls:
        return
    async with AsyncSessionLocal() as db:
        await enqueue_discarded_images(db, user_key, urls, retained_urls)
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


async def _load_owned_images(
    image_urls: dict[int, str], allowed_keys: set[str], deadline: float, cache: ObjectReadCache,
):
    keys = {}
    for page, url in image_urls.items():
        key = key_from_public_url(url)
        # The caller's keys come only from this job's generated outputs or an
        # ownership-checked Book/Page snapshot. Never fetch arbitrary URLs.
        if not key or key not in allowed_keys or "placeholder" in url:
            raise quality_failure("asset_invalid")
        keys[page] = key

    for discarded_key in cache.keys() - set(keys.values()):
        del cache[discarded_key]

    slots = asyncio.Semaphore(REVIEW_DOWNLOAD_CONCURRENCY)
    total_bytes = 0

    async def load(key):
        nonlocal total_bytes
        async with slots:
            limit = min(MAX_REVIEW_IMAGE_BYTES, MAX_REVIEW_TOTAL_IMAGE_BYTES - total_bytes)
            if limit <= 0:
                raise quality_failure("asset_invalid")
            data, _stored_mime = await asyncio.wait_for(
                get_object_bytes(key, max_bytes=limit), timeout=min(15.0, seconds_remaining(deadline))
            )
            # Other downloads may have finished while this one was in flight.
            if (not 0 < len(data) <= limit
                    or total_bytes + len(data) > MAX_REVIEW_TOTAL_IMAGE_BYTES):
                raise quality_failure("asset_invalid")
            total_bytes += len(data)
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
        return data, mime

    async with object_read_connection_scope(revalidate=cache):
        images = await _gather_or_cancel(load(key) for key in keys.values())
    return dict(zip(keys, images, strict=True))


async def _gather_or_cancel(awaitables):
    tasks = [asyncio.create_task(awaitable) for awaitable in awaitables]
    try:
        return await asyncio.gather(*tasks)
    finally:
        pending = [task for task in tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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
    repair_concurrency: int = 1,
    use_prompt_action_focus: bool = False,
) -> VerifiedIllustrations:
    """Review and repair only failing pages within one shared request/time budget.

    A regeneration callback receives current candidate URLs, except that page 0
    is omitted when it is the repair target or has not passed the initial review.
    This prevents older cover-primary fallbacks from propagating a flagged cover.
    Use the action focus only when prompts were generated for these exact texts.
    """
    from src.services.image import image_book_reference_scope, supports_image_reference
    from src.services.image_quality import (
        IllustrationActionBasis, illustration_page_action_review_scope, review_book_illustrations,
    )

    urls = dict(image_urls)
    original_prompts = dict(image_prompts)
    prompts = dict(original_prompts)
    expected = set(page_texts)
    repair_limit = max_repair_pages(len(expected) - 1)
    if expected != set(prompts) or expected != set(urls):
        raise quality_failure("page_coverage_invalid")
    allowed_keys = {key for url in urls.values() if (key := key_from_public_url(url))}
    discarded = []
    read_cache: ObjectReadCache = {}
    accepted_page_contexts: dict[int, bytes] = {}

    async def review():
        images = await _load_owned_images(urls, allowed_keys, deadline, read_cache)
        # Keep acceptance local to this operation and these exact bytes/texts.
        # A stable URL is insufficient: storage content or story context may
        # have changed. Every round still loads and reviews the complete book.
        page_contexts = {}
        for page, (data, mime) in images.items():
            digest = hashlib.sha256(json.dumps(
                [title, page_texts[page], prompts[page].positive_prompt, mime],
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            page_contexts[page] = digest.digest()
        action_review_pages = {
            page for page in expected if accepted_page_contexts.get(page) != page_contexts[page]
        }
        timeout = min(REVIEW_TIMEOUT, seconds_remaining(deadline))
        with illustration_page_action_review_scope(action_review_pages):
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
        suppressed_local_actions = []
        for page in pages:
            issues = [str(getattr(issue, "value", issue)) for issue in page.issues]
            if any(
                issue not in _ISSUE_INSTRUCTIONS and issue not in _BLOCKING_ISSUES
                for issue in issues
            ):
                raise quality_failure("unknown_issue")
            if (page.page_number not in action_review_pages
                    and getattr(page, "action_mismatch_basis", None) is IllustrationActionBasis.PAGE_ACTION):
                # Only a newly invented local action finding on an unchanged,
                # accepted page is suppressed. Legacy/unknown basis, global
                # object continuity and every identity/safety/text defect keep
                # the original fail-closed repair/publication behavior.
                if "action_mismatch" in issues:
                    suppressed_local_actions.append(page.page_number)
                issues = [issue for issue in issues if issue != "action_mismatch"]
            if issues:
                findings[page.page_number] = issues
                accepted_page_contexts.pop(page.page_number, None)
            else:
                accepted_page_contexts[page.page_number] = page_contexts[page.page_number]
        if suppressed_local_actions:
            record_illustration_diagnostic(
                "pipeline", "unchanged_local_action", page_numbers=suppressed_local_actions,
            )
        return findings

    async def repair(page, issues, timeout, cover_passed_review):
        prompt = corrected_prompt(original_prompts[page], page_texts[page], issues)
        reference_urls = dict(urls)
        if page == 0 or not cover_passed_review:
            reference_urls.pop(0, None)
        book_reference = reference_urls.get(0) if supports_image_reference() else None
        with image_correction_scope(
            page_text=page_texts[page], issues=issues, source_image_url=urls[page],
            previous_page_text=page_texts.get(page - 1, "") if page > 1 else "",
            next_page_text=page_texts.get(page + 1, "") if page > 0 else "",
            use_prompt_action_focus=use_prompt_action_focus and page != 0,
            review_repair=True,
        ), image_book_reference_scope(book_reference):
            url = await asyncio.wait_for(regenerate(page, prompt, reference_urls), timeout=timeout)
        key = key_from_public_url(url)
        if not key or "placeholder" in url:
            raise quality_failure("asset_invalid")
        return page, prompt, url, key

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

        from src.core.config import settings
        from src.services.image_request_budget import remaining_image_requests

        repair_reserve = REVIEW_TIMEOUT + COMMIT_RESERVE_SECONDS
        attempts_used = 0
        repaired_pages: set[int] = set()
        repair_issues: dict[int, list[str]] = {}
        while findings:
            # The allowance counts attempts, not distinct pages. A page that
            # still fails may use the remaining allowance; neither retries nor
            # a second pass can reset the book-wide paid request ceiling.
            remaining_attempts = min(repair_limit - attempts_used, remaining_image_requests(repair_limit))
            if len(findings) > remaining_attempts:
                raise quality_failure("recheck_failed")
            if any(issue in _BLOCKING_ISSUES for issues in findings.values() for issue in issues):
                raise quality_failure("blocking_issue")
            if repairable_pages is not None and not set(findings).issubset(repairable_pages):
                raise quality_failure("repair_scope_invalid")
            # A new defect on a repaired page must not undo an earlier fix.
            for page, issues in findings.items():
                repair_issues[page] = list(dict.fromkeys([*repair_issues.get(page, ()), *issues]))
            cover_passed_review = 0 not in findings
            # Only parallelize when the existing cover is approved. A rejected
            # cover must never become a sibling repair's reference mid-round.
            pages = sorted(findings)
            slots = max(1, min(repair_concurrency, MAX_PARALLEL_REPAIRS)) if cover_passed_review else 1

            def timeout_for(queued_pages):
                waves = (queued_pages + slots - 1) // slots
                timeout = min(float(settings.image_timeout),
                              seconds_remaining(deadline, reserve=repair_reserve) / waves)
                if timeout < MIN_REPAIR_SECONDS:
                    raise quality_failure("repair_deadline_insufficient")
                return timeout

            timeout_for(len(pages))  # Reject a round that cannot fit before starting any paid work.
            if on_progress:
                await on_progress("repair_illustrations", PROGRESS_REPAIR + 2 * attempts_used)

            active = {}
            index = 0
            try:
                while index < len(pages) or active:
                    if index < len(pages) and len(active) < slots:
                        timeout = timeout_for(len(pages) - index)
                        queued = pages[index:index + slots - len(active)]
                        for page in queued:
                            task = asyncio.create_task(repair(page, repair_issues[page], timeout, cover_passed_review))
                            active[task] = page
                        index += len(queued)
                        attempts_used += len(queued)

                    await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                    # Observe every completed task before paying for another repair.
                    finished = sorted((task for task in active if task.done()), key=active.__getitem__)
                    for task in finished:
                        page, prompt, url, key = task.result()
                        allowed_keys.add(key)
                        if url != urls[page]:
                            discarded.append(urls[page])
                        urls[page] = url
                        prompts[page] = prompt
                        repaired_pages.add(page)
                        del active[task]
            finally:
                for task in active:
                    task.cancel()
                if active:
                    await asyncio.gather(*active, return_exceptions=True)
            if on_progress:
                # Three repair slots fit before the learning-assets step at 92%.
                await on_progress("verify_illustrations", PROGRESS_REVERIFY + 2 * (attempts_used - 1))
            # Every accepted result has a complete final review. A previously
            # rejected cover may anchor later repairs only after passing here.
            findings = await review()
        return VerifiedIllustrations(urls, prompts, discarded, sorted(repaired_pages))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if isinstance(exc, StoryBookError) and exc.code == ErrorCode.AI_PROVIDER_UNAVAILABLE:
            raise
        record_illustration_diagnostic(
            "pipeline", "pipeline_exception", error_code=getattr(exc, "code", None),
        )
        raise quality_failure() from exc
