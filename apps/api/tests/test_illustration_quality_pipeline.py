"""Quality decisions must precede publication and preserve old pages on failure."""

import asyncio
from datetime import datetime
from datetime import timedelta
from io import BytesIO
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.core.errors import ErrorCode, StoryBookError, is_retryable
from src.models.db import Book, Job, Page, StoragePurgeTask, UserCredits
from src.models.dto import ImagePrompt, RetoldStory
from src.services import image_quality, illustration_quality_pipeline as pipeline
from src.services.image_quality import BookIllustrationReview
from src.services.storage import canonical_media_url


def _review(count=5, failures=None):
    failures = failures or {}
    return BookIllustrationReview(
        pages=[{"page_number": n, "issues": failures.get(n, [])} for n in range(count)]
    )


def _inputs(count=5):
    return dict(
        title="그림책",
        page_texts={n: f"이야기 {n}" for n in range(count)},
        image_prompts={
            n: ImagePrompt(
                page=n,
                positive_prompt=f"A small rabbit in the garden, scene {n}",
                negative_prompt="text, letters, duplicate rabbits",
                seed=10 + n,
            )
            for n in range(count)
        },
        image_urls={n: canonical_media_url(f"jobs/q/page-{n}.png") for n in range(count)},
        deadline=time.monotonic() + 500,
    )


@pytest.fixture
def review_bytes(monkeypatch):
    from src.services.image import _mock_png_bytes

    loader = AsyncMock(return_value=(_mock_png_bytes(1), "image/png"))
    monkeypatch.setattr(pipeline, "get_object_bytes", loader)
    return loader


@pytest.mark.asyncio
async def test_account_deletion_sweeps_uploads_that_finish_after_job_rows_are_gone(
    client, db_session, monkeypatch, user_key, headers
):
    from src.core.utils import utcnow
    from src.services import purge_queue, storage

    db_session.add(Job(id="upload-inflight", user_key=user_key, status="running", image_keys=[]))
    await db_session.commit()
    objects = set()
    deleted_prefixes = []

    async def delete_prefix(prefix):
        deleted_prefixes.append(prefix)
        objects.difference_update(key for key in list(objects) if key.startswith(prefix))
        return []

    monkeypatch.setattr(storage.storage_service, "delete_prefix", delete_prefix)
    monkeypatch.setattr(storage, "delete_keys", AsyncMock(return_value=[]))
    response = await client.delete("/v1/users/me", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["purge_retry_pending"] is True
    assert await db_session.get(Job, "upload-inflight") is None
    guard = await db_session.scalar(
        select(StoragePurgeTask).where(
            StoragePurgeTask.reason == "account_deletion_inflight_images"
        )
    )
    assert guard.target == "jobs/upload-inflight/"
    assert guard.status == "pending" and guard.attempts == 0
    assert deleted_prefixes.count(guard.target) == 1
    # This upload was already in flight when account deletion removed the Job.
    late_key = "jobs/upload-inflight/gemini/late.png"
    objects.add(late_key)
    assert await purge_queue.sweep_pending_purges() == 0
    assert late_key in objects
    guard.created_at = utcnow() - timedelta(seconds=purge_queue.UNATTEMPTED_GRACE_SECONDS + 1)
    await db_session.commit()
    assert await purge_queue.sweep_pending_purges() == 1
    assert late_key not in objects


@pytest.mark.asyncio
async def test_all_pages_pass_without_extra_generation(monkeypatch, review_bytes):
    reviewer = AsyncMock(return_value=_review())
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    generate = AsyncMock()
    inputs = _inputs()
    result = await pipeline.verify_and_repair_illustrations(**inputs, regenerate=generate)
    assert result.image_urls == inputs["image_urls"]
    generate.assert_not_awaited()
    assert reviewer.await_count == 1
    assert all(isinstance(v[0], bytes) for v in reviewer.call_args.kwargs["images"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_prompts", [True, False])
async def test_action_repair_only_reuses_focus_for_the_original_story(
    monkeypatch, review_bytes, fresh_prompts,
):
    from src.services.image_correction import provider_prompt_with_correction

    inputs = _inputs()
    action = "Dari, the green-shirted squirrel, picks up the napkin while Haru watches."
    narrative = "다리가 냅킨을 주웠어요." if fresh_prompts else "이번에는 하루가 냅킨을 주웠어요."
    inputs["page_texts"][3] = narrative
    original = inputs["image_prompts"][3].model_copy(update={
        "positive_prompt": f"ACTION FOCUS: {action}\nVisible cast: 2. Wide forest view.",
        "guidance_notes": "CAST LOOKS: Dari = squirrel, green shirt; Haru = white rabbit",
    })
    inputs["image_prompts"][3] = original
    reviewer = AsyncMock(side_effect=[_review(failures={3: ["action_mismatch"]}), _review()])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)

    async def repair(page, prompt, _urls):
        assert page == 3
        wire = provider_prompt_with_correction(prompt, use_cast_looks=True).positive_prompt
        assert wire.startswith(f"CURRENT PAGE NARRATIVE: {narrative}\n")
        assert (action in wire) is fresh_prompts
        assert "Wide forest view" not in wire
        assert original.guidance_notes in wire
        if fresh_prompts:
            assert f"ACTION FOCUS (only if supported by the current narrative): {action}" in wire
        return canonical_media_url("jobs/q/new-3.png")

    flags = {"use_prompt_action_focus": True} if fresh_prompts else {}
    result = await pipeline.verify_and_repair_illustrations(**inputs, regenerate=repair, **flags)
    assert result.image_prompts[3].positive_prompt == original.positive_prompt
    assert reviewer.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cover_flagged", [True, False])
async def test_action_repair_keeps_the_supporting_cast_details_without_the_old_staging(
    monkeypatch, review_bytes, cover_flagged,
):
    from src.services.image_correction import provider_prompt_with_correction

    inputs = _inputs()
    details = "Haru = white rabbit, red scarf; Keeper = adult gray badger, navy cap, orange jacket"
    wrong_staging = "Both characters hold the same green litter tongs."
    brief = "ACTION FOCUS: Haru picks up the can with tongs while Keeper watches."
    inputs["image_prompts"][3] = inputs["image_prompts"][3].model_copy(update={
        "positive_prompt": f"{brief}\nCAST DETAILS: {details}\n{wrong_staging}",
        "guidance_notes": "CAST LOOKS: Haru = white rabbit; Keeper = gray badger",
    })
    failures = {3: ["action_mismatch"]}
    if cover_flagged:
        failures[0] = ["readable_text"]
    reviewer = AsyncMock(side_effect=[_review(failures=failures), _review()])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)

    async def repair(page, prompt, urls):
        if page == 3:
            wire = provider_prompt_with_correction(prompt, use_cast_looks=0 in urls).positive_prompt
            assert f"CAST DETAILS (fixed appearance of current cast only): {details}" in wire
            assert wrong_staging not in wire
            assert len(wire) <= 3000
        return canonical_media_url(f"jobs/q/new-{page}.png")

    result = await pipeline.verify_and_repair_illustrations(**inputs, regenerate=repair, use_prompt_action_focus=True)
    assert 3 in result.repaired_pages
    assert result.image_prompts[3].positive_prompt == inputs["image_prompts"][3].positive_prompt


@pytest.mark.asyncio
async def test_full_recheck_reads_current_bytes_using_one_storage_client_per_round(monkeypatch):
    from src.services import storage

    clients = []
    images = {f"jobs/q/page-{page}.png": b"\x89PNG\r\n\x1a\n" + bytes([page]) for page in range(13)}

    class ReadClient:
        def __init__(self):
            self.keys = []
            self.bodies = []
            self.closed = False

        def get_object(self, *, Bucket, Key):
            assert not self.closed
            self.keys.append(Key)
            body = BytesIO(images[Key])
            self.bodies.append(body)
            return {"Body": body}

        def close(self):
            assert all(body.closed for body in self.bodies)
            self.closed = True

    def make_client():
        client = ReadClient()
        clients.append(client)
        return client

    async def repair(page, _prompt, _urls):
        assert page == 3
        # Simulate a changed sibling in storage. The final review has to see
        # its current bytes in addition to the explicitly repaired page.
        images["jobs/q/page-4.png"] = b"\x89PNG\r\n\x1a\nchanged sibling"
        images["jobs/q/new-3.png"] = b"\x89PNG\r\n\x1a\nrepaired"
        return canonical_media_url("jobs/q/new-3.png")

    monkeypatch.setattr(storage, "get_s3_client", make_client)
    reviewer = AsyncMock(side_effect=[_review(13, {3: ["action_mismatch"]}), _review(13)])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)

    result = await pipeline.verify_and_repair_illustrations(**_inputs(13), regenerate=repair)
    assert result.repaired_pages == [3]
    assert len(clients) == 2
    assert all(client.closed and len(client.keys) == 13 for client in clients)
    assert "jobs/q/page-3.png" in clients[0].keys
    assert "jobs/q/page-3.png" not in clients[1].keys
    first, final = [call.kwargs["images"] for call in reviewer.await_args_list]
    assert first[4][0] != final[4][0] == images["jobs/q/page-4.png"]
    assert final[3][0] == images["jobs/q/new-3.png"]


