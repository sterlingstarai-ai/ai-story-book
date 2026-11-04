from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.models.db import NarrationVariant, StoragePurgeTask
from src.services.audio_assets import NarrationSource, publish_variant, retire_page_variants, store_narration
from src.services.storage import storage_service
from tests.test_audio_completion import _narration_book


class _LockRedis:
    def __init__(self):
        self.entries = {}

    async def set(self, key, token, *, ex, nx):
        assert ex == 600 and nx is True
        if key in self.entries:
            return False
        self.entries[key] = token
        return True

    async def eval(self, _script, _count, key, token):
        if self.entries.get(key) == token:
            del self.entries[key]


@pytest.mark.asyncio
async def test_capabilities_advertise_current_audio_provider(client, monkeypatch):
    from src.routers import config as config_router

    monkeypatch.setattr(config_router, "audio_supported", lambda: True)
    monkeypatch.setattr(config_router, "narration_supported", lambda: True)
    monkeypatch.setattr(settings, "tts_provider", "google_gemini")
    response = await client.get("/v1/config/capabilities")
    assert response.json()["narration_audio_provider"] == "google_gemini"
    monkeypatch.setattr(settings, "tts_provider", "openai_realtime")
    response = await client.get("/v1/config/capabilities")
    assert response.json()["narration_audio_provider"] == "openai_realtime"


@pytest.mark.asyncio
async def test_choices_are_supported_only_with_openai(client, monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "google")
    assert (await client.get("/v1/config/capabilities")).json()["narration_voice_selection_supported"] is False
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-key")
    assert (await client.get("/v1/config/capabilities")).json()["narration_voice_selection_supported"] is True


@pytest.mark.asyncio
async def test_voice_caches_are_separate_and_default_audio_preserved(db_session, monkeypatch):
    from src.routers.books import get_page_audio
    from src.services.tts import tts_service

    book, page, _ = await _narration_book(db_session)
    page.audio_url = "https://cdn.example.com/legacy.mp3"
    page.audio_url_en = page.audio_url
    await db_session.commit()
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-key")
    monkeypatch.setattr(settings, "generation_access_mode", "open")
    from src.core.rate_limit import rate_limiter
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=_LockRedis()))
    synth = AsyncMock(return_value=b"synthetic audio")
    monkeypatch.setattr(tts_service, "synthesize_page", synth)

    async def upload(_data, key, **_kwargs):
        return "https://cdn.example.com/" + key
    monkeypatch.setattr(storage_service, "upload_bytes", upload)

    async def get(voice):
        return await get_page_audio(book.id, 1, language="en", voice=voice,
                                    db=db_session, user_key=book.user_key, profile_id=None)
    default = await get("default")
    warm = await get("warm")
    deep = await get("deep")
    assert default["audio_url"].endswith("legacy.mp3")
    assert warm["audio_url"] != deep["audio_url"]
    assert await get("warm") == warm
    assert synth.await_count == 2
    assert [call.kwargs["voice"] for call in synth.await_args_list] == ["coral", "onyx"]
    await db_session.refresh(page)
    assert page.audio_url == page.audio_url_en == default["audio_url"]
    assert len((await db_session.scalars(select(NarrationVariant))).all()) == 2


@pytest.mark.asyncio
async def test_default_narration_does_not_duplicate_an_inflight_generation(db_session, monkeypatch):
    from src.core.exceptions import APIError
    from src.core.rate_limit import rate_limiter
    from src.routers.books import get_page_audio
    from src.services.audio_assets import variant_singleflight
    from src.services.tts import tts_service

    book, _, _ = await _narration_book(db_session)
    monkeypatch.setattr(settings, 'tts_provider', 'openai')
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'test-key')
    monkeypatch.setattr(settings, 'generation_access_mode', 'open')
    monkeypatch.setattr(rate_limiter, 'get_redis', AsyncMock(return_value=_LockRedis()))
    synth = AsyncMock(return_value=b'synthetic audio')
    monkeypatch.setattr(tts_service, 'synthesize_page', synth)
    monkeypatch.setattr(storage_service, 'upload_bytes', AsyncMock(return_value='https://cdn.example.com/audio.mp3'))
    book_id, user_key = book.id, book.user_key

    async def request():
        return await get_page_audio(book_id, 1, language='en', voice='default', style='legacy',
                                    db=db_session, user_key=user_key, profile_id=None)

    async with variant_singleflight(user_key, book_id, 1, 'en', 'default', 'legacy', 'openai'):
        with pytest.raises(APIError) as error:
            await request()
        assert error.value.status_code == 409
        synth.assert_not_awaited()

    first = await request()
    assert await request() == first
    synth.assert_awaited_once()


