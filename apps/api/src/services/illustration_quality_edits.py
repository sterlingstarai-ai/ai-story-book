"""Review candidate book edits before an atomic compare-and-swap publication."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
import time
import uuid

from sqlalchemy import select

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.errors import ErrorCode, SafetyError, StoryBookError
from src.core.utils import utcnow
from src.models.db import Book, Job, Page, StoragePurgeTask, StoryDraftDB
from src.models.dto import BookSpec, ImagePrompt, StoryDraft
from src.services.image_request_budget import image_request_budget
from src.services.image_correction import image_correction_scope
from src.services.illustration_policy import max_repair_pages
from src.services.illustration_quality_pipeline import (
    quality_failure,
    queue_discarded_images,
    seconds_remaining,
    verify_and_repair_illustrations,
)
from src.services.purge_queue import cancel_purge_task, enqueue_purge_keys, enqueue_purge_prefix
from src.services.storage import copy_object_to_new_key, key_from_public_url


@dataclass
class BookSnapshot:
    book: dict
    pages: dict[int, dict]
    draft: dict | None

    def urls(self):
        return {
            0: self.book["cover_image_url"],
            **{n: p["image_url"] for n, p in self.pages.items()},
        }

    def texts(self):
        return {0: self.book["title"], **{n: p["text"] for n, p in self.pages.items()}}

    def prompts(self):
        return {
            n: ImagePrompt(
                page=n,
                positive_prompt=(self.pages[n]["image_prompt"] if n else "")
                or f"A {self.book['style']} storybook illustration of {self.texts()[n]}",
                negative_prompt="text, letters, captions, duplicate characters, changed identity",
                seed=1 + uuid.uuid4().int % 2_147_483_646,
                aspect_ratio="3:4",
            )
            for n in self.urls()
        }


async def load_book_snapshot(
    book_id: str, *, job_id: str | None = None, user_key: str | None = None
) -> BookSnapshot:
    async with AsyncSessionLocal() as db:
        book = await db.get(Book, book_id)
        if (
            book is None
            or (job_id is not None and book.job_id != job_id)
            or (user_key is not None and book.user_key != user_key)
        ):
            raise quality_failure()
        rows = list(
            (
                await db.scalars(
                    select(Page).where(Page.book_id == book_id).order_by(Page.page_number)
                )
            ).all()
        )
        draft = await db.scalar(select(StoryDraftDB).where(StoryDraftDB.job_id == book.job_id))
        fields = (
            "id",
            "job_id",
            "title",
            "language",
            "target_age",
            "style",
            "theme",
            "user_key",
            "profile_id",
            "character_id",
            "character_ids",
            "cover_image_url",
        )
        return BookSnapshot(
            {name: getattr(book, name) for name in fields},
            {
                p.page_number: {
                    name: getattr(p, name)
                    for name in ("id", "text", "image_url", "image_prompt", "updated_at")
                }
                for p in rows
            },
            draft.draft if draft is not None else None,
        )


async def _guard(prefix: str, user_key: str) -> int:
    async with AsyncSessionLocal() as db:
        task = enqueue_purge_prefix(
            db, user_key=user_key, reason="unpublished_illustration_edit", prefix=prefix
        )
        await db.commit()
        return task.id


async def _locked_snapshot(db, snapshot: BookSnapshot):
    from src.services.photo_lifecycle import lock_photo_account
    from src.services.photo_book_references import existing_book_is_photo_derived
    from src.core.consent import require_photo_consent

    await lock_photo_account(db, snapshot.book["user_key"])
    book = await db.scalar(select(Book).where(Book.id == snapshot.book["id"]).with_for_update())
    if book is None or any(
        getattr(book, name) != snapshot.book[name]
        for name in ("user_key", "title", "cover_image_url")
    ):
        raise quality_failure()
    if await existing_book_is_photo_derived(db, book):
        await require_photo_consent(db, book.user_key)
    rows = list(
        (await db.scalars(select(Page).where(Page.book_id == book.id).with_for_update())).all()
    )
    current = {p.page_number: p for p in rows}
    if set(current) != set(snapshot.pages):
        raise quality_failure()
    for number, page in current.items():
        before = snapshot.pages[number]
        if any(
            getattr(page, field) != before[field]
            for field in ("id", "text", "image_url", "image_prompt", "updated_at")
        ):
            raise quality_failure()
    return book, current


async def _generate_candidate(
    prompt: ImagePrompt,
    prefix: str,
    deadline: float,
    reference: str | None,
    generated_urls: list[str],
) -> str:
    from src.services.image import generate_image, image_storage_scope

    with image_storage_scope(prefix):
        url = await asyncio.wait_for(
            generate_image(prompt, reference_image_url=reference),
            timeout=min(float(settings.image_timeout), seconds_remaining(deadline)),
        )
    if not key_from_public_url(url) or not url or "placeholder" in url:
        raise quality_failure()
    generated_urls.append(url)
    return url


async def edit_verified_page(
    *,
    job_id: str,
    book_id: str,
    page_number: int,
    mode: str,
    feedback: str | None = None,
    mask_url: str | None = None,
    operation_job_id: str | None = None,
) -> None:
    """Keep the old page visible until the complete candidate book passes review."""
    from src.services.orchestrator import moderate_text_localized
    from src.services.llm import call_text_rewrite

    deadline = time.monotonic() + 140.0
    snapshot = await load_book_snapshot(book_id, job_id=job_id)
    if page_number not in snapshot.pages or mode not in {"text", "image", "both", "inpaint"}:
        raise quality_failure()
    from src.services.photo_book_references import reference_for_existing_book
    from src.services.image import supports_image_reference

    character_reference = await reference_for_existing_book(snapshot.book["job_id"], snapshot.book["user_key"])
    prefix = f"books/{book_id}/edits/{uuid.uuid4().hex}/"
    guard_id = await _guard(prefix, snapshot.book["user_key"])
    generated_urls = []
    texts, urls, prompts = snapshot.texts(), snapshot.urls(), snapshot.prompts()
    revised = None
    with image_request_budget((1 if mode in {"image", "both", "inpaint"} else 0) + 2, deadline):
        if feedback and not await moderate_text_localized(feedback, snapshot.book["language"]):
            raise SafetyError("부적절한 재생성 요청입니다", is_input=True)
        if mode in {"text", "both"}:
            if snapshot.draft is None:
                raise StoryBookError(
                    ErrorCode.LLM_JSON_INVALID,
                    "이 책은 텍스트 재생성을 위한 스토리 원안이 없습니다.",
                )
            spec = BookSpec(
                topic=snapshot.book["title"],
                language=snapshot.book["language"],
                target_age=snapshot.book["target_age"],
                style=snapshot.book["style"],
            )
            draft = StoryDraft.model_validate(snapshot.draft)
            rewritten = await asyncio.wait_for(
                call_text_rewrite(spec, draft, page_number, feedback),
                timeout=min(float(settings.llm_timeout), seconds_remaining(deadline)),
            )
            revised = rewritten.revised_text
            if not revised or not revised.strip():
                raise quality_failure()
            if not await moderate_text_localized(revised, snapshot.book["language"]):
                raise SafetyError("재생성된 내용이 안전 기준을 통과하지 못했습니다", is_input=False)
            texts[page_number] = revised
        if mode == "both":
            from src.services.illustration_quality_pipeline import corrected_prompt

            prompts[page_number] = corrected_prompt(
                prompts[page_number], texts[page_number], ["action_mismatch"]
            )
        if mode == "inpaint":
            if not urls[page_number] or not mask_url:
                raise quality_failure()
            prompts[page_number] = prompts[page_number].model_copy(
                update={
                    "positive_prompt": f"{feedback or ''}. {prompts[page_number].positive_prompt}"[
                        :1200
                    ],
                    "base_image_url": urls[page_number],
                    "mask_url": mask_url,
                }
            )
        if mode in {"image", "both", "inpaint"}:
            correction_scope = (
                image_correction_scope(page_text=texts[page_number], issues=["action_mismatch"])
                if mode == "both"
                else nullcontext()
            )
            with correction_scope:
                urls[page_number] = await _generate_candidate(
                    prompts[page_number],
                    prefix,
                    deadline,
                    character_reference or (urls[0] if supports_image_reference() else None),
                    generated_urls,
                )

        async def repair(number, prompt, current_urls):
            return await _generate_candidate(
                prompt,
                prefix,
                deadline,
                character_reference or (current_urls.get(0) if supports_image_reference() else None),
                generated_urls,
            )

        async def progress(step, percent):
            if operation_job_id:
                from src.services.orchestrator import update_job_status

                await update_job_status(operation_job_id, step, percent)

        verified = await verify_and_repair_illustrations(
            title=snapshot.book["title"],
            page_texts=texts,
            image_prompts=prompts,
            image_urls=urls,
            deadline=deadline,
            regenerate=repair,
            on_progress=progress,
            repairable_pages={page_number},
        )
        seconds_remaining(deadline, reserve=0)
        async with AsyncSessionLocal() as db:
            _, pages = await _locked_snapshot(db, snapshot)
            operation = None
            if operation_job_id:
                operation = await db.scalar(
                    select(Job).where(Job.id == operation_job_id).with_for_update()
                )
                if operation is None or operation.status not in {"queued", "running"}:
                    raise quality_failure()
            page = pages[page_number]
            page.image_url = verified.image_urls[page_number]
            page.image_prompt = verified.image_prompts[page_number].positive_prompt
            if revised is not None:
                enqueue_purge_keys(
                    db, user_key=snapshot.book["user_key"], reason="replaced_page_audio",
                    keys=[key for key in (
                        key_from_public_url(page.audio_url),
                        key_from_public_url(page.audio_url_ko),
                        key_from_public_url(page.audio_url_en),
                    ) if key],
                )
                page.text = revised
                page.text_ko = revised if snapshot.book["language"] == "ko" else None
                page.text_en = revised if snapshot.book["language"] == "en" else None
                page.audio_url = page.audio_url_ko = page.audio_url_en = None
                page.vocab = page.comprehension = page.quiz = None
                stored_draft = await db.scalar(
                    select(StoryDraftDB).where(StoryDraftDB.job_id == job_id)
                )
                if stored_draft is not None:
                    updated = dict(stored_draft.draft)
                    updated["pages"] = [
                        dict(p, text=revised) if p["page"] == page_number else p
                        for p in updated["pages"]
                    ]
                    stored_draft.draft = updated
            page.updated_at = utcnow()
            if operation is not None:
                operation.status, operation.progress, operation.current_step = "done", 100, "done"
                operation.updated_at = utcnow()
            cancel_purge_task(await db.get(StoragePurgeTask, guard_id))
            retained = set(verified.image_urls.values())
            enqueue_purge_keys(
                db,
                user_key=snapshot.book["user_key"],
                reason="rejected_illustration",
                keys=[key_from_public_url(url) for url in generated_urls if url not in retained],
            )
            await db.commit()
        await queue_discarded_images(
            snapshot.book["user_key"],
            [snapshot.pages[page_number]["image_url"]],
            set(verified.image_urls.values()),
        )


async def publish_verified_retell(
    *,
    source_book_id: str,
    user_key: str,
    retold,
    target_age: str,
    idempotency_key: str | None,
) -> str:
    """Validate the new narrative against its images before copying/publishing it."""
    deadline = time.monotonic() + 140.0
    snapshot = await load_book_snapshot(source_book_id, user_key=user_key)
    if len(retold.pages) != len(snapshot.pages):
        raise quality_failure()
    from src.services.photo_book_references import reference_for_existing_book
    from src.services.image import supports_image_reference

    character_reference = await reference_for_existing_book(snapshot.book["job_id"], user_key)
    new_book_id = f"book_{uuid.uuid4().hex[:16]}"
    prefix = f"images/retell/{new_book_id}/"
    guard_id = await _guard(prefix, user_key)
    generated_urls = []
    title = retold.title or snapshot.book["title"]
    texts = {
        0: title,
        **{number: retold.pages[index] for index, number in enumerate(snapshot.pages)},
    }

    async def repair(number, prompt, current_urls):
        return await _generate_candidate(
            prompt,
            prefix,
            deadline,
            character_reference or (current_urls.get(0) if number and supports_image_reference() else None),
            generated_urls,
        )

    with image_request_budget(max_repair_pages(len(snapshot.pages)), deadline):
        verified = await verify_and_repair_illustrations(
            title=title,
            page_texts=texts,
            image_prompts=snapshot.prompts(),
            image_urls=snapshot.urls(),
            deadline=deadline,
            regenerate=repair,
        )
    final_urls = {}
    for number, url in verified.image_urls.items():
        key = key_from_public_url(url)
        if not key:
            raise quality_failure()
        if key.startswith(prefix):
            final_urls[number] = url
        else:
            new_key = f"{prefix}page-{number}-{uuid.uuid4().hex}{'.' + key.rsplit('.', 1)[-1] if '.' in key else '.png'}"
            copied = await asyncio.wait_for(
                copy_object_to_new_key(url, new_key), timeout=min(15, seconds_remaining(deadline))
            )
            if not copied:
                raise quality_failure()
            final_urls[number] = copied
    copied_reference = None
    if character_reference:
        copied_reference = await asyncio.wait_for(
            copy_object_to_new_key(character_reference, f"{prefix}character-reference.png"),
            timeout=min(15, seconds_remaining(deadline)),
        )
        if not copied_reference:
            raise quality_failure()
    async with AsyncSessionLocal() as db:
        current_book, _ = await _locked_snapshot(db, snapshot)
        source_job = await db.get(Job, snapshot.book["job_id"])
        job_id = f"retell_{uuid.uuid4().hex}"
        db.add(
            Job(
                id=job_id,
                status="done",
                progress=100,
                current_step="done",
                user_key=user_key,
                idempotency_key=idempotency_key,
                profile_id=snapshot.book["profile_id"],
                image_keys=[key_from_public_url(url) for url in [*final_urls.values(), *([copied_reference] if copied_reference else [])]],
                photo_derived=bool(copied_reference),
                character_reference_url=copied_reference,
                character_reference_version=source_job.character_reference_version if source_job else None,
            )
        )
        await db.flush()
        db.add(
            Book(
                id=new_book_id,
                job_id=job_id,
                title=title,
                language=snapshot.book["language"],
                target_age=target_age,
                style=snapshot.book["style"],
                theme=snapshot.book["theme"],
                user_key=user_key,
                profile_id=snapshot.book["profile_id"],
                # A reusable character may have been removed during review.
                # Its approved book-owned reference remains valid, while the
                # live relationship (including a detached FK) is authoritative.
                character_id=current_book.character_id,
                character_ids=current_book.character_ids,
                cover_image_url=final_urls[0],
                retelling_source_book_id=source_book_id,
            )
        )
        await db.flush()
        for number in snapshot.pages:
            db.add(
                Page(
                    book_id=new_book_id,
                    page_number=number,
                    text=texts[number],
                    image_url=final_urls[number],
                    image_prompt=verified.image_prompts[number].positive_prompt,
                )
            )
        cancel_purge_task(await db.get(StoragePurgeTask, guard_id))
        enqueue_purge_keys(
            db,
            user_key=user_key,
            reason="rejected_illustration",
            keys=[
                key_from_public_url(url) for url in generated_urls if url not in final_urls.values()
            ],
        )
        await db.commit()
    return new_book_id