@pytest.mark.asyncio
async def test_only_bad_pages_repaired_once_and_entire_book_rechecked(monkeypatch, review_bytes):
    from src.services import image
    reviewer = AsyncMock(
        side_effect=[_review(failures={0: ["readable_text"], 3: ["identity_swap"]}), _review()]
    )
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    calls = []
    completed = []

    async def generate(page, prompt, current):
        from src.services.image_correction import provider_prompt_with_correction

        if page != 0:
            assert completed == [0]
        calls.append((page, provider_prompt_with_correction(prompt), current, image._book_reference_url.get()))
        await asyncio.sleep(0)
        completed.append(page)
        return canonical_media_url(f"jobs/q/repaired-{page}.png")

    original = _inputs()
    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        result = await pipeline.verify_and_repair_illustrations(**original, regenerate=generate, repair_concurrency=4)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert [call[0] for call in calls] == [0, 3]
    # Repairing the flagged cover first is not evidence it is now correct.
    # Hide both old/new cover fallbacks until the final whole-book recheck.
    assert all(0 not in call[2] and call[3] is None for call in calls)
    assert result.image_urls[0] == canonical_media_url("jobs/q/repaired-0.png")
    assert len(reviewer.call_args.kwargs["images"]) == 5
    assert result.image_urls[2] == original["image_urls"][2]
    assert "Remove all readable text" in calls[0][1].positive_prompt
    assert result.image_prompts[0].positive_prompt == original["image_prompts"][0].positive_prompt
    assert original["image_prompts"][0].seed == 10
    assert result.repaired_pages == [0, 3]


@pytest.mark.asyncio
async def test_page_repairs_use_only_the_current_cover_that_passed_full_review(monkeypatch, review_bytes):
    from src.services import image
    from src.services.image_correction import correction_scene_reference, provider_prompt_with_correction

    original = _inputs()
    reviewer = AsyncMock(side_effect=[_review(failures={1: ["action_mismatch"], 3: ["readable_text"]}), _review()])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    seen = []

    async def generate(page, prompt, current):
        await asyncio.sleep(0)
        repair_text = provider_prompt_with_correction(prompt).positive_prompt
        if page == 1:
            assert f'Next page: {original["page_texts"][2]}' in repair_text
            assert "Previous page:" not in repair_text  # Cover title is not adjacent prose.
        else:
            assert "NEIGHBORING PAGES" not in repair_text
        seen.append((page, image._book_reference_url.get(), correction_scene_reference(), current.get(0)))
        return canonical_media_url(f"jobs/q/repaired-{page}.png")

    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        result = await pipeline.verify_and_repair_illustrations(**original, regenerate=generate)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert seen == [(page, original["image_urls"][0], None if page == 1 else original["image_urls"][page], original["image_urls"][0])
                    for page in (1, 3)]
    assert result.repaired_pages == [1, 3]
    assert reviewer.await_count == 2
    assert image._book_reference_url.get() is None


