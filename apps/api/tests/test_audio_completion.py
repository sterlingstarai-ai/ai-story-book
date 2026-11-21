from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.core.audio_feature import audio_readiness_issues
from src.core.config import settings
from src.services.audio_text import audio_texts


def test_stt_requires_matching_provider_credentials(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_api_key", "tts-key")
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "stt_api_key", None)
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_api_key", "not-an-openai-key")
    assert "stt_key" in audio_readiness_issues()
    monkeypatch.setattr(settings, "stt_api_key", "stt-key")
    assert not audio_readiness_issues()


def test_english_original_does_not_become_korean_audio():
    assert audio_texts("Hello", None, None, "en") == {"en": "Hello"}
    assert audio_texts("ねこ", "고양이", "Cat", "ja") == {
        "ja": "ねこ", "ko": "고양이", "en": "Cat"
    }


@pytest.mark.parametrize("text", ["おはようございます", "你好，今天很开心", "¡Qué día más bonito!"])
def test_supported_language_exact_reading_receives_full_score(text):
    from src.routers.pronunciation import _score_pronunciation
    score, _ = _score_pronunciation(text, text)
    assert score == 100.0


@pytest.mark.asyncio
async def test_audio_upload_requires_parental_consent_before_stt(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    from src.services.stt import stt_service
    synth = AsyncMock()
    monkeypatch.setattr(stt_service, "transcribe_audio", synth)
    result = await client.post("/v1/pronunciation/evaluate-audio", headers=headers,
        data={"expected_text": "안녕하세요", "language": "ko"},
        files={"audio_file": ("speech.m4a", b"audio", "audio/mp4")})
    assert result.status_code == 403
    assert result.json()["error"]["code"] == "PARENTAL_CONSENT_REQUIRED"
    synth.assert_not_awaited()


@pytest.mark.asyncio
async def test_google_stt_keeps_all_segments(monkeypatch):
    from src.services.stt import GoogleSTTProvider
    monkeypatch.setattr(settings, "google_stt_api_key", "key")
    response = httpx.Response(200, request=httpx.Request("POST", "https://example.com"), json={
        "results": [{"alternatives": [{"transcript": "First sentence."}]},
                    {"alternatives": [{"transcript": "Second sentence."}]}]
    })
    client = AsyncMock()
    client.post.return_value = response
    with patch("src.services.stt.httpx.AsyncClient") as factory:
        factory.return_value.__aenter__.return_value = client
        text = await GoogleSTTProvider().transcribe(b"audio", mime_type="audio/wav", language="en")
    assert text == "First sentence. Second sentence."


@pytest.mark.asyncio
async def test_audio_readiness_uses_endpoint_scope_not_only_key_presence(monkeypatch):
    from src.services import provider_runtime as runtime
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "image_provider", "mock")
    monkeypatch.setattr(settings, "photo_processing_enabled", False)
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_api_key", "audio-scope-regression")
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "stt_api_key", "audio-scope-regression")
    assert (await runtime.provider_runtime_status(include_audio=True))["status"] == "unverified"
    request = runtime.begin_provider_request("openai", settings.openai_tts_model,
                                             "tts", "audio-scope-regression")
    await runtime.observe_provider_response(request, httpx.Response(401,
        json={"error": {"code": "missing_scope"}}))
    assert (await runtime.provider_runtime_status(include_audio=True))["status"] == "unavailable"
    # A speech-only outage must not make ordinary book generation unavailable.
    assert (await runtime.provider_runtime_status())["status"] == "healthy"


@pytest.mark.asyncio
async def test_narration_upload_guard_survives_failed_page_transaction(db_session, monkeypatch):
    from sqlalchemy import select
    from src.models.db import StoragePurgeTask
    from src.services.audio_assets import store_narration
    from src.services.purge_queue import cancel_purge_task
    from src.services.storage import storage_service

    upload = AsyncMock(return_value="https://cdn.example.com/narration.mp3")
    monkeypatch.setattr(storage_service, "upload_bytes", upload)
    _, guard = await store_narration(db_session, "synthetic-book", 1, "ko", b"synthetic audio")
    guard_id = guard.id
    cancel_purge_task(guard)
    # Failed/deleted page write rolls back the cancellation, preserving cleanup.
    await db_session.rollback()
    stored = (await db_session.execute(select(StoragePurgeTask)
        .where(StoragePurgeTask.id == guard_id))).scalar_one()
    assert stored.status == "pending"
    assert stored.reason == "incomplete_narration"
    assert stored.target.startswith("books/synthetic-book/audio/page_1_ko_")
    upload.assert_awaited_once()


async def _narration_book(db, *, text="Current page", consent=True, user_key="audio-regression-user"):
    from src.models.db import Book, Job, Page, UserConsent
    db.add(Job(id="audio-regression-job", user_key=user_key, status="done"))
    await db.flush()
    book = Book(id="audio-regression-book", job_id="audio-regression-job", title="Audio fixture",
                user_key=user_key, language="en", target_age="3-5", style="watercolor")
    db.add(book)
    await db.flush()
    page = Page(book_id=book.id, page_number=1, text=text)
    db.add(page)
    decision = UserConsent(user_key=book.user_key, privacy=consent,
                           data_processing=consent, granted=consent)
    db.add(decision)
    await db.commit()
    return book, page, decision


