"""Regression evidence for scan b5a756ed: real local boundaries, no live providers."""

import asyncio
from datetime import timedelta, timezone
import io
import threading
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.exceptions import APIError
from src.core.utils import utcnow
from src.models.db import IAPReceipt, UserCredits
from src.services.iap_verifier import IAPVerificationResult, iap_verifier


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("erase_account", [None, "owner", "recipient",
                                           "recipient_then_owner", "recipient_then_other"])
async def test_refund_after_multiple_restores_debits_original_grant(
    client, db_session, headers, monkeypatch, native, legacy, erase_account,
):
    from src.routers.iap import _apply_native_event
    from src.models.db import Subscription
    from src.services.credits import credits_service
    from src.services.store_notifications import StoreEvent

    owner = headers["X-User-Key"]
    expiry = int((utcnow() + timedelta(days=30)).replace(tzinfo=timezone.utc).timestamp() * 1000)
    monkeypatch.setattr(iap_verifier, "verify_purchase", AsyncMock(return_value=IAPVerificationResult(
        verified=True, source="apple_store", environment="Production",
        store_transaction_id="restore-refund", store_product_id="subscription_basic",
        expires_date_ms=expiry, raw={"original_transaction_id": "restore-refund"},
    )))
    body = {"platform": "apple", "product_id": "subscription_basic",
            "transaction_id": "restore-refund", "receipt_data": "AAAA"}
    first = await client.post("/v1/iap/verify", headers=headers, json=body)
    assert first.status_code == 200, first.text
    grant = (await db_session.scalar(select(IAPReceipt))).payload["granted_credits"]
    assert grant > 0
    before = await db_session.scalar(select(UserCredits.credits).where(UserCredits.user_key == owner))
    if legacy:
        receipt = await db_session.scalar(select(IAPReceipt))
        receipt.payload = {key: value for key, value in receipt.payload.items()
                           if key not in {"granted_credits", "credit_grant_user_key"}}
        await db_session.commit()
    for user in ["11111111-2222-4333-8444-555555555555",
                 "22222222-2222-4333-8444-555555555555"]:
        response = await client.post("/v1/iap/verify", headers={"X-User-Key": user}, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "restored"
        assert response.json()["credits_added"] == 0
    db_session.expire_all()
    receipt = await db_session.scalar(select(IAPReceipt))
    assert receipt.payload["credit_grant_user_key"] == owner
    assert receipt.payload["granted_credits"] == grant
    recipient = receipt.user_key
    recipient_before = await db_session.scalar(
        select(UserCredits.credits).where(UserCredits.user_key == recipient))
    if erase_account:
        result = await client.delete("/v1/users/me", headers={
            "X-User-Key": owner if erase_account == "owner" else recipient})
        assert result.status_code == 200, result.text
    unrelated_subscription_id = None
    if erase_account == "recipient":
        # Retained grant evidence must not expire the beneficiary's newer plan.
        unrelated = await credits_service.create_subscription(
            db_session, owner, "basic", grant_credits=False)
        unrelated_subscription_id = unrelated.id
    if erase_account in {"recipient_then_owner", "recipient_then_other"}:
        restore_user = owner if erase_account == "recipient_then_owner" else (
            "55555555-2222-4333-8444-555555555555")
        result = await client.post("/v1/iap/verify", headers={"X-User-Key": restore_user}, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "restored"
        assert result.json()["credits_added"] == 0
    for _ in range(2):
        if native:
            await _apply_native_event(StoreEvent(
                platform="apple", transaction_id="restore-refund", product_id="subscription_basic",
                original_transaction_id="restore-refund", status="refunded",
                expires_date_ms=expiry, environment="Production", signed_at_ms=1000,
            ), db_session)
        else:
            response = await client.post("/v1/iap/webhook/apple", json={
                "transaction_id": "restore-refund", "status": "refunded"})
            assert response.status_code == 200, response.text
    db_session.expire_all()
    after = await db_session.scalar(select(UserCredits.credits).where(UserCredits.user_key == owner))
    assert after == (None if erase_account == "owner" else before - grant)
    assert await db_session.scalar(
        select(UserCredits.credits).where(UserCredits.user_key == recipient)) == (
            None if erase_account and erase_account.startswith("recipient") else recipient_before)
    assert (await db_session.scalar(select(IAPReceipt))).status == "refunded"
    if unrelated_subscription_id:
        assert (await db_session.get(Subscription, unrelated_subscription_id)).status == "active"


def test_repetitive_pronunciation_has_bounded_runtime():
    from src.routers.pronunciation import _score_pronunciation

    started = time.perf_counter()
    exact, _ = _score_pronunciation("a " * 2000, "a " * 2000)
    shifted, _ = _score_pronunciation("abc " * 1000, "bca " * 1000)
    elapsed = time.perf_counter() - started
    assert exact == 100
    assert 0 <= shifted < 100
    assert elapsed < 0.5, f"Bounded 4000-character scoring took {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_s3_network_and_body_read_leave_event_loop_available(monkeypatch):
    from src.services import storage

    loop_thread = threading.get_ident()
    calls = []

    def slow_operation(name):
        event = threading.Event()
        loop.call_soon_threadsafe(loop.call_later, 0.01, event.set)
        calls.append((name, threading.get_ident(), event.wait(0.2)))

    class Body(io.BytesIO):
        def read(self, size=-1):
            slow_operation("read")
            return super().read(size)

    body = Body(b"image")

    class Client:
        def get_object(self, **kwargs):
            slow_operation("get")
            return {"Body": body, "ContentLength": 5, "ContentType": "image/png"}

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(storage, "get_s3_client", lambda: Client())
    assert await storage.get_object_bytes("books/id/cover.png") == (b"image", "image/png")
    assert all(thread != loop_thread and responsive for _, thread, responsive in calls), calls
    assert body.closed


@pytest.mark.asyncio
async def test_audio_services_share_global_budget_and_block_before_provider(monkeypatch):
    from src.core.rate_limit import rate_limiter
    from src.services.stt import STTService
    from src.services.tts import TTSService
    from tests.fake_redis import FakeRedis

    monkeypatch.setattr(settings, "daily_generation_budget", 1)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=FakeRedis()))
    tts, stt = TTSService(), STTService()
    tts._provider = AsyncMock()
    tts._provider.synthesize.return_value = b"audio"
    stt._provider = AsyncMock()
    stt._provider.transcribe.return_value = "hello"
    assert await tts.synthesize_page("hello") == b"audio"
    with pytest.raises(APIError) as error:
        await stt.transcribe_audio(b"audio", mime_type="audio/wav")
    assert error.value.status_code == 429
    assert error.value.error_code == "SERVICE_BUDGET_EXCEEDED"
    stt._provider.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_zero_grant_restore_does_not_claw_back_other_credits(client, db_session, monkeypatch):
    from src.services.credits import credits_service

    owner = "33333333-2222-4333-8444-555555555555"
    recipient = "44444444-2222-4333-8444-555555555555"
    sub = await credits_service.create_subscription(db_session, owner, "basic", grant_credits=False)
    await credits_service.add_credits(db_session, owner, 11, "purchase", "other purchase")
    expiry = int((utcnow() + timedelta(days=30)).replace(tzinfo=timezone.utc).timestamp() * 1000)
    db_session.add(IAPReceipt(user_key=owner, platform="apple", product_id="subscription_basic",
        transaction_id="no-grant", store_transaction_id="no-grant", status="already_subscribed",
        subscription_id=sub.id, payload={"granted_credits": 0}))
    await db_session.commit()
    before = await db_session.scalar(select(UserCredits.credits).where(UserCredits.user_key == owner))
    monkeypatch.setattr(iap_verifier, "verify_purchase", AsyncMock(return_value=IAPVerificationResult(
        verified=True, source="apple_store", environment="Production", raw={},
        store_transaction_id="no-grant", store_product_id="subscription_basic",
        expires_date_ms=expiry)))
    response = await client.post("/v1/iap/verify", headers={"X-User-Key": recipient}, json={
        "platform": "apple", "product_id": "subscription_basic",
        "transaction_id": "no-grant", "receipt_data": "AAAA"})
    assert response.status_code == 200, response.text
    response = await client.post("/v1/iap/webhook/apple", json={
        "transaction_id": "no-grant", "status": "refunded"})
    assert response.status_code == 200, response.text
    assert await db_session.scalar(
        select(UserCredits.credits).where(UserCredits.user_key == owner)) == before