@pytest.mark.asyncio
async def test_new_book_repairs_at_most_two_at_once_and_reviews_all_pages(monkeypatch, review_bytes):
    from src.services.image_request_budget import consume_image_request, image_request_budget

    inputs = _inputs(13)
    failed_pages = [1, 4, 8]
    reviewer = AsyncMock(side_effect=[_review(13, dict.fromkeys(failed_pages, ["readable_text"])), _review(13)])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    pair_started = asyncio.Event()
    third_started = asyncio.Event()
    active = set()
    finished = set()

    async def repair(page, _prompt, current):
        consume_image_request()
        assert current[0] == inputs["image_urls"][0]
        assert current[page] == inputs["image_urls"][page]
        active.add(page)
        assert len(active) <= 2
        try:
            if page == failed_pages[-1]:
                assert finished == {failed_pages[0]}
                assert failed_pages[1] in active
                third_started.set()
            else:
                if len(active) == 2:
                    pair_started.set()
                await pair_started.wait()
                if page == failed_pages[1]:
                    await third_started.wait()
            finished.add(page)
            return canonical_media_url(f"jobs/q/parallel-repaired-{page}.png")
        finally:
            active.remove(page)

    with image_request_budget(16, inputs["deadline"]) as budget:
        for _ in range(13):
            consume_image_request()
        result = await asyncio.wait_for(pipeline.verify_and_repair_illustrations(
            **inputs, regenerate=repair, repair_concurrency=4,
        ), timeout=2)

    assert result.repaired_pages == failed_pages and budget.used == 16
    assert not active and reviewer.await_count == 2
    assert list(reviewer.call_args.kwargs["images"]) == list(range(13))


@pytest.mark.asyncio
@pytest.mark.parametrize("slots", [1, 2])
async def test_repair_deadline_accounts_for_parallel_slots(monkeypatch, review_bytes, slots):
    inputs = _inputs(13)
    inputs["deadline"] = time.monotonic() + 100
    reviewer = AsyncMock(side_effect=[_review(13, {1: ["readable_text"], 4: ["readable_text"]}), _review(13)])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    repair = AsyncMock(side_effect=lambda page, *_: canonical_media_url(f"jobs/q/repair-{page}.png"))
    if slots == 1:
        with pytest.raises(StoryBookError):
            await pipeline.verify_and_repair_illustrations(**inputs, regenerate=repair, repair_concurrency=slots)
        repair.assert_not_awaited()
        assert reviewer.await_count == 1
    else:
        result = await pipeline.verify_and_repair_illustrations(**inputs, regenerate=repair, repair_concurrency=slots)
        assert result.repaired_pages == [1, 4]
        assert repair.await_count == reviewer.await_count == 2
        assert list(reviewer.call_args.kwargs["images"]) == list(range(13))


@pytest.mark.asyncio
async def test_failed_parallel_repair_cancels_sibling_without_another_batch(monkeypatch, review_bytes):
    failures = {page: ["readable_text"] for page in (1, 2, 3)}
    reviewer = AsyncMock(return_value=_review(13, failures))
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    sibling_started = asyncio.Event()
    sibling_stopped = asyncio.Event()
    attempted = []

    async def repair(page, _prompt, _current):
        attempted.append(page)
        if page == 1:
            await sibling_started.wait()
            raise StoryBookError(ErrorCode.AI_PROVIDER_UNAVAILABLE, "inert failure")
        sibling_started.set()
        try:
            await asyncio.Future()
        finally:
            sibling_stopped.set()

    with pytest.raises(StoryBookError) as raised:
        await asyncio.wait_for(pipeline.verify_and_repair_illustrations(
            **_inputs(13), regenerate=repair, repair_concurrency=2,
        ), timeout=2)
    assert raised.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert attempted == [1, 2] and sibling_stopped.is_set()
    assert reviewer.await_count == 1


@pytest.mark.asyncio
async def test_repair_does_not_add_a_reference_to_an_unsupported_provider(monkeypatch, review_bytes):
    from src.services import image

    monkeypatch.setattr(settings, "image_provider", "replicate")
    reviewer = AsyncMock(side_effect=[_review(failures={1: ["action_mismatch"]}), _review()])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)

    async def generate(page, _prompt, _current):
        assert image._book_reference_url.get() is None
        return canonical_media_url(f"jobs/q/repaired-{page}.png")

    result = await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=generate)
    assert result.repaired_pages == [1]
    assert reviewer.await_count == 2


@pytest.mark.asyncio
async def test_repair_failure_does_not_leak_another_books_cover_scope(monkeypatch, review_bytes):
    from src.services import image

    original = _inputs()
    reviewer = AsyncMock(return_value=_review(failures={1: ["action_mismatch"]}))
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)

    async def fail(*args):
        assert image._book_reference_url.get() == original["image_urls"][0]
        raise RuntimeError("repair failed")

    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        with pytest.raises(StoryBookError):
            await pipeline.verify_and_repair_illustrations(**original, regenerate=fail)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert reviewer.await_count == 1
    assert image._book_reference_url.get() is None


@pytest.mark.asyncio
async def test_twelve_page_book_repairs_three_once_then_rechecks_all_thirteen(monkeypatch, review_bytes):
    failures = {0: ["action_mismatch"], 5: ["action_mismatch"], 7: ["action_mismatch"]}
    reviewer = AsyncMock(side_effect=[_review(13, failures), _review(13)])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    original = _inputs(13)
    repairs = []

    async def generate(number, _prompt, _current):
        repairs.append(number)
        return canonical_media_url(f"jobs/q/repair-{number}.png")

    result = await pipeline.verify_and_repair_illustrations(**original, regenerate=generate)
    assert repairs == [0, 5, 7] and result.repaired_pages == [0, 5, 7]
    assert reviewer.await_count == 2
    assert all(len(call.kwargs["images"]) == 13 for call in reviewer.await_args_list)
    assert len(result.discarded_urls) == 3
    for number in set(range(13)) - set(repairs):
        assert result.image_urls[number] == original["image_urls"][number]