@pytest.mark.asyncio
async def test_queued_audio_rechecks_revoked_consent_before_provider(db_session, monkeypatch):
    from sqlalchemy import update
    from src.core.database import AsyncSessionLocal
    from src.models.db import UserConsent
    from src.services.job_runners import generate_audio_pages
    from src.services.tts import tts_service
    from src.core.utils import utcnow
    book, page, decision = await _narration_book(db_session)
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    # The session still holds the formerly granted consent ORM instance.
    await db_session.execute(update(UserConsent).where(UserConsent.id == decision.id)
        .values(revoked_at=utcnow()).execution_options(synchronize_session=False))
    await db_session.commit()
    synth = AsyncMock()
    monkeypatch.setattr(tts_service, "synthesize_page", synth)
    # Use a separate actual session as the worker does after queue dispatch.
    monkeypatch.setattr("src.core.database.AsyncSessionLocal", AsyncSessionLocal)
    result = await generate_audio_pages(book.id, [{"page_id": page.id, "page_number": 1,
                                                  "text": "Old queued text"}])
    assert result == (0, [1])
    synth.assert_not_awaited()


@pytest.mark.asyncio
async def test_removed_audio_job_cannot_send_text_even_with_current_consent(db_session, monkeypatch):
    from src.services.job_runners import generate_audio_pages
    from src.services.tts import OpenAITTSProvider, tts_service
    from src.models.db import Job
    from src.services.storage import storage_service

    book, page, _ = await _narration_book(db_session)
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-only")
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    monkeypatch.setattr(tts_service, "_provider", OpenAITTSProvider())
    monkeypatch.setattr("src.services.tts.require_daily_generation_budget", AsyncMock())
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(return_value="https://cdn.example.com/test.mp3"))
    send = AsyncMock(return_value=httpx.Response(200, content=b"ID3-test", headers={"content-type": "audio/mpeg"}))
    monkeypatch.setattr(httpx.AsyncClient, "post", send)
    result = await generate_audio_pages(book.id, [{"page_id": page.id, "page_number": 1}],
                                        audio_job_id="audio_withdrawn")
    assert result == (0, [1])
    send.assert_not_awaited()

    db_session.add(Job(id="audio_active", user_key=book.user_key, status="running"))
    await db_session.commit()
    assert await generate_audio_pages(book.id, [{"page_id": page.id, "page_number": 1}],
                                      audio_job_id="audio_active") == (1, [])
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_queued_audio_reads_current_database_text(db_session, monkeypatch):
    from src.services.job_runners import generate_audio_pages
    from src.services.storage import storage_service
    from src.services.tts import tts_service
    book, page, _ = await _narration_book(db_session, text="Revised current page")
    synth = AsyncMock(return_value=b"audio")
    monkeypatch.setattr(tts_service, "synthesize_page", synth)
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(return_value="https://cdn.example.com/current.mp3"))
    result = await generate_audio_pages(book.id, [{"page_id": page.id, "page_number": 1,
        "text": "Old queued text", "text_ko": "Old Korean text"}], default_language="ko")
    assert result == (1, [])
    synth.assert_awaited_once_with("Revised current page", target_age="3-5", language="en")
    await db_session.refresh(page)
    assert page.audio_url_en.endswith("current.mp3")
    assert page.audio_url_ko is None


@pytest.mark.asyncio
async def test_two_inflight_narrations_publish_once_and_keep_loser_cleanup(db_session, monkeypatch):
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.db import StoragePurgeTask
    from src.services.audio_assets import NarrationSource, publish_narration, store_narration
    from src.services.storage import storage_service
    book, page, _ = await _narration_book(db_session)
    source_a = NarrationSource.from_page(book, page)
    source_b = NarrationSource.from_page(book, page)  # both saw cache miss
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(side_effect=[
        "https://cdn.example.com/a.mp3", "https://cdn.example.com/b.mp3"]))
    url_a, guard_a = await store_narration(db_session, book.id, 1, "en", b"a")
    guard_a_id = guard_a.id
    async with AsyncSessionLocal() as other:
        url_b, guard_b = await store_narration(other, book.id, 1, "en", b"b")
        guard_b_id = guard_b.id
        assert await publish_narration(db_session, source_a, "en", url_a, guard_a) == url_a
        assert await publish_narration(other, source_b, "en", url_b, guard_b) == url_a
    await db_session.refresh(page)
    assert page.audio_url_en == url_a
    guards = (await db_session.execute(select(StoragePurgeTask)
        .where(StoragePurgeTask.id.in_([guard_a_id, guard_b_id]))
        .execution_options(populate_existing=True))).scalars().all()
    assert {g.id: g.status for g in guards} == {guard_a_id: "cancelled", guard_b_id: "pending"}
    assert guards[0].target != guards[1].target