@pytest.mark.parametrize("text", ["안녕 작은 토끼", "Hello rabbit", "こんにちは うさぎ", "你好小兔子", "¡Hola, conejo!"])
def test_pronunciation_exact_multilingual_control(text):
    from src.routers.pronunciation import _score_pronunciation
    assert _score_pronunciation(text, text)[0] == 100


def test_pronunciation_order_omission_and_oversize_output():
    from src.core.exceptions import ValidationError
    from src.routers.pronunciation import _score_pronunciation

    assert 0 < _score_pronunciation("rabbit small the", "the small rabbit")[0] < 100
    score, feedback = _score_pronunciation("the rabbit", "the small rabbit")
    assert 0 < score < 100
    assert "small" in feedback
    assert _score_pronunciation("", "hello")[0] == 0
    with pytest.raises(ValidationError):
        _score_pronunciation("a" * 4001, "hello")


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, 30])
async def test_s3_oversized_body_is_bounded_and_closed(monkeypatch, header):
    from src.core.errors import StorageError
    from src.services import storage

    body = io.BytesIO(b"x" * 30)
    response = {"Body": body}
    if header is not None:
        response["ContentLength"] = header
    client = AsyncMock()
    client.get_object.return_value = response
    monkeypatch.setattr(storage, "get_s3_client", lambda: client)
    monkeypatch.setattr(storage, "_MAX_OBJECT_BYTES", 20)
    with pytest.raises(StorageError):
        await storage.get_object_bytes("books/cover.png")
    assert body.closed