@pytest.mark.asyncio
@pytest.mark.parametrize("count,failures", [
    (5, {0: ["action_mismatch"], 1: ["action_mismatch"], 2: ["action_mismatch"]}),
    (9, {0: ["action_mismatch"], 1: ["action_mismatch"], 2: ["action_mismatch"]}),
    (13, {n: ["action_mismatch"] for n in range(4)}),
    (13, {7: ["uncertain"]}), (13, {7: ["unsafe_depiction"]}),
])
async def test_page_specific_repair_limit_never_weakens_issue_blocking(monkeypatch, review_bytes, count, failures):
    reviewer = AsyncMock(return_value=_review(count, failures))
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    generate = AsyncMock()
    with pytest.raises(StoryBookError) as caught:
        await pipeline.verify_and_repair_illustrations(**_inputs(count), regenerate=generate)
    assert caught.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    assert reviewer.await_count == 1
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_three_page_repair_still_fails_before_cost_when_original_deadline_is_short(monkeypatch, review_bytes):
    monkeypatch.setattr(image_quality, "review_book_illustrations",
                        AsyncMock(return_value=_review(13, {n: ["action_mismatch"] for n in (0, 5, 7)})))
    data = _inputs(13)
    data["deadline"] = time.monotonic() + 139
    generate = AsyncMock()
    with pytest.raises(StoryBookError):
        await pipeline.verify_and_repair_illustrations(**data, regenerate=generate)
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_three_repairs_cannot_start_another_cycle_when_recheck_fails(monkeypatch, review_bytes):
    reviewer = AsyncMock(side_effect=[_review(13, {n: ["action_mismatch"] for n in (0, 5, 7)}),
                                     _review(13, {7: ["action_mismatch"]})])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    generate = AsyncMock(side_effect=lambda number, *_: canonical_media_url(f"jobs/q/repair-{number}.png"))
    with pytest.raises(StoryBookError):
        await pipeline.verify_and_repair_illustrations(**_inputs(13), regenerate=generate)
    assert reviewer.await_count == 2 and generate.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failures",
    [
        {1: ["uncertain"]},
        {2: ["unsafe_depiction"]},
        {1: ["action_mismatch"], 2: ["action_mismatch"], 3: ["readable_text"]},
    ],
)
async def test_blocking_or_excessive_findings_never_generate(monkeypatch, review_bytes, failures):
    from src.services import illustration_diagnostics

    events = []
    monkeypatch.setattr(illustration_diagnostics, "logger", SimpleNamespace(
        warning=lambda event, **fields: events.append(fields),
    ))
    monkeypatch.setattr(
        image_quality,
        "review_book_illustrations",
        AsyncMock(return_value=_review(failures=failures)),
    )
    generate = AsyncMock()
    with pytest.raises(StoryBookError) as exc:
        await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=generate)
    assert exc.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    assert not is_retryable(exc.value)
    generate.assert_not_awaited()
    assert events[0]["quality_reason"] == ("repair_limit_exceeded" if len(failures) > 2 else "blocking_issue")
    assert events[0]["quality_error_code"] == "IMAGE_QUALITY_FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_review",
    [asyncio.TimeoutError(), ValueError("malformed response"), SimpleNamespace(pages=[])],
)
async def test_review_failure_or_missing_page_is_never_a_pass(
    monkeypatch, review_bytes, bad_review
):
    fake = (
        AsyncMock(side_effect=bad_review)
        if isinstance(bad_review, Exception)
        else AsyncMock(return_value=bad_review)
    )
    monkeypatch.setattr(image_quality, "review_book_illustrations", fake)
    with pytest.raises(StoryBookError, match="IMAGE_QUALITY_FAILED"):
        await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=AsyncMock())