@pytest.mark.asyncio
async def test_page_changed_during_tts_cannot_receive_stale_audio(db_session, monkeypatch):
    from sqlalchemy import select, update
    from src.models.db import Page, StoragePurgeTask
    from src.services.audio_assets import NarrationSource, publish_narration, store_narration
    from src.services.storage import storage_service
    book, page, _ = await _narration_book(db_session)
    source = NarrationSource.from_page(book, page)
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(return_value="https://cdn.example.com/old.mp3"))
    url, guard = await store_narration(db_session, book.id, 1, "en", b"old")
    guard_id = guard.id
    # A separate text regeneration can leave this worker's identity map stale.
    await db_session.execute(update(Page).where(Page.id == page.id)
        .values(text="New page").execution_options(synchronize_session=False))
    await db_session.commit()
    with pytest.raises(ValueError, match="changed"):
        await publish_narration(db_session, source, "en", url, guard)
    await db_session.refresh(page)
    assert page.text == "New page" and page.audio_url_en is None
    assert (await db_session.execute(select(StoragePurgeTask)
        .where(StoragePurgeTask.id == guard_id))).scalar_one().status == "pending"


@pytest.mark.asyncio
async def test_consent_revoked_during_tts_keeps_cleanup_and_no_published_audio(db_session, monkeypatch):
    from sqlalchemy import update
    from src.core.exceptions import APIError
    from src.models.db import UserConsent
    from src.core.utils import utcnow
    from src.services.audio_assets import NarrationSource, publish_narration, store_narration
    from src.services.storage import storage_service
    book, page, decision = await _narration_book(db_session)
    source = NarrationSource.from_page(book, page)
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(return_value="https://cdn.example.com/stale.mp3"))
    url, guard = await store_narration(db_session, book.id, 1, "en", b"old")
    await db_session.execute(update(UserConsent).where(UserConsent.id == decision.id)
        .values(revoked_at=utcnow()).execution_options(synchronize_session=False))
    await db_session.commit()
    with pytest.raises(APIError):
        await publish_narration(db_session, source, "en", url, guard)
    await db_session.refresh(page)
    assert page.audio_url_en is None and guard.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,mandatory_withdrawal", [
    ("dispatch", True), ("publish", True), ("dispatch", False),
])
async def test_on_demand_narration_rechecks_admission_without_holding_reader(
    db_session, monkeypatch, stage, mandatory_withdrawal,
):
    from sqlalchemy import select
    from src.core import database
    from src.core.exceptions import APIError
    from src.core.rate_limit import rate_limiter
    from src.models.db import StoragePurgeTask
    from src.routers.books import get_page_audio
    from src.routers.consent import ConsentGrantRequest, grant_consent, revoke_consent
    from src.services.storage import storage_service
    from src.services.tts import OpenAITTSProvider, tts_service
    from tests.test_narration_voices import _LockRedis

    book, page, _ = await _narration_book(db_session)
    owner, book_id = book.user_key, book.id
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-only")
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=_LockRedis()))
    monkeypatch.setattr(tts_service, "_provider", OpenAITTSProvider())

    async def change_decision():
        # The caller must have released its pool connection before external I/O.
        assert not db_session.in_transaction()
        async with database.AsyncSessionLocal() as other:
            if mandatory_withdrawal:
                await revoke_consent(db=other, user_key=owner)
            await grant_consent(ConsentGrantRequest(privacy=True, data_processing=True, photos=False),
                                db=other, user_key=owner)

    async def budget(_operation):
        assert not db_session.in_transaction()
        if stage == "dispatch":
            await change_decision()

    async def upload(*_args, **_kwargs):
        if stage == "publish":
            await change_decision()
        return "https://cdn.example.com/render.mp3"

    monkeypatch.setattr("src.services.tts.require_daily_generation_budget", budget)
    monkeypatch.setattr(storage_service, "upload_bytes", upload)
    send = AsyncMock(return_value=httpx.Response(200, content=b"ID3-test", headers={"content-type": "audio/mpeg"}))
    monkeypatch.setattr(httpx.AsyncClient, "post", send)
    async def narrate():
        return await get_page_audio(book_id, 1, language="en", db=db_session, user_key=owner, profile_id=None)

    if mandatory_withdrawal:
        with pytest.raises(APIError) as denied:
            await narrate()
        assert denied.value.error_code == "PARENTAL_CONSENT_REQUIRED"
        await db_session.refresh(page)
        assert page.audio_url_en is None
        if stage == "publish":
            send.assert_awaited_once()
            guard = await db_session.scalar(select(StoragePurgeTask).where(
                StoragePurgeTask.user_key == owner, StoragePurgeTask.reason == "incomplete_narration"))
            assert guard.status == "pending"
        else:
            send.assert_not_awaited()
    else:
        assert (await narrate())["audio_url"].endswith("render.mp3")
        send.assert_awaited_once()


def test_legacy_broker_narration_without_admission_never_dispatches(monkeypatch):
    from src.services import tasks
    runner = AsyncMock()
    monkeypatch.setattr("src.services.job_runners.run_audio_job", runner)
    result = tasks.generate_audio_task.run("synthetic-book", [], "5-7", "ko")
    assert result == {"status": "skipped", "reason": "missing_job_id"}
    runner.assert_not_called()
