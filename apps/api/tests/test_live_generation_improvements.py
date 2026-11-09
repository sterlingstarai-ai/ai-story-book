"""Regression cases exposed by the first real eight-page Korean book."""

import asyncio
from collections import Counter
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.dto import BookSpec, CharacterSheet, ImagePrompt, ImagePrompts
from src.services import image, llm, orchestrator


def prompts(count=4):
    return ImagePrompts(style="watercolor", cover=ImagePrompt(
        page=0, positive_prompt="A child in a quiet library", negative_prompt="text, logo, weapons", seed=1),
        pages=[ImagePrompt(page=i, positive_prompt="The child waters a flower",
                           negative_prompt="text, logo, weapons", seed=i + 1) for i in range(1, count + 1)])


def test_unicode_json_keeps_korean_meaning_without_escape_expansion():
    payload = {"text": "하루는 젖은 책을 조심조심 꺼냈어요.", "quote": '"친구야"'}
    rendered = llm.jinja_env.from_string("{{ value | tojson }}").render(value=payload)
    assert json.loads(rendered) == payload
    assert "하루는" in rendered
    assert len(rendered) < len(json.dumps(payload, ensure_ascii=True))


@pytest.mark.asyncio
async def test_twelve_page_prompts_have_room_for_all_scenes(monkeypatch, valid_character):
    spec = BookSpec(topic="작은 정원을 돌보는 이야기", target_age="7-9", style="watercolor", page_count=12)
    character = CharacterSheet(character_id="hero", **valid_character)
    story = SimpleNamespace(cover=SimpleNamespace(model_dump=lambda: {"scene": "작은 정원"}),
                            characters=[SimpleNamespace(model_dump=lambda: {
                                "id": "hero", "name": character.name, "role": "main", "brief": "친절한 정원 탐험가"})],
                            pages=[SimpleNamespace(model_dump=lambda: {"scene": "꽃에 물을 주어요"}) for _ in range(12)])
    async def provider(_system, user, max_tokens, temperature, *, response_schema=None):
        assert "꽃에 물을 주어요" in user
        # A realistic 13-scene JSON exceeds the old fixed4k output limit.
        assert 6500 <= max_tokens <= 8000
        assert response_schema == ImagePrompts.model_json_schema()
        return prompts(12).model_dump_json()
    monkeypatch.setattr(llm, "call_llm", provider)
    result = await llm.call_image_prompts_generation(spec, story, character)
    assert [p.page for p in result.pages] == list(range(1, 13))


def test_gemini_forwards_negative_prompt_and_blank_sign_policy():
    text = image.gemini_prompt_text(prompts().cover)
    assert "A child in a quiet library" in text
    assert "Exclude these elements: text, logo, weapons" in text
    assert "Signs and book covers must be blank" in text
    assert "sexual content, nudity, nsfw, violence" in text
    assert "horror, nightmare, blurry, distorted" in text


@pytest.mark.asyncio
async def test_image_progress_counts_completions_instead_of_page_number(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 4)
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    release_earlier_pages = asyncio.Event()
    finished = []
    progress = []

    async def generate(prompt, job_id, page, reference_image_url=None, **_):
        if 1 <= page <= 3:
            await release_earlier_pages.wait()
        finished.append(page)
        return f"https://s3.example/owned-page-{page}.png"

    async def update(job_id, step, value):
        progress.append((value, list(finished)))
        if len(progress) == 3:
            release_earlier_pages.set()

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    monkeypatch.setattr(orchestrator, "update_job_status", update)
    images = await asyncio.wait_for(
        orchestrator.generate_all_images("synthetic", prompts(), 5), timeout=2,
    )
    assert list(images) == list(range(5))
    assert progress[:3] == [(50, []), (57, [0]), (64, [0, 4])]
    assert [value for value, _ in progress] == [50, 57, 64, 71, 78, 85]


@pytest.mark.asyncio
async def test_image_progress_coalesces_completed_pages_during_slow_status_write(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 4)
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    first_page_write_started = asyncio.Event()
    remaining_pages_finished = asyncio.Event()
    writes = []
    finished = []

    async def generate(prompt, job_id, page, reference_image_url=None, **_):
        if page >= 2:
            await first_page_write_started.wait()
            finished.append(page)
            if len(finished) == 3:
                remaining_pages_finished.set()
        return f"https://s3.example/owned-page-{page}.png"

    async def update(job_id, step, value):
        assert step == "generate_images"
        writes.append(value)
        if value == 64:
            first_page_write_started.set()
            await remaining_pages_finished.wait()
            raise OSError("synthetic transient status-write failure")

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    monkeypatch.setattr(orchestrator, "update_job_status", update)
    images = await asyncio.wait_for(
        orchestrator.generate_all_images("synthetic", prompts(), 5), timeout=2,
    )

    assert sorted(images) == list(range(5))
    assert writes == [50, 57, 64, 85]