@pytest.mark.asyncio
async def test_failed_recheck_uses_remaining_allowance_then_stops(monkeypatch, review_bytes):
    reviewer = AsyncMock(return_value=_review(failures={2: ["action_mismatch"]}))
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    generate = AsyncMock(return_value=canonical_media_url("jobs/q/fix.png"))
    with pytest.raises(StoryBookError):
        await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=generate)
    assert reviewer.await_count == 3
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_not_enough_time_to_repair_preserves_deadline(monkeypatch, review_bytes):
    from src.services import illustration_diagnostics

    events = []
    monkeypatch.setattr(illustration_diagnostics, "logger", SimpleNamespace(
        warning=lambda event, **fields: events.append(fields),
    ))
    monkeypatch.setattr(
        image_quality,
        "review_book_illustrations",
        AsyncMock(return_value=_review(failures={2: ["action_mismatch"]})),
    )
    generate = AsyncMock()
    inputs = _inputs()
    inputs["deadline"] = time.monotonic() + 50
    with pytest.raises(StoryBookError):
        await pipeline.verify_and_repair_illustrations(**inputs, regenerate=generate)
    assert events[0]["quality_reason"] in {"deadline_exhausted", "repair_deadline_insufficient"}
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_pipeline_exception_logs_no_private_prose(monkeypatch, review_bytes):
    from src.core.logging import redact_log_data
    from src.services import illustration_diagnostics

    secret = "private-provider-payload-and-child-name"
    events = []
    monkeypatch.setattr(illustration_diagnostics, "logger", SimpleNamespace(
        warning=lambda event, **fields: events.append(redact_log_data(None, "warning", {"event": event, **fields})),
    ))
    monkeypatch.setattr(image_quality, "review_book_illustrations", AsyncMock(side_effect=ValueError(secret)))
    with pytest.raises(StoryBookError) as caught:
        await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=AsyncMock())
    assert caught.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    assert events == [{"event": "Illustration quality diagnostic", "quality_stage": "pipeline",
                       "quality_reason": "pipeline_exception"}]
    assert secret not in str(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_pages", [[1], [1, 3]])
async def test_edit_deadline_allows_repairs_with_shorter_per_call_timeouts(
    monkeypatch, review_bytes, failed_pages
):
    monkeypatch.setattr(settings, "image_timeout", 90)
    reviewer = AsyncMock(
        side_effect=[_review(failures={p: ["action_mismatch"] for p in failed_pages}), _review()]
    )
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    generate = AsyncMock(side_effect=lambda page, *_: canonical_media_url(f"jobs/q/new-{page}.png"))
    inputs = _inputs()
    inputs["deadline"] = time.monotonic() + 140
    result = await pipeline.verify_and_repair_illustrations(**inputs, regenerate=generate)
    assert result.repaired_pages == failed_pages
    assert generate.await_count == len(failed_pages)
    assert reviewer.await_count == 2


@pytest.mark.asyncio
async def test_two_repairs_require_minimum_time_for_each(monkeypatch, review_bytes):
    monkeypatch.setattr(
        image_quality,
        "review_book_illustrations",
        AsyncMock(return_value=_review(failures={1: ["readable_text"], 3: ["identity_swap"]})),
    )
    generate = AsyncMock()
    inputs = _inputs()
    inputs["deadline"] = time.monotonic() + 100
    with pytest.raises(StoryBookError):
        await pipeline.verify_and_repair_illustrations(**inputs, regenerate=generate)
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_url_not_fetched_or_reviewed(monkeypatch, review_bytes):
    review = AsyncMock()
    monkeypatch.setattr(image_quality, "review_book_illustrations", review)
    inputs = _inputs()
    inputs["image_urls"][4] = "http://127.0.0.1/private-photo.png"
    with pytest.raises(StoryBookError):
        await pipeline.verify_and_repair_illustrations(**inputs, regenerate=AsyncMock())
    review.assert_not_awaited()
    review_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_downloads_overlap_and_preserve_page_order(monkeypatch):
    inputs = _inputs()
    reached_limit = asyncio.Event()
    release = asyncio.Event()
    active = peak = 0

    async def download(key, *, max_bytes):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == pipeline.REVIEW_DOWNLOAD_CONCURRENCY:
            reached_limit.set()
        try:
            await release.wait()
            return b"\x89PNG\r\n\x1a\n" + key.encode(), "unused"
        finally:
            active -= 1

    monkeypatch.setattr(pipeline, "get_object_bytes", download)
    reviewer = AsyncMock(return_value=_review())
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    task = asyncio.create_task(
        pipeline.verify_and_repair_illustrations(**inputs, regenerate=AsyncMock())
    )
    try:
        await asyncio.wait_for(reached_limit.wait(), timeout=2)
    finally:
        release.set()
        await task
    images = reviewer.call_args.kwargs["images"]
    assert peak == pipeline.REVIEW_DOWNLOAD_CONCURRENCY
    assert active == 0
    assert list(images) == list(range(5))
    assert all(data.endswith(f"page-{page}.png".encode()) for page, (data, _) in images.items())


@pytest.mark.asyncio
async def test_review_downloads_stop_before_reviewer_when_aggregate_bytes_exceed_limit(monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_REVIEW_IMAGE_BYTES", 20)
    monkeypatch.setattr(pipeline, "MAX_REVIEW_TOTAL_IMAGE_BYTES", 34)
    downloads = []
    all_slots_started = asyncio.Event()

    async def download(key, *, max_bytes):
        downloads.append(max_bytes)
        if len(downloads) == pipeline.REVIEW_DOWNLOAD_CONCURRENCY:
            all_slots_started.set()
        await asyncio.wait_for(all_slots_started.wait(), timeout=2)
        return b"\x89PNG\r\n\x1a\n" + b"x" * 9, "image/png"

    monkeypatch.setattr(pipeline, "get_object_bytes", download)
    reviewer = AsyncMock(return_value=_review())
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    with pytest.raises(StoryBookError) as exc:
        await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=AsyncMock())
    assert exc.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    first_wave = pipeline.REVIEW_DOWNLOAD_CONCURRENCY
    assert downloads[:first_wave] == [20] * first_wave
    # One queued read can start as a slot frees, but it gets only the
    # remaining budget. The last image never needs to be fetched.
    assert downloads[first_wave:] in ([], [17])
    reviewer.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_review_download_cancels_pending_reads(monkeypatch):
    active = set()
    reached_limit = asyncio.Event()

    async def download(key, *, max_bytes):
        active.add(key)
        if len(active) == pipeline.REVIEW_DOWNLOAD_CONCURRENCY:
            reached_limit.set()
        try:
            if key.endswith("page-0.png"):
                await reached_limit.wait()
                raise OSError("inert storage failure")
            await asyncio.Future()
        finally:
            active.remove(key)

    monkeypatch.setattr(pipeline, "get_object_bytes", download)
    reviewer = AsyncMock()
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    with pytest.raises(StoryBookError):
        await asyncio.wait_for(
            pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=AsyncMock()),
            timeout=2,
        )
    assert not active
    reviewer.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_http_budget_shared_across_parallel_image_calls(monkeypatch):
    import httpx
    from src.services import image
    from src.services.image_request_budget import image_request_budget

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={})

    monkeypatch.setattr(settings, "image_provider", "gemini")
    monkeypatch.setattr(settings, "image_api_key", "dummy-not-real")

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=client_factory))
    with image_request_budget(2, time.monotonic() + 10) as budget:
        results = await asyncio.gather(
            *(image.generate_image(_inputs()["image_prompts"][1]) for _ in range(5)),
            return_exceptions=True,
        )
    assert len(calls) == budget.used == 2
    assert (
        sum(
            isinstance(result, StoryBookError) and result.code == ErrorCode.IMAGE_QUALITY_FAILED
            for result in results
        )
        == 3
    )


