"""Withdrawn page-edit tasks cannot resume after re-grant or publish late output."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import settings
from src.models.db import Job, Page
from src.routers.consent import ConsentGrantRequest, grant_consent, revoke_consent
from src.services import job_runners, purge_queue
from src.services.generation_consent import post_with_consent
from tests.test_celery_dispatch import _seed_book


@pytest.mark.asyncio
@pytest.mark.parametrize("celery", [False, True])
@pytest.mark.parametrize("quality", [False, True])
@pytest.mark.parametrize("kind", ["regen", "inpaint"])
@pytest.mark.parametrize("withdraw_at", ["queued", "before_send", "after_send", "none"])
async def test_page_edit_worker_observes_withdrawal(
    db_session, user_key, monkeypatch, kind, withdraw_at, quality, celery,
):
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    monkeypatch.setattr(purge_queue, "_execute_task", AsyncMock(return_value=[]))
    monkeypatch.setattr(settings, "illustration_quality_enabled", quality)

    async def verified(**kwargs):
        return SimpleNamespace(image_urls=kwargs["image_urls"], image_prompts=kwargs["image_prompts"])
    monkeypatch.setattr("src.services.illustration_quality_edits.verify_and_repair_illustrations", verified)
    await _seed_book(db_session, user_key)
    grant = ConsentGrantRequest(privacy=True, data_processing=True, photos=False)
    await grant_consent(grant, db=db_session, user_key=user_key)
    operation_id = f"{kind}_synthetic"
    db_session.add(Job(id=operation_id, user_key=user_key, status="queued"))
    await db_session.commit()
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    transport = AsyncMock()

    async def withdraw_and_regrant():
        async with sessions() as request:
            await revoke_consent(db=request, user_key=user_key)
            await grant_consent(grant, db=request, user_key=user_key)

    async def image_provider(*args, **kwargs):
        if withdraw_at == "before_send":
            await withdraw_and_regrant()
        await post_with_consent(transport, "https://example.invalid/")
        if withdraw_at == "after_send":
            await withdraw_and_regrant()
        return "http://localhost:9000/storybook/images/mock/new.png"

    monkeypatch.setattr("src.services.image.generate_image", image_provider)
    monkeypatch.setattr("src.services.orchestrator._purge_replaced_image", AsyncMock())
    if withdraw_at == "queued":
        await withdraw_and_regrant()
    from src.services.tasks import inpaint_page_task, regenerate_page_task

    if kind == "regen":
        runner, task = job_runners.run_regeneration_job, regenerate_page_task
        args = (operation_id, "job-dispatch", "book-dispatch", 1, "image", None)
    else:
        runner, task = job_runners.run_inpaint_job, inpaint_page_task
        args = (operation_id, "job-dispatch", "book-dispatch", 1, "http://fixture.invalid/mask", "edit")
    if celery:
        result = await asyncio.to_thread(task.run, *args)
        assert result["status"] == ("success" if withdraw_at == "none" else "skipped")
    else:
        await runner(*args)
    assert transport.post.await_count == (1 if withdraw_at in {"after_send", "none"} else 0)
    async with sessions() as observer:
        page = await observer.scalar(select(Page).where(Page.book_id == "book-dispatch"))
        assert page.image_url.endswith("new.png" if withdraw_at == "none" else "p1.png")
        operation = await observer.get(Job, operation_id)
        if withdraw_at == "none":
            assert operation.status == "done"
        else:
            assert operation is None


@pytest.mark.asyncio
async def test_inpaint_withdrawal_during_mask_upload_keeps_cleanup_guard(
    client, headers, user_key, db_session, monkeypatch,
):
    from src.models.db import StoragePurgeTask
    from src.routers import books

    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    monkeypatch.setattr(settings, "image_provider", "fal")
    monkeypatch.setattr(purge_queue, "_execute_task", AsyncMock(return_value=[]))
    dispatch = AsyncMock()
    monkeypatch.setattr(books, "_dispatch_long_running_job", dispatch)
    await _seed_book(db_session, user_key)
    grant = ConsentGrantRequest(privacy=True, data_processing=True, photos=False)
    await grant_consent(grant, db=db_session, user_key=user_key)
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def upload(_data, key, _mime):
        async with sessions() as request:
            await revoke_consent(db=request, user_key=user_key)
            await grant_consent(grant, db=request, user_key=user_key)
        return f"http://localhost:9000/storybook/{key}"

    monkeypatch.setattr(books.storage_service, "upload_bytes", upload)
    response = await client.post(
        "/v1/books/job-dispatch/pages/1/inpaint",
        headers=headers, files={"mask": ("mask.png", b"test", "image/png")},
        data={"region_prompt": "green forest"},
    )
    assert response.status_code == 403, response.text
    dispatch.assert_not_awaited()
    async with sessions() as observer:
        guard = await observer.scalar(select(StoragePurgeTask).where(
            StoragePurgeTask.reason == "inpaint_mask_upload",
        ))
        assert guard.status == "pending" and guard.target.startswith("masks/book-dispatch/")