@pytest.mark.asyncio
async def test_incomplete_cover_prevents_paid_page_generation(monkeypatch):
    from src.core.errors import ErrorCode, StoryBookError

    generate = AsyncMock(return_value="https://placeholder.invalid/cover.png")
    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())

    with pytest.raises(StoryBookError) as exc:
        await orchestrator.generate_all_images("synthetic", prompts(12), 13, require_complete=True)

    assert exc.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    assert [call.args[2] for call in generate.await_args_list] == [0]


@pytest.mark.asyncio
@pytest.mark.parametrize("rate_limited", [False, True])
async def test_image_retry_delay_only_holds_slot_for_provider_rate_limit(monkeypatch, rate_limited):
    from src.core.errors import ErrorCode, StoryBookError
    from src.services.storage import canonical_media_url

    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 1)
    monkeypatch.setattr(orchestrator.settings, "image_max_retries", 2)
    monkeypatch.setattr(orchestrator, "get_backoff", lambda *_: 0.01)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    calls = []

    async def generate(prompt, reference_image_url=None):
        page = prompt.page
        calls.append(page)
        if page == 1 and calls.count(1) == 1:
            if rate_limited:
                raise StoryBookError(ErrorCode.IMAGE_RATE_LIMIT, "fixture rate limit")
            raise asyncio.TimeoutError()
        return canonical_media_url(f"jobs/synthetic/{page}.png")

    monkeypatch.setattr(orchestrator, "generate_image", generate)
    images = await asyncio.wait_for(
        orchestrator.generate_all_images("synthetic", prompts(), 5, require_complete=True), timeout=2,
    )
    assert set(images) == {0, 1, 2, 3, 4}
    assert calls == ([0, 1, 1, 2, 3, 4] if rate_limited else [0, 1, 2, 3, 4, 1])


@pytest.mark.asyncio
async def test_terminal_page_failure_wakes_waiting_retry_without_another_request(monkeypatch):
    from src.core.errors import ErrorCode, StoryBookError
    from src.services.storage import canonical_media_url

    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 1)
    monkeypatch.setattr(orchestrator.settings, "image_max_retries", 2)
    monkeypatch.setattr(orchestrator, "get_backoff", lambda *_: 120)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    calls = []

    async def generate(prompt, reference_image_url=None):
        page = prompt.page
        calls.append(page)
        if page == 1:
            raise asyncio.TimeoutError()
        if page == 2:
            raise StoryBookError(ErrorCode.AI_PROVIDER_UNAVAILABLE, "fixture provider unavailable")
        return canonical_media_url(f"jobs/synthetic/{page}.png")

    monkeypatch.setattr(orchestrator, "generate_image", generate)
    with pytest.raises(StoryBookError) as exc:
        await asyncio.wait_for(
            orchestrator.generate_all_images("synthetic", prompts(), 5, require_complete=True), timeout=2,
        )
    assert exc.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert calls == [0, 1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_unavailable", [False, True])
async def test_incomplete_book_stops_queued_pages_and_drains_inflight_page(monkeypatch, provider_unavailable):
    from src.core.errors import ErrorCode, StoryBookError
    from src.services.storage import canonical_media_url

    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 2)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    second_started, release_second = asyncio.Event(), asyncio.Event()
    pages_started = []
    pages_saved = []

    async def generate(prompt, job_id, page, reference_image_url=None, **_):
        pages_started.append(page)
        if page == 1:
            await second_started.wait()
            if provider_unavailable:
                raise StoryBookError(ErrorCode.AI_PROVIDER_UNAVAILABLE, "fixture provider unavailable")
            return "https://placeholder.invalid/page.png"
        if page == 2:
            second_started.set()
            await release_second.wait()
        pages_saved.append(page)
        return canonical_media_url(f"jobs/{job_id}/{page}.png")

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    async def check_book():
        work = asyncio.create_task(
            orchestrator.generate_all_images("synthetic", prompts(12), 13, require_complete=True),
        )
        try:
            await second_started.wait()
            await asyncio.sleep(0)
            assert not work.done()
            assert pages_saved == [0]
        finally:
            release_second.set()
            with pytest.raises(StoryBookError) as exc:
                await work
        return exc.value.code

    code = await asyncio.wait_for(check_book(), timeout=2)
    assert code == (ErrorCode.AI_PROVIDER_UNAVAILABLE if provider_unavailable else ErrorCode.IMAGE_QUALITY_FAILED)
    assert pages_started == [0, 1, 2]
    assert pages_saved == [0, 2]