async def _seed_book(db):
    db.add(Job(id="source-job", user_key="owner", status="done"))
    await db.flush()
    db.add(
        Book(
            id="source",
            job_id="source-job",
            title="원본 이야기",
            user_key="owner",
            language="ko",
            target_age="5-7",
            style="watercolor",
            cover_image_url=canonical_media_url("jobs/source/cover.png"),
        )
    )
    await db.flush()
    for number in range(1, 5):
        db.add(
            Page(
                book_id="source",
                page_number=number,
                text=f"원문 {number}",
                image_url=canonical_media_url(f"jobs/source/p{number}.png"),
                image_prompt="A rabbit waters a small tree",
                updated_at=datetime(2026, 9, 6),
            )
        )
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["image", "inpaint"])
async def test_failed_manual_edit_keeps_original_and_guard_only_targets_new_assets(
    db_session, monkeypatch, review_bytes, mode
):
    from src.services.illustration_quality_edits import edit_verified_page
    from src.services import image

    await _seed_book(db_session)
    monkeypatch.setattr(
        image_quality,
        "review_book_illustrations",
        AsyncMock(return_value=_review(failures={1: ["uncertain"]})),
    )
    generated = canonical_media_url("books/source/edits/new.png")
    monkeypatch.setattr(image, "generate_image", AsyncMock(return_value=generated))
    with pytest.raises(StoryBookError):
        await edit_verified_page(
            job_id="source-job",
            book_id="source",
            page_number=1,
            mode=mode,
            feedback="작은 꽃",
            mask_url=canonical_media_url("masks/source/mask.png"),
        )
    db_session.expire_all()
    page = await db_session.scalar(
        select(Page).where(Page.book_id == "source", Page.page_number == 1)
    )
    assert page.text == "원문 1"
    assert page.image_url == canonical_media_url("jobs/source/p1.png")
    guards = list((await db_session.scalars(select(StoragePurgeTask))).all())
    assert len(guards) == 1
    assert guards[0].target.startswith("books/source/edits/")
    assert guards[0].status == "pending"


@pytest.mark.asyncio
async def test_manual_edit_cas_rejects_concurrent_page_change(
    db_session, monkeypatch, review_bytes
):
    from src.services.illustration_quality_edits import edit_verified_page
    from src.core.database import AsyncSessionLocal
    from src.services import image

    await _seed_book(db_session)
    monkeypatch.setattr(
        image,
        "generate_image",
        AsyncMock(return_value=canonical_media_url("books/source/edits/new.png")),
    )

    async def review(**kwargs):
        async with AsyncSessionLocal() as db:
            page = await db.scalar(
                select(Page).where(Page.book_id == "source", Page.page_number == 2)
            )
            page.text = "다른 작업이 수정한 본문"
            await db.commit()
        return _review()

    monkeypatch.setattr(image_quality, "review_book_illustrations", review)
    with pytest.raises(StoryBookError):
        await edit_verified_page(job_id="source-job", book_id="source", page_number=1, mode="image")
    db_session.expire_all()
    page = await db_session.scalar(
        select(Page).where(Page.book_id == "source", Page.page_number == 1)
    )
    assert page.image_url == canonical_media_url("jobs/source/p1.png")


@pytest.mark.asyncio
async def test_retell_rejection_creates_no_book_or_image_copies(
    db_session, monkeypatch, review_bytes
):
    from src.services import illustration_quality_edits as edits

    await _seed_book(db_session)
    copy = AsyncMock()
    monkeypatch.setattr(edits, "copy_object_to_new_key", copy)
    monkeypatch.setattr(
        image_quality,
        "review_book_illustrations",
        AsyncMock(return_value=_review(failures={1: ["uncertain"]})),
    )
    with pytest.raises(StoryBookError):
        await edits.publish_verified_retell(
            source_book_id="source",
            user_key="owner",
            retold=RetoldStory(title="새 이야기", pages=["새 본문"] * 4),
            target_age="3-5",
            idempotency_key=None,
        )
    assert await db_session.scalar(select(func.count(Book.id))) == 1
    copy.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_book_quality_failure_refunds_once_and_never_publishes(
    db_session, monkeypatch, valid_book_spec
):
    from src.models.dto import BookSpec
    from src.services.credits import credits_service
    from src.services import orchestrator, tasks

    monkeypatch.setattr(settings, "illustration_quality_enabled", True)
    await credits_service.get_or_create_credits(db_session, "owner")
    db_session.add(Job(id="new-job", status="queued", user_key="owner"))
    await db_session.commit()
    starting_credits = await db_session.scalar(select(UserCredits.credits))
    await credits_service.use_credit(db_session, "owner", reference_id="new-job")

    async def reject(**kwargs):
        return _review(len(kwargs["images"]), {1: ["uncertain"]})

    learning = AsyncMock()
    monkeypatch.setattr(orchestrator, "generate_learning_assets", learning)
    monkeypatch.setattr(image_quality, "review_book_illustrations", reject)
    assert (
        await orchestrator.start_book_generation("new-job", BookSpec(**valid_book_spec), "owner")
        is None
    )
    db_session.expire_all()
    job = await db_session.get(Job, "new-job")
    assert job.status == "failed" and job.error_code == "IMAGE_QUALITY_FAILED"
    assert await db_session.scalar(select(func.count(Book.id))) == 0
    assert await db_session.scalar(select(UserCredits.credits)) == starting_credits
    learning.assert_not_awaited()
    repeated = await tasks._run_book_task_async("new-job", valid_book_spec, "owner")
    assert repeated["status"] == "skipped"