@pytest.mark.asyncio
async def test_singleflight_rejects_concurrency_and_holds_lock_on_failure(monkeypatch):
    from src.core.exceptions import APIError
    from src.core.rate_limit import rate_limiter
    from src.services.audio_assets import variant_singleflight
    redis = _LockRedis()
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=redis))
    args = ("user", "book", 1, "ko", "warm")
    async with variant_singleflight(*args):
        with pytest.raises(APIError) as error:
            async with variant_singleflight(*args):
                pass
        assert error.value.error_code == "AUDIO_GENERATION_IN_PROGRESS"
    assert not redis.entries
    with pytest.raises(RuntimeError):
        async with variant_singleflight(*args):
            raise RuntimeError("provider may still be processing")
    assert len(redis.entries) == 1  # expire instead of immediately duplicating a paid request
    with pytest.raises(APIError):
        async with variant_singleflight(*args):
            pass


@pytest.mark.asyncio
async def test_singleflight_releases_lock_when_local_budget_denies_synthesis(monkeypatch):
    from src.core.exceptions import APIError
    from src.core.rate_limit import rate_limiter
    from src.services.audio_assets import variant_singleflight

    redis = _LockRedis()
    monkeypatch.setattr(rate_limiter, 'get_redis', AsyncMock(return_value=redis))
    args = ('user', 'book', 1, 'ko', 'warm')
    with pytest.raises(APIError, match='daily limit'):
        async with variant_singleflight(*args):
            raise APIError(429, 'SERVICE_BUDGET_EXCEEDED', 'daily limit')
    assert not redis.entries
    async with variant_singleflight(*args):
        assert len(redis.entries) == 1
    assert not redis.entries


@pytest.mark.asyncio
async def test_singleflight_redis_failure_blocks_generation(monkeypatch):
    from src.core.exceptions import APIError
    from src.core.rate_limit import rate_limiter
    from src.services.audio_assets import variant_singleflight
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(side_effect=ConnectionError("unavailable")))
    with pytest.raises(APIError) as error:
        async with variant_singleflight("user", "book", 1, "ko", "deep"):
            pytest.fail("must not start paid work")
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_singleflight_never_unlocks_a_different_owner(monkeypatch):
    from src.core.rate_limit import rate_limiter
    from src.services.audio_assets import variant_singleflight
    redis = _LockRedis()
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=redis))
    async with variant_singleflight("user", "book", 1, "ko", "deep"):
        key = next(iter(redis.entries))
        # A newer owner may replace an expired lease; the old owner must never delete it.
        redis.entries[key] = "new-owner-token"
    assert redis.entries[key] == "new-owner-token"


@pytest.mark.asyncio
async def test_voice_rejected_without_provider_or_ownership(db_session, monkeypatch):
    from src.core.exceptions import AuthorizationError, ValidationError
    from src.routers.books import get_page_audio
    book, _, _ = await _narration_book(db_session)
    monkeypatch.setattr(settings, "tts_provider", "google")
    with pytest.raises(ValidationError):
        await get_page_audio(book.id, 1, language="en", voice="deep", db=db_session,
                             user_key=book.user_key, profile_id=None)
    with pytest.raises(AuthorizationError):
        await get_page_audio(book.id, 1, language="en", voice="deep", db=db_session,
                             user_key="another-user", profile_id=None)