@pytest.mark.asyncio
async def test_provider_rejection_stops_queued_http_requests(monkeypatch):
    import base64
    import re
    import time

    import httpx

    from src.core.errors import ErrorCode, StoryBookError
    from src.services.image_request_budget import image_request_budget
    from src.services.storage import _object_upload_batch, canonical_media_url

    monkeypatch.setattr(orchestrator.settings, "image_provider", "openai")
    monkeypatch.setattr(orchestrator.settings, "image_model", "gpt-image-2")
    monkeypatch.setattr(orchestrator.settings, "image_api_key", "inert-image-key")
    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 2)
    monkeypatch.setattr(orchestrator.settings, "image_max_retries", 2)
    recorded = AsyncMock()
    monkeypatch.setattr(orchestrator, "record_job_image_keys", recorded)
    png = image._mock_png_bytes(1)
    monkeypatch.setattr(image, "_fetch_image_bytes", AsyncMock(return_value=(png, "image/png")))

    image_prompts = prompts(12)
    for prompt in [image_prompts.cover, *image_prompts.pages]:
        prompt.positive_prompt += f" fixture_scene_{prompt.page}"
    calls = []
    clients = []
    upload_batches = []
    stored = []
    progress = []
    second_started, first_finished = asyncio.Event(), asyncio.Event()

    async def respond(request):
        body = await request.aread()
        page = int(re.search(rb"fixture_scene_(\d+)", body)[1])
        calls.append(page)
        if page == 1:
            await second_started.wait()
            return httpx.Response(401, json={"error": {"code": "invalid_api_key"}})
        if page == 2:
            second_started.set()
            await first_finished.wait()
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode()}]})

    async def persist(data, mime, provider):
        assert data == png and mime == "image/png" and provider == "openai"
        upload_batches.append(_object_upload_batch.get())
        url = canonical_media_url(f"jobs/synthetic/saved-{len(stored)}.png")
        stored.append(url)
        return url

    async def update(job_id, step, value):
        progress.append(value)
        if len(progress) == 3:
            first_finished.set()

    def create_client(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=create_client))
    monkeypatch.setattr(image, "_persist_image_bytes", persist)
    monkeypatch.setattr(orchestrator, "update_job_status", update)

    with image_request_budget(16, time.monotonic() + 20) as budget:
        with pytest.raises(StoryBookError) as exc:
            await asyncio.wait_for(
                orchestrator.generate_all_images("synthetic", image_prompts, 13, require_complete=True),
                timeout=3,
            )

    assert exc.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert sorted(calls) == [0, 1, 2]
    assert budget.used == 3
    assert [call.args for call in recorded.await_args_list] == [("synthetic", [url]) for url in stored]
    assert len(stored) == 2
    assert len(clients) == 1 and clients[0].is_closed
    assert upload_batches[0] is not None and upload_batches[0] is upload_batches[1]
    assert _object_upload_batch.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,reference,cover,expected", [
    ("gemini", None, "https://s3.example/owned-cover.png", "https://s3.example/owned-cover.png"),
    ("gemini", "https://s3.example/owned-photo.png", "https://s3.example/owned-cover.png", "https://s3.example/owned-photo.png"),
    ("gemini", None, "https://placeholder.invalid/image-unavailable.png", None),
    ("mock", None, "https://s3.example/owned-cover.png", "https://s3.example/owned-cover.png"),
])
async def test_owned_cover_anchors_pages_without_overriding_explicit_reference(
        monkeypatch, provider, reference, cover, expected):
    monkeypatch.setattr(orchestrator.settings, "image_provider", provider)
    seen = []
    async def generate(prompt, job_id, page, reference_image_url=None, **_):
        seen.append((page, reference_image_url, image._book_reference_url.get()))
        return cover if page == 0 else f"https://s3.example/owned-page-{page}.png"
    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        result = await orchestrator.generate_all_images("synthetic", prompts(), 5, reference)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert result[0] == cover
    assert seen[0] == (0, reference, None)
    assert all(ref == expected for page, ref, _ in seen if page > 0)
    expected_cover = None if "placeholder" in cover else cover
    assert all(anchor == expected_cover for page, _, anchor in seen if page > 0)