@pytest.mark.asyncio
async def test_production_disabled_quality_blocks_before_any_budget_or_provider(monkeypatch):
    from src.routers import books

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "illustration_quality_enabled", False)
    consume = AsyncMock()
    monkeypatch.setattr(books, "consume_daily_generation_budget", consume)
    with pytest.raises(StoryBookError) as exc:
        await books.consume_generation_budget(endpoint="books.retell")
    assert exc.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_mime_comes_from_original_bytes_not_filename_or_metadata(monkeypatch):
    from io import BytesIO
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="JPEG")
    original_bytes = output.getvalue()
    monkeypatch.setattr(
        pipeline, "get_object_bytes", AsyncMock(return_value=(original_bytes, "image/png"))
    )
    reviewer = AsyncMock(return_value=_review())
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    await pipeline.verify_and_repair_illustrations(**_inputs(), regenerate=AsyncMock())
    assert set(reviewer.call_args.kwargs["images"].values()) == {(original_bytes, "image/jpeg")}


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["normal", "enqueue_failed", "retained_alias", "referenced_cover"])
async def test_manual_edit_publishes_page_and_operation_atomically(
    db_session, monkeypatch, review_bytes, cleanup
):
    from src.services import image, illustration_quality_edits as edits

    await _seed_book(db_session)
    old_key = "jobs/source/p1.png"
    old_url = canonical_media_url(old_key)
    if cleanup == "retained_alias":
        sibling = await db_session.scalar(select(Page).where(Page.book_id == "source", Page.page_number == 2))
        sibling.image_url = f"{old_url}?signed=fixture"
    if cleanup == "referenced_cover":
        # Exercise the DB lookup without relying on the current book's retained URLs.
        db_session.add(Job(id="cover-job", user_key="owner", status="done"))
        await db_session.flush()
        db_session.add(Book(id="cover-book", job_id="cover-job", user_key="owner", title="공유 표지",
                            language="ko", target_age="5-7", style="watercolor", cover_image_url=old_url))
    db_session.add(Job(id="edit-job", user_key="owner", status="running"))
    await db_session.commit()
    generated = canonical_media_url("books/source/edits/new.png")
    monkeypatch.setattr(image, "generate_image", AsyncMock(return_value=generated))
    monkeypatch.setattr(
        image_quality, "review_book_illustrations", AsyncMock(return_value=_review())
    )
    if cleanup == "enqueue_failed":
        monkeypatch.setattr(edits, "enqueue_discarded_images", AsyncMock(side_effect=RuntimeError("queue failed")))
    edit = edits.edit_verified_page(
        job_id="source-job",
        book_id="source",
        page_number=1,
        mode="image",
        operation_job_id="edit-job",
    )
    if cleanup == "enqueue_failed":
        with pytest.raises(RuntimeError, match="queue failed"):
            await edit
    else:
        await edit
    db_session.expire_all()
    page = await db_session.scalar(
        select(Page).where(Page.book_id == "source", Page.page_number == 1)
    )
    failed = cleanup == "enqueue_failed"
    assert page.image_url == (old_url if failed else generated)
    assert (await db_session.get(Job, "edit-job")).status == ("running" if failed else "done")
    tasks = (await db_session.scalars(select(StoragePurgeTask))).all()
    assert [task.status for task in tasks if task.kind == "prefix"] == ["pending" if failed else "cancelled"]
    assert [task.target for task in tasks if task.kind == "keys"] == ([old_key] if cleanup == "normal" else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "both"])
@pytest.mark.parametrize("passes", [False, True])
async def test_retext_candidate_is_reviewed_before_any_text_or_image_changes(
    db_session, monkeypatch, review_bytes, mode, passes
):
    from src.models.db import StoryDraftDB
    from src.models.dto import BookSpec, RewriteResult
    from src.services import image, llm, orchestrator
    from src.services.illustration_quality_edits import edit_verified_page

    await _seed_book(db_session)
    story = await orchestrator.generate_story(
        BookSpec(topic="나무와 토끼", page_count=8, target_age="5-7", style="watercolor")
    )
    story = story.model_copy(update={"pages": story.pages[:4]})
    db_session.add(StoryDraftDB(job_id="source-job", draft=story.model_dump()))
    await db_session.commit()
    monkeypatch.setattr(
        llm,
        "call_text_rewrite",
        AsyncMock(return_value=RewriteResult(page=1, revised_text="토끼가 물을 모두 주었어요.")),
    )
    generated = canonical_media_url("books/source/edits/new.png")
    wire_prompts = []

    async def generate(prompt, **kwargs):
        from src.services.image_correction import provider_prompt_with_correction

        wire_prompts.append(provider_prompt_with_correction(prompt))
        return generated

    generator = AsyncMock(side_effect=generate)
    monkeypatch.setattr(image, "generate_image", generator)
    reviewer = AsyncMock(return_value=_review(failures={} if passes else {1: ["uncertain"]}))
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    call = edit_verified_page(
        job_id="source-job",
        book_id="source",
        page_number=1,
        mode=mode,
        feedback="물을 모두 준 장면으로",
    )
    if passes:
        await call
    else:
        with pytest.raises(StoryBookError):
            await call
    assert reviewer.call_args.kwargs["page_texts"][1] == "토끼가 물을 모두 주었어요."
    db_session.expire_all()
    page = await db_session.scalar(
        select(Page).where(Page.book_id == "source", Page.page_number == 1)
    )
    assert page.text == ("토끼가 물을 모두 주었어요." if passes else "원문 1")
    assert page.image_url == (
        generated if passes and mode == "both" else canonical_media_url("jobs/source/p1.png")
    )
    if mode == "both":
        assert "토끼가 물을 모두 주었어요." in wire_prompts[0].positive_prompt
        assert generator.call_args.args[0].positive_prompt == "A rabbit waters a small tree"


@pytest.mark.asyncio
async def test_verified_retell_copies_images_only_after_pass(db_session, monkeypatch, review_bytes):
    from src.services import illustration_quality_edits as edits

    await _seed_book(db_session)
    source = await db_session.get(Book, "source")
    source.profile_id = "child-a"
    await db_session.commit()
    review_done = False

    async def review(**kwargs):
        nonlocal review_done
        review_done = True
        assert kwargs["page_texts"][1] == "새 본문"
        return _review()

    async def copy(url, key):
        assert review_done
        return canonical_media_url(key)

    monkeypatch.setattr(image_quality, "review_book_illustrations", review)
    monkeypatch.setattr(edits, "copy_object_to_new_key", copy)
    new_id = await edits.publish_verified_retell(
        source_book_id="source",
        user_key="owner",
        retold=RetoldStory(title="새 이야기", pages=["새 본문"] * 4),
        target_age="3-5",
        idempotency_key="one-retell",
    )
    book = await db_session.get(Book, new_id)
    assert book.retelling_source_book_id == "source"
    assert book.profile_id == "child-a"
    assert (await db_session.get(Job, book.job_id)).profile_id == "child-a"
    assert (await db_session.get(Job, book.job_id)).status == "done"
    assert book.cover_image_url != canonical_media_url("jobs/source/cover.png")