@pytest.mark.asyncio
async def test_async_storage_adapter_and_body_remain_supported(monkeypatch):
    from src.services import storage

    body, client = AsyncMock(), AsyncMock()
    body.read.return_value = b"image"
    client.get_object.return_value = {"Body": body, "ContentType": "image/png"}
    monkeypatch.setattr(storage, "get_s3_client", lambda: client)
    assert await storage.get_object_bytes("books/cover.png") == (b"image", "image/png")
    body.read.assert_awaited_once_with(storage._MAX_OBJECT_BYTES + 1)
    body.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_length", [6, None])
async def test_object_download_applies_stricter_limit_and_closes_body(monkeypatch, declared_length):
    from src.core.errors import StorageError
    from src.services import storage

    body, client = AsyncMock(), AsyncMock()
    body.read.return_value = b"123456"
    response = {"Body": body, "ContentType": "image/png"}
    if declared_length is not None:
        response["ContentLength"] = declared_length
    client.get_object.return_value = response
    monkeypatch.setattr(storage, "get_s3_client", lambda: client)

    with pytest.raises(StorageError, match="size limit"):
        await storage.get_object_bytes("books/cover.png", max_bytes=5)
    if declared_length is None:
        body.read.assert_awaited_once_with(6)
    else:
        body.read.assert_not_awaited()
    body.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [304, 403, 404])