@pytest.mark.asyncio
async def test_concurrent_books_keep_their_own_avatar_and_generated_cover(monkeypatch):
    from src.services.storage import canonical_media_url

    monkeypatch.setattr(orchestrator.settings, "image_provider", "openai")
    monkeypatch.setattr(orchestrator.settings, "image_model", "gpt-image-2")
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())
    seen = []

    async def generate(prompt, job_id, page, reference_image_url=None, **_):
        before = image._book_reference_url.get()
        await asyncio.sleep(0)
        assert image._book_reference_url.get() == before
        seen.append((job_id, page, reference_image_url, before))
        return canonical_media_url(f"jobs/{job_id}/page-{page}.png")

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", generate)
    avatars = {job: canonical_media_url(f"jobs/{job}/character-reference/avatar.png") for job in ("one", "two")}
    await asyncio.gather(*[
        orchestrator.generate_all_images(job, prompts(), 5, avatars[job]) for job in avatars
    ])
    assert len(seen) == 10
    for job, page, avatar, cover in seen:
        assert avatar == avatars[job]
        assert cover == (canonical_media_url(f"jobs/{job}/page-0.png") if page else None)
    assert image._book_reference_url.get() is None


@pytest.mark.asyncio
async def test_failed_cover_restores_the_callers_reference_scope(monkeypatch):
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())

    async def fail(*args, **kwargs):
        assert image._book_reference_url.get() is None
        raise RuntimeError("cover failed")

    monkeypatch.setattr(orchestrator, "generate_image_with_retry", fail)
    with image.image_book_reference_scope("https://other-book.invalid/cover.png"):
        with pytest.raises(RuntimeError, match="cover failed"):
            await orchestrator.generate_all_images("synthetic", prompts(), 5)
        assert image._book_reference_url.get() == "https://other-book.invalid/cover.png"
    assert image._book_reference_url.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted_after_cover", [False, True])
async def test_approved_character_reads_share_transport_without_caching(monkeypatch, deleted_after_cover):
    from src.core.errors import StoryBookError
    from src.services import storage

    avatar_key = "jobs/synthetic/character-reference/avatar.png"
    cover_key = "jobs/synthetic/page-0.png"
    payloads = {avatar_key: b"avatar", cover_key: b"cover"}
    reads = Counter()
    provider_requests = []
    client = AsyncMock()
    clients = []

    def create_client():
        clients.append(client)
        return client

    async def read_object(*, Bucket, Key):
        reads[Key] += 1
        body = AsyncMock()
        body.read.return_value = payloads[Key]
        return {"Body": body, "ContentType": "image/png"}

    async def generate(prompt, reference_image_url=None):
        refs = await image._load_reference_images(image._reference_urls(reference_image_url), prompt.page)
        assert [data for data, _ in refs] == ([b"avatar", b"cover"] if prompt.page else [b"avatar"])
        provider_requests.append(prompt.page)
        if prompt.page == 0 and deleted_after_cover:
            del payloads[avatar_key]
        return storage.canonical_media_url(f"jobs/synthetic/page-{prompt.page}.png")

    client.get_object.side_effect = read_object
    monkeypatch.setattr(storage, "get_s3_client", create_client)
    monkeypatch.setattr(orchestrator.settings, "image_provider", "openai")
    monkeypatch.setattr(orchestrator.settings, "image_model", "gpt-image-2")
    monkeypatch.setattr(orchestrator.settings, "image_max_concurrent", 1 if deleted_after_cover else 3)
    monkeypatch.setattr(orchestrator.settings, "image_max_retries", 1)
    monkeypatch.setattr(orchestrator, "generate_image", generate)
    monkeypatch.setattr(orchestrator, "update_job_status", AsyncMock())
    monkeypatch.setattr(orchestrator, "record_job_image_keys", AsyncMock())

    run = orchestrator.generate_all_images(
        "synthetic", prompts(12), 13, storage.canonical_media_url(avatar_key), require_complete=True,
    )
    if deleted_after_cover:
        with pytest.raises(StoryBookError):
            await run
        assert provider_requests == [0]
        assert reads == {avatar_key: 2, cover_key: 1}
    else:
        assert len(await run) == 13
        assert sorted(provider_requests) == list(range(13))
        assert reads == {avatar_key: 13, cover_key: 12}
    assert clients == [client]
    client.close.assert_awaited_once()