@pytest.mark.asyncio
@pytest.mark.parametrize("learning_outcome", ["available", "timeout", "deadline"])
async def test_new_book_all_passes_is_published_after_review(
    db_session, monkeypatch, valid_book_spec, learning_outcome,
):
    from src.models.dto import BookSpec
    from src.services import orchestrator

    monkeypatch.setattr(settings, "illustration_quality_enabled", True)
    db_session.add(Job(id="new-job", status="queued", user_key="owner"))
    await db_session.commit()
    calls = []

    async def approve(**kwargs):
        calls.append(kwargs)
        assert await db_session.scalar(select(func.count(Book.id))) == 0
        if learning_outcome == "deadline":
            monkeypatch.setattr(orchestrator, "time", SimpleNamespace(
                monotonic=lambda: time.monotonic() + settings.job_sla_seconds,
            ))
        return _review(len(kwargs["images"]))

    monkeypatch.setattr(image_quality, "review_book_illustrations", approve)
    if learning_outcome != "available":
        learning = AsyncMock(side_effect=asyncio.TimeoutError)
        monkeypatch.setattr(orchestrator, "generate_learning_assets", learning)
    result = await orchestrator.start_book_generation(
        "new-job", BookSpec(**valid_book_spec), "owner"
    )
    assert result is not None and len(calls) == 1
    db_session.expire_all()
    assert (await db_session.get(Job, "new-job")).status == "done"
    assert await db_session.get(Book, result.book_id) is not None
    if learning_outcome == "timeout":
        learning.assert_awaited_once()
        assert result.learning_assets is None
    elif learning_outcome == "deadline":
        learning.assert_not_awaited()
        assert result.learning_assets is None


@pytest.mark.asyncio
@pytest.mark.parametrize("publish", [True, False])
async def test_learning_assets_overlap_bounded_repairs_without_publishing_before_review(
    db_session, monkeypatch, valid_book_spec, publish,
):
    from src.models.dto import BookSpec, LearningAssets
    from src.services import orchestrator

    monkeypatch.setattr(settings, "illustration_quality_enabled", True)
    db_session.add(Job(id="new-job", status="queued", user_key="owner"))
    await db_session.commit()
    learning_started = asyncio.Event()
    learning_stopped = asyncio.Event()
    review_finished = asyncio.Event()
    review_calls = 0
    learning_calls = 0

    async def learning(story):
        nonlocal learning_calls
        learning_calls += 1
        learning_started.set()
        try:
            await review_finished.wait()
            return LearningAssets(
                source_language="ko",
                target_language="en",
                title_translation="A story",
                pages=[{"page": page.page, "translated_text": "A translation."} for page in story.pages],
                parent_guide={"summary": "Read together.", "discussion_prompts": [], "activities": []},
            )
        finally:
            learning_stopped.set()

    async def review(**kwargs):
        nonlocal review_calls
        review_calls += 1
        pages = len(kwargs["images"])
        if review_calls == 1:
            assert not learning_started.is_set()
            return _review(pages, {1: ["action_mismatch"]})
        await asyncio.wait_for(learning_started.wait(), timeout=2)
        assert await db_session.scalar(select(func.count(Book.id))) == 0
        if not publish:
            return _review(pages, {1: ["uncertain"]})
        review_finished.set()
        return _review(pages)

    monkeypatch.setattr(orchestrator, "generate_learning_assets", learning)
    monkeypatch.setattr(image_quality, "review_book_illustrations", review)
    result = await orchestrator.start_book_generation("new-job", BookSpec(**valid_book_spec), "owner")
    assert review_calls == 2 and learning_calls == 1 and learning_stopped.is_set()
    db_session.expire_all()
    job = await db_session.get(Job, "new-job")
    if publish:
        assert job.status == "done"
        assert result.learning_assets.title_translation == "A story"
        assert await db_session.get(Book, result.book_id) is not None
    else:
        assert result is None
        assert job.status == "failed" and job.error_code == "IMAGE_QUALITY_FAILED"
        assert await db_session.scalar(select(func.count(Book.id))) == 0


@pytest.mark.asyncio
async def test_twelve_page_book_uses_last_repair_for_one_remaining_defect(monkeypatch, review_bytes):
    from src.services.image_correction import correction_scene_reference
    from src.services.image_request_budget import image_request_budget, consume_image_request
    reviewer = AsyncMock(side_effect=[
        _review(13, {2: ["action_mismatch"], 3: ["action_mismatch"]}),
        _review(13, {3: ["action_mismatch"]}), _review(13),
    ])
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    calls = []
    progress = AsyncMock()
    async def repair(page, prompt, current):
        assert correction_scene_reference() is None
        consume_image_request()
        calls.append(page)
        return canonical_media_url(f"jobs/q/repaired-{page}-{len(calls)}.png")
    inputs = _inputs(13)
    with image_request_budget(16, inputs["deadline"]) as budget:
        for _ in range(13):
            consume_image_request()
        result = await pipeline.verify_and_repair_illustrations(
            **inputs, regenerate=repair, on_progress=progress,
        )
        assert budget.used == 16
    assert calls == [2, 3, 3]
    assert reviewer.await_count == 3
    assert [call.args for call in progress.await_args_list] == [
        ("verify_illustrations", 86),
        ("repair_illustrations", 87),
        ("verify_illustrations", 90),
        ("repair_illustrations", 91),
        ("verify_illustrations", 92),
    ]
    assert result.repaired_pages == [2, 3]
    assert len(result.discarded_urls) == 3


@pytest.mark.asyncio
async def test_transient_image_retries_reduce_quality_repair_allowance(monkeypatch, review_bytes):
    from src.services.image_request_budget import image_request_budget, consume_image_request
    reviewer = AsyncMock(return_value=_review(13, {3: ["action_mismatch"]}))
    monkeypatch.setattr(image_quality, "review_book_illustrations", reviewer)
    inputs = _inputs(13)
    calls = []
    async def repair(page, prompt, current):
        consume_image_request()
        calls.append(page)
        return canonical_media_url("jobs/q/last-allowed.png")
    with image_request_budget(16, inputs["deadline"]) as budget:
        for _ in range(15):
            consume_image_request()
        with pytest.raises(StoryBookError):
            await pipeline.verify_and_repair_illustrations(**inputs, regenerate=repair)
        assert budget.used == 16
    assert calls == [3] and reviewer.await_count == 2
