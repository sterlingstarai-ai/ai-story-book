"""Launch foundations: account-owned private media, provider failure, feature gating."""
import base64
import json
from urllib.parse import urlparse, parse_qs
from unittest.mock import AsyncMock

import pytest

from src.core.config import settings
from src.core.errors import LLMError
from src.core.exceptions import APIError
from src.models.db import Book, Job, Page
from src.services import storage
from src.services.photo_character import PhotoCharacterService
from tests.test_photo_provider_boundary import live_configuration


@pytest.fixture
def private_storage(monkeypatch):
    monkeypatch.setattr(settings, "s3_public_url", "https://old-media.example/books")
    monkeypatch.setattr(settings, "s3_endpoint", "http://minio:9000")
    monkeypatch.setattr(settings, "s3_download_endpoint", "https://download.example")
    monkeypatch.setattr(settings, "s3_bucket", "storybook")


def test_signed_url_round_trip_preserves_storage_key(private_storage):
    key = "characters/char-1/아이 사진.png"
    canonical = storage.canonical_media_url(key)
    signed = storage.media_url(canonical)
    parsed = urlparse(signed)
    assert parsed.netloc == "download.example"
    assert parse_qs(parsed.query)["X-Amz-Expires"] == ["3600"]
    assert "X-Amz-Signature" in parse_qs(parsed.query)
    assert storage.key_from_public_url(signed) == key
    assert storage.canonical_media_url(storage.key_from_public_url(signed)) == canonical
    assert "X-Amz" not in canonical


def test_signer_does_not_accept_lookalike_hosts_or_traversal(private_storage):
    assert storage.key_from_public_url("https://download.example.evil/storybook/a.png") is None
    assert storage.key_from_public_url("https://download.example/storybook/../other/a.png") is None
    assert storage.key_from_public_url("https://download.example/storybook/%2e%2e/a.png") is None
    external = "https://other.example/a.png"
    assert storage.media_url(external) == external


async def _seed_book(db, user_key):
    cover = storage.canonical_media_url("books/private-book/cover.png")
    db.add(Job(id="job-private-book", status="done", user_key=user_key))
    await db.flush()
    book = Book(id="private-book", job_id="job-private-book", title="Private book",
                language="ko", target_age="5-7", style="watercolor",
                user_key=user_key, cover_image_url=cover)
    db.add(book)
    db.add(Page(book_id=book.id, page_number=1, text="첫 페이지",
                image_url=storage.canonical_media_url("books/private-book/1.png")))
    await db.commit()
    return book