@pytest.mark.asyncio
async def test_revoked_consent_blocks_even_cached_voice(db_session, monkeypatch):
    from src.core.exceptions import APIError
    from src.routers.books import get_page_audio
    book, page, _ = await _narration_book(db_session, consent=False)
    db_session.add(NarrationVariant(id="a" * 32, page_id=page.id, language="en", voice="deep",
                                    audio_url="https://cdn.example.com/stale.mp3"))
    await db_session.commit()
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "openai_tts_api_key", "test-key")
    with pytest.raises(APIError) as error:
        await get_page_audio(book.id, 1, language="en", voice="deep", db=db_session,
                             user_key=book.user_key, profile_id=None)
    assert error.value.error_code == "PARENTAL_CONSENT_REQUIRED"


@pytest.mark.asyncio
async def test_page_change_retires_variants_with_durable_purge(db_session, monkeypatch):
    from src.services.storage import canonical_media_url
    book, page, _ = await _narration_book(db_session)
    url = canonical_media_url(f"books/{book.id}/audio/variant.mp3")
    db_session.add(NarrationVariant(id="a" * 32, page_id=page.id, language="en", voice="deep", audio_url=url))
    await db_session.commit()
    await retire_page_variants(db_session, page.id, user_key=book.user_key)
    await db_session.commit()
    assert not (await db_session.scalars(select(NarrationVariant))).all()
    assert (await db_session.scalar(select(StoragePurgeTask).where(
        StoragePurgeTask.reason == "replaced_page_audio"))).target.endswith("variant.mp3")


@pytest.mark.asyncio
async def test_changed_source_cannot_publish_variant(db_session, monkeypatch):
    book, page, _ = await _narration_book(db_session)
    source = NarrationSource.from_page(book, page)
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(return_value="https://cdn.example.com/audio.mp3"))
    url, guard = await store_narration(db_session, book.id, 1, "en", b"audio", user_key=book.user_key)
    guard_id = guard.id
    page.text = "Changed before publication"
    await db_session.commit()
    with pytest.raises(ValueError):
        await publish_variant(db_session, source, "en", "deep", url, guard)
    await db_session.rollback()
    assert not (await db_session.scalars(select(NarrationVariant))).all()
    assert (await db_session.scalar(select(StoragePurgeTask).where(
        StoragePurgeTask.id == guard_id))).status == "pending"


@pytest.mark.asyncio
async def test_competing_variant_publish_reuses_winner_and_keeps_loser_purge(db_session, monkeypatch):
    from src.core.database import AsyncSessionLocal
    book, page, _ = await _narration_book(db_session)
    source = NarrationSource.from_page(book, page)
    monkeypatch.setattr(storage_service, "upload_bytes", AsyncMock(side_effect=[
        "https://cdn.example.com/first.mp3", "https://cdn.example.com/second.mp3"]))
    first, first_guard = await store_narration(db_session, book.id, 1, "en", b"a", user_key=book.user_key)
    async with AsyncSessionLocal() as other:
        second, second_guard = await store_narration(other, book.id, 1, "en", b"b", user_key=book.user_key)
        second_guard_id = second_guard.id
        assert await publish_variant(db_session, source, "en", "warm", first, first_guard) == first
        assert await publish_variant(other, source, "en", "warm", second, second_guard) == first
        assert (await other.scalar(select(StoragePurgeTask).where(
            StoragePurgeTask.id == second_guard_id))).status == "pending"


@pytest.mark.asyncio
async def test_book_children_deletion_removes_variant_rows(db_session):
    from src.services.data_deletion import purge_book_children
    book, page, _ = await _narration_book(db_session)
    db_session.add(NarrationVariant(id="a" * 32, page_id=page.id, language="en", voice="warm",
                                    audio_url="https://cdn.example.com/book/audio.mp3"))
    await db_session.commit()
    await purge_book_children(db_session, [book.id])
    await db_session.commit()
    assert not (await db_session.scalars(select(NarrationVariant))).all()