async def test_review_object_cache_requires_a_successful_revalidation(monkeypatch, status):
    from botocore.exceptions import ClientError
    from src.core.errors import StorageError
    from src.services import storage

    key = "jobs/fixture/cover.png"
    tag = '"' + 'a' * 32 + '"'
    body, client = AsyncMock(), AsyncMock()
    body.read.return_value = b"synthetic-image"
    response = {"Body": body, "ContentType": "image/png", "ETag": tag}
    error = ClientError({
        "Error": {"Code": str(status)},
        "ResponseMetadata": {"HTTPStatusCode": status, "HTTPHeaders": {"etag": tag}},
    }, "GetObject")
    client.get_object.side_effect = [response, error, error]
    monkeypatch.setattr(storage, "get_s3_client", lambda: client)
    cache = {}
    async with storage.object_read_connection_scope(revalidate=cache):
        expected = (b"synthetic-image", "image/png")
        assert await storage.get_object_bytes(key) == expected
        if status == 304:
            assert await storage.get_object_bytes(key) == expected
            with pytest.raises(StorageError, match="size limit"):
                await storage.get_object_bytes(key, max_bytes=1)
        else:
            with pytest.raises(ClientError):
                await storage.get_object_bytes(key)
    assert client.get_object.await_args_list[0].kwargs["Key"] == key
    assert client.get_object.await_args_list[1].kwargs["IfNoneMatch"] == tag
    assert key not in cache
    body.read.assert_awaited_once()
    body.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ambiguous_conditional_reply_reads_current_object(monkeypatch):
    from botocore.exceptions import ClientError
    from src.services import storage

    key = "jobs/fixture/cover.png"
    original, replacement, client = AsyncMock(), AsyncMock(), AsyncMock()
    original.read.return_value = b"original"
    replacement.read.return_value = b"replacement"
    client.get_object.side_effect = [
        {"Body": original, "ETag": '"' + 'a' * 32 + '"'},
        ClientError({"Error": {"Code": "304"}, "ResponseMetadata": {"HTTPStatusCode": 304}}, "GetObject"),
        {"Body": replacement, "ETag": 'W/"weak"'},
        {"Body": replacement, "ETag": 'W/"weak"'},
    ]
    monkeypatch.setattr(storage, "get_s3_client", lambda: client)
    async with storage.object_read_connection_scope(revalidate={}):
        assert (await storage.get_object_bytes(key))[0] == b"original"
        assert (await storage.get_object_bytes(key))[0] == b"replacement"
        assert (await storage.get_object_bytes(key))[0] == b"replacement"
    assert [
        call.kwargs.get("IfNoneMatch") for call in client.get_object.await_args_list
    ] == [None, '"' + 'a' * 32 + '"', None, None]


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/img/cover", "/img/page/1"])
async def test_share_limit_cannot_be_rotated_with_headers(client, monkeypatch, suffix):
    from src.core.rate_limit import rate_limiter

    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    limiter = AsyncMock(side_effect=[(True, 1), (False, 0)])
    monkeypatch.setattr(rate_limiter, "is_allowed", limiter)
    first = await client.get("/share/unknown" + suffix, headers={
        "X-User-Key": "a", "X-Forwarded-For": "192.0.2.1"})
    assert first.status_code == 404
    second = await client.get("/share/unknown" + suffix, headers={
        "X-User-Key": "b", "X-Forwarded-For": "192.0.2.2"})
    assert second.status_code == 429
    assert limiter.await_args_list[0] == limiter.await_args_list[1]
    assert limiter.await_args.args[0].startswith("share:")
    assert limiter.await_args.kwargs == {"bucket": "read"}


@pytest.mark.asyncio
async def test_public_share_fails_closed_without_limiter(client, monkeypatch):
    from redis.exceptions import RedisError
    from src.core.rate_limit import rate_limiter

    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(side_effect=RedisError("offline")))
    assert (await client.get("/share/unknown/img/cover")).status_code == 503