@pytest.mark.asyncio
async def test_owned_book_signs_at_read_boundary_without_mutating_db(
    client, db_session, headers, private_storage,
):
    book = await _seed_book(db_session, headers["X-User-Key"])
    canonical = book.cover_image_url
    response = await client.get("/v1/books/private-book/detail", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "X-Amz-Signature" in data["cover_image_url"]
    assert "X-Amz-Signature" in data["pages"][0]["image_url"]
    assert "no-store" in response.headers["cache-control"]
    await db_session.refresh(book)
    assert book.cover_image_url == canonical
    foreign = {"X-User-Key": "99999999-9999-4999-8999-999999999999"}
    denied = await client.get("/v1/books/private-book/detail", headers=foreign)
    assert denied.status_code in {403, 404}
    assert "X-Amz-Signature" not in denied.text
    anonymous = await client.get("/v1/books/private-book/detail")
    assert anonymous.status_code in {401, 422}


@pytest.mark.asyncio
async def test_branch_cannot_mint_download_for_another_book(
    client, db_session, headers, private_storage,
):
    await _seed_book(db_session, headers["X-User-Key"])
    response = await client.post("/v1/branch/books/private-book/initialize", headers=headers, json={
        "nodes": [{"node_key": "start", "page_number": 1, "text": "Hi",
                   "image_url": storage.canonical_media_url("characters/someone-else/photo.png")}],
    })
    assert response.status_code == 400
    assert "X-Amz-Signature" not in response.text


@pytest.mark.asyncio
async def test_legacy_voice_signed_url_can_be_deleted_as_canonical_key(
    client, headers, private_storage, _block_real_s3, db_session,
):
    from tests.voice_fixtures import seed_voice_profile
    key = storage.voice_sample_prefix(headers["X-User-Key"]) + "legacy.wav"
    url = await storage.storage_service.upload_bytes(b"legacy", key, content_type="audio/wav")
    signed = storage.media_url(url)
    assert "X-Amz-Signature" in signed
    profile_id = await seed_voice_profile(db_session, headers["X-User-Key"],
        sample_audio_url=storage.canonical_media_url(storage.key_from_public_url(signed)))
    assert key in _block_real_s3.objects
    deleted = await client.delete(f"/v1/voice-profiles/{profile_id}", headers=headers)
    assert deleted.status_code == 200
    assert key not in _block_real_s3.objects


@pytest.mark.asyncio
async def test_private_reference_and_pdf_read_s3_without_public_http(
    monkeypatch, private_storage, _block_real_s3,
):
    from src.services.image import _fetch_image_as_base64
    from src.services.pdf import pdf_service
    key = "characters/one/photo.png"
    _block_real_s3.objects[key] = b"image-data"
    url = storage.canonical_media_url(key)
    fetch = AsyncMock(side_effect=AssertionError("No anonymous HTTP for private assets"))
    monkeypatch.setattr("httpx.AsyncClient.get", fetch)
    data, _ = await _fetch_image_as_base64(url)
    assert base64.b64decode(data) == b"image-data"
    assert await pdf_service._fetch_image(url) == b"image-data"
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_text_character_provider_never_returns_mock(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "typo")
    with pytest.raises(LLMError):
        await PhotoCharacterService().create_character_from_text("Name", "5", ["friendly"])


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["analyze_photo", "analyze_drawing"])
@pytest.mark.parametrize("provider", ["typo", "gemini"])
async def test_unknown_or_unapproved_photo_provider_never_returns_mock(monkeypatch, method, provider):
    live_configuration(monkeypatch)
    monkeypatch.setattr(settings, "photo_analysis_provider", provider)
    request = AsyncMock(side_effect=AssertionError("No unapproved photo provider request"))
    monkeypatch.setattr("src.services.photo_character.request_openai_json", request)
    monkeypatch.setattr("src.services.photo_character._call_gemini", request)
    with pytest.raises(APIError) as caught:
        await getattr(PhotoCharacterService(), method)(b"image")
    assert caught.value.status_code == 503
    assert caught.value.error_code == "PHOTO_PROCESSING_UNAVAILABLE"
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_character_failure_is_propagated(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    svc = PhotoCharacterService()
    monkeypatch.setattr(svc, "_generate_text_character_anthropic",
                        AsyncMock(side_effect=TimeoutError("provider timed out")))
    with pytest.raises(LLMError) as caught:
        await svc.create_character_from_text("Name", "5", ["friendly"])
    assert caught.value.code.value == "LLM_TIMEOUT"
    assert "provider timed out" not in str(caught.value)


@pytest.mark.asyncio
async def test_explicit_photo_analysis_sends_actual_image_with_dedicated_credentials(monkeypatch):
    live_configuration(monkeypatch)
    call = AsyncMock(return_value=json.dumps({"visual_description": "A character"}))
    monkeypatch.setattr("src.services.photo_character.request_openai_json", call)
    image = b"\x89PNG\r\n\x1a\nimage-bytes"
    result = await PhotoCharacterService().analyze_drawing(image)
    assert result["visual_description"] == "A character"
    image_url = call.call_args.kwargs["image_url"]
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.partition(",")[2]) == image
    assert call.call_args.kwargs["model"] == settings.photo_analysis_model
    assert call.call_args.kwargs["api_key"] == settings.photo_analysis_api_key
    assert call.call_args.kwargs["api_key"] != settings.llm_api_key


@pytest.mark.asyncio
async def test_disabled_pod_blocks_quote_and_order_without_provider(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "pod_ordering_enabled", False)
    caps = (await client.get("/v1/config/capabilities", headers=headers)).json()
    assert caps["pod_ordering_supported"] is False
    quote = await client.get("/v1/pod/quote?country=KR", headers=headers)
    assert quote.status_code == 409
    order = await client.post("/v1/pod/orders", headers=headers, json={
        "book_id": "any", "shipping_address": {
            "name": "Parent", "line1": "Street", "postal_code": "12345", "country": "KR",
        },
    })
    assert order.status_code == 409
    assert order.json()["error"]["code"] == "POD_NOT_SUPPORTED"