@pytest.mark.asyncio
async def test_audio_invalid_input_and_unavailable_budget_never_call_provider(monkeypatch):
    from redis.exceptions import RedisError
    from src.core.rate_limit import rate_limiter
    from src.services.stt import STTService
    from src.services.tts import TTSService

    monkeypatch.setattr(settings, "daily_generation_budget", 1)
    get_redis = AsyncMock(side_effect=RedisError("offline"))
    monkeypatch.setattr(rate_limiter, "get_redis", get_redis)
    tts, stt = TTSService(), STTService()
    tts._provider, stt._provider = AsyncMock(), AsyncMock()
    with pytest.raises(ValueError):
        await tts.synthesize_page(" ")
    with pytest.raises(ValueError):
        await stt.transcribe_audio(b"audio", mime_type="audio/wav", language="xx")
    assert await stt.transcribe_audio(b"", mime_type="audio/wav") == ""
    get_redis.assert_not_awaited()
    for operation in [tts.synthesize_page("hello"), stt.transcribe_audio(b"audio", mime_type="audio/wav")]:
        with pytest.raises(APIError) as error:
            await operation
        assert error.value.status_code == 503
    tts._provider.synthesize.assert_not_awaited()
    stt._provider.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_audio_admissions_respect_global_cap(monkeypatch):
    from src.core.rate_limit import rate_limiter
    from src.services.tts import TTSService
    from tests.fake_redis import FakeRedis

    monkeypatch.setattr(settings, "daily_generation_budget", 2)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=FakeRedis()))
    tts = TTSService()
    tts._provider = AsyncMock()
    tts._provider.synthesize.return_value = b"audio"
    results = await asyncio.gather(*(tts.synthesize_page("hello") for _ in range(8)),
                                   return_exceptions=True)
    assert results.count(b"audio") == 2
    assert sum(isinstance(result, APIError) and result.status_code == 429 for result in results) == 6
    assert tts._provider.synthesize.await_count == 2


@pytest.mark.asyncio
async def test_audio_worker_budget_failure_and_cached_page_control(db_session, monkeypatch):
    from src.core.rate_limit import rate_limiter
    from src.services.job_runners import generate_audio_pages
    from src.services.tts import tts_service
    from tests.fake_redis import FakeRedis
    from tests.test_audio_completion import _narration_book

    book, page, _ = await _narration_book(db_session)
    monkeypatch.setattr(settings, "daily_generation_budget", 1)
    get_redis = AsyncMock(return_value=FakeRedis())
    monkeypatch.setattr(rate_limiter, "get_redis", get_redis)
    provider = AsyncMock()
    provider.synthesize.return_value = b"audio"
    monkeypatch.setattr(tts_service, "_provider", provider)
    await tts_service.synthesize_page("exhaust budget")
    work = [{"page_id": page.id, "page_number": 1}]
    assert await generate_audio_pages(book.id, work) == (0, [1])
    assert provider.synthesize.await_count == 1
    page.audio_url = "https://cdn.example.com/cached.mp3"
    await db_session.commit()
    get_redis.reset_mock()
    assert await generate_audio_pages(book.id, work) == (1, [])
    get_redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_audio_http_budget_errors_and_cached_playback(client, db_session, headers, monkeypatch):
    from src.core.cost_budget import consume_daily_generation_budget
    from src.core.rate_limit import rate_limiter
    from src.models.db import Book, Job, Page
    from src.services.stt import stt_service
    from src.services.tts import tts_service
    from tests.fake_redis import FakeRedis

    class AudioBudgetRedis(FakeRedis):
        async def set(self, key, token, *, ex, nx):
            return True

        async def eval(self, script, numkeys, key, *args):
            if "redis.call('get'" in script:
                return 1
            return await super().eval(script, numkeys, key, *args)

    db_session.add(Job(id="budget-job", user_key=headers["X-User-Key"], status="done"))
    await db_session.flush()
    db_session.add(Book(id="budget-book", job_id="budget-job", user_key=headers["X-User-Key"],
        title="Budget control", target_age="3-5", language="en", style="watercolor"))
    await db_session.flush()
    page = Page(book_id="budget-book", page_number=1, text="Hello")
    db_session.add(page)
    await db_session.commit()
    monkeypatch.setattr(settings, "daily_generation_budget", 1)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=AudioBudgetRedis()))
    assert (await consume_daily_generation_budget())[0]
    tts_provider, stt_provider = AsyncMock(), AsyncMock()
    monkeypatch.setattr(tts_service, "_provider", tts_provider)
    monkeypatch.setattr(stt_service, "_provider", stt_provider)
    response = await client.get("/v1/books/budget-book/pages/1/audio?language=en", headers=headers)
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "SERVICE_BUDGET_EXCEEDED"
    response = await client.post("/v1/pronunciation/evaluate-audio", headers=headers,
        data={"expected_text": "Hello", "language": "en"},
        files={"audio_file": ("speech.wav", b"audio", "audio/wav")})
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "SERVICE_BUDGET_EXCEEDED"
    # The failed request rolled back its transaction, so reload the page.
    page = await db_session.scalar(select(Page).where(Page.book_id == "budget-book"))
    page.audio_url = "https://cdn.example.com/cached.mp3"
    await db_session.commit()
    response = await client.get("/v1/books/budget-book/pages/1/audio?language=en", headers=headers)
    assert response.status_code == 200, response.text
    tts_provider.synthesize.assert_not_awaited()
    stt_provider.transcribe.assert_not_awaited()


def test_audio_budget_redis_is_closed_before_each_worker_loop_ends(monkeypatch):
    from src.core.rate_limit import rate_limiter
    from src.services.tasks import run_async
    from src.services.tts import TTSService

    clients = []

    class LoopBoundRedis:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.closed = False
            clients.append(self)

        async def incr(self, key):
            assert self.loop is asyncio.get_running_loop(), "Redis reused across worker loops"
            return 1

        async def eval(self, _script, _numkeys, key, _ttl):
            return await self.incr(key)

        async def expire(self, key, ttl):
            return True

        async def aclose(self):
            assert not self.loop.is_closed()
            self.closed = True

    monkeypatch.setattr(settings, "daily_generation_budget", 2)
    monkeypatch.setattr(rate_limiter, "_redis", None)
    monkeypatch.setattr("src.core.rate_limit.redis.from_url", lambda *a, **kw: LoopBoundRedis())
    tts = TTSService()
    tts._provider = AsyncMock()
    tts._provider.synthesize.return_value = b"audio"
    for _ in range(2):
        assert run_async(tts.synthesize_page("hello")) == b"audio"
    assert len(clients) == 2
    assert all(client.closed for client in clients)


@pytest.mark.asyncio
async def test_compose_trusted_proxy_separates_share_visitors_without_header_spoofing(monkeypatch):
    from pathlib import Path
    from fastapi import Request
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    import yaml
    from src.core.rate_limit import check_public_share_rate_limit, rate_limiter

    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "infra/docker-compose.prod.yml").read_text())
    services = config["services"]
    configured_ip = services["nginx"]["networks"]["app-network"]["ipv4_address"]
    proxy_ip = configured_ip.split(":-", 1)[1].removesuffix("}")
    assert "FORWARDED_ALLOW_IPS=" + configured_ip in services["api"]["environment"]
    assert not services["api"].get("ports")
    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    limiter = AsyncMock(return_value=(True, 1))
    monkeypatch.setattr(rate_limiter, "is_allowed", limiter)

    async def app(scope, receive, send):
        await check_public_share_rate_limit(Request(scope))

    proxy = ProxyHeadersMiddleware(app, trusted_hosts=proxy_ip)
    for peer, forwarded in [(proxy_ip, "192.0.2.9, 198.51.100.1"),
                            (proxy_ip, "192.0.2.9, 198.51.100.2"),
                            ("203.0.113.1", "198.51.100.1")]:
        await proxy({"type": "http", "client": (peer, 1234), "method": "GET",
            "headers": [(b"x-forwarded-for", forwarded.encode())]}, AsyncMock(), AsyncMock())
    assert [call.args[0] for call in limiter.await_args_list] == [
        "share:198.51.100.1", "share:198.51.100.2", "share:203.0.113.1"]
