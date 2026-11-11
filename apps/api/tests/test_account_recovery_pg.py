"""Concurrent one-time account recovery against migrated PostgreSQL, never SQLite."""

import asyncio
import hashlib
import os
import secrets
import uuid
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from scripts import provision_store_review
from src.core.config import settings
from src.core.consent import latest_active_consent
from src.core.database import get_db
from src.core.exceptions import APIError
from src.core.generation_access import generation_identity_hash
from src.core.rate_limit import rate_limiter
from src.main import app
from src.models.db import AccountIdentity, PrivacyJournalOutbox, UserConsent
from src.services import guardian_email
from src.services.account_recovery import (
    credential_hash,
    issue_recovery_code,
    recover_account,
    resolve_user_key,
    revoke_deleted_account,
)
from src.services.privacy_journal import PrivacyJournal
from src.services.privacy_journal_outbox import publish_privacy_event
from tests.test_pg_fk_erasure import PG_URL, pg_schema_at_head  # noqa: F401
from tests.test_privacy_journal_outbox import FakeStore

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="E2E_PG_DATABASE_URL required for recovery concurrency"),
]


@pytest_asyncio.fixture
async def recovery_pg(request):
    request.getfixturevalue("pg_schema_at_head")
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_key = str(uuid.uuid4())
    async with maker() as session:
        code, _ = await issue_recovery_code(session, user_key, user_key)
    yield maker, user_key, code
    async with maker() as session:
        await session.execute(delete(AccountIdentity).where(AccountIdentity.user_key == user_key))
        await session.commit()
    await engine.dispose()


def device():
    return "asb_device_" + secrets.token_urlsafe(32)


async def attempt(maker, code, new_key):
    async with maker() as session:
        try:
            return await recover_account(session, code, new_key)
        except APIError as exc:
            return exc.status_code


async def test_only_one_competing_device_can_redeem(recovery_pg):
    maker, user_key, code = recovery_pg
    keys = [device(), device()]
    results = await asyncio.gather(*(attempt(maker, code, key) for key in keys))
    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(result == 401 for result in results) == 1
    async with maker() as session:
        for key, result in zip(keys, results):
            if isinstance(result, tuple):
                assert await resolve_user_key(session, key) == user_key
            else:
                with pytest.raises(APIError):
                    await resolve_user_key(session, key)
        with pytest.raises(APIError):
            await resolve_user_key(session, user_key)


async def test_concurrent_exact_retry_keeps_same_session_without_secret_replay(recovery_pg):
    maker, user_key, code = recovery_pg
    key = device()
    results = await asyncio.gather(attempt(maker, code, key), attempt(maker, code, key))
    assert all(isinstance(result, tuple) for result in results)
    assert sum(result[0] is None for result in results) == 1
    async with maker() as session:
        assert await resolve_user_key(session, key) == user_key


async def test_review_pass_concurrent_retries_and_isolated_new_devices(recovery_pg, monkeypatch):
    maker, _, _ = recovery_pg
    slots = [str(uuid.uuid4()) for _ in range(2)]
    passcode = "ASB-R1-" + secrets.token_urlsafe(32)
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    monkeypatch.setattr(settings, "free_plan_first_book_trial", True)
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", ",".join(map(generation_identity_hash, slots)))
    monkeypatch.setattr(settings, "store_review_account_slots", ",".join(slots))
    monkeypatch.setattr(settings, "store_review_pass_hash", credential_hash(passcode, kind="store-review"))
    maker.configure(info={"privacy_journal": PrivacyJournal(FakeStore(), b"k" * 32)})
    async def review_db():
        async with maker() as session:
            yield session

    monkeypatch.setattr(provision_store_review, "get_db", review_db)
    try:
        await provision_store_review.reserve_slots(slots)
        await provision_store_review.reserve_slots(slots)
        first, second = device(), device()
        results = await asyncio.gather(
            attempt(maker, passcode, first),
            attempt(maker, passcode, first),
            attempt(maker, passcode, second),
        )
        assert all(isinstance(result, tuple) for result in results)
        assert sum(result[0] is None for result in results) == 1
        async with maker() as session:
            assert {await resolve_user_key(session, key) for key in (first, second)} == set(slots)
        assert await attempt(maker, passcode, device()) == 401
    finally:
        async with maker() as session:
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key.in_(slots)))
            await session.execute(delete(AccountIdentity).where(AccountIdentity.user_key.in_(slots)))
            await session.commit()


async def test_reserved_review_slot_can_only_be_prepared_after_email_approval(
    recovery_pg, monkeypatch, tmp_path,
):
    redis_url = os.getenv("E2E_GUARDIAN_REDIS_URL") or os.getenv("E2E_REDIS_URL")
    if not redis_url:
        pytest.skip("Requires disposable Redis for the store-review consent journey")
    maker, _, _ = recovery_pg
    slot = str(uuid.uuid4())
    passcode = "ASB-R1-" + secrets.token_urlsafe(32)
    key_path = tmp_path / "account-scope.key"
    key_path.write_bytes(b"g" * 32)
    key_path.chmod(0o600)
    monkeypatch.setattr(settings, "account_scope_key_file", str(key_path))
    monkeypatch.setattr(settings, "account_scope_key_sha256", hashlib.sha256(b"g" * 32).hexdigest())
    monkeypatch.setattr(settings, "guardian_email_consent_enabled", True)
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    monkeypatch.setattr(settings, "free_plan_first_book_trial", True)
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", generation_identity_hash(slot))
    monkeypatch.setattr(settings, "store_review_account_slots", slot)
    monkeypatch.setattr(settings, "store_review_pass_hash", credential_hash(passcode, kind="store-review"))
    store = FakeStore()
    journal = PrivacyJournal(store, b"k" * 32)
    maker.configure(info={"privacy_journal": journal})

    async def review_db():
        async with maker() as session:
            yield session

    redis = Redis.from_url(redis_url)

    async def get_redis():
        return redis

    messages = []
    monkeypatch.setattr(rate_limiter, "get_redis", get_redis)
    monkeypatch.setattr(guardian_email, "_mail_config", lambda: ("https://example.test", "fake"))
    monkeypatch.setattr(guardian_email, "_send_notice", lambda to, link, _: messages.append((to, link)))
    monkeypatch.setattr(provision_store_review, "get_db", review_db)
    monkeypatch.setitem(app.dependency_overrides, get_db, review_db)
    try:
        await provision_store_review.reserve_slots([slot])
        with pytest.raises(APIError) as rejected:
            await provision_store_review.prepare_slot_consent(slot)
        assert rejected.value.status_code == 403
        assert await attempt(maker, passcode, device()) == 401
        recipient = f"review-{slot}@example.test"
        await provision_store_review.prepare_slot_consent(slot, request_email=recipient)
        assert len(messages) == 1 and messages[0][0] == recipient
        link = urlsplit(messages[0][1])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://example.test") as client:
            assert (await client.get(link.path)).status_code == 200
            with pytest.raises(APIError) as unconfirmed:
                await provision_store_review.prepare_slot_consent(slot)
            assert unconfirmed.value.status_code == 403
            confirmed = await client.post(link.path, json={"token": link.fragment, "consent": True})
            assert confirmed.status_code == 200 and confirmed.json()["status"] == "approved"
        store.fail_commit = True
        with pytest.raises(RuntimeError, match="consent is not yet published"):
            await provision_store_review.prepare_slot_consent(slot)
        async with maker() as session:
            assert await latest_active_consent(session, slot) is not None
            pending_event_id = await session.scalar(select(PrivacyJournalOutbox.event_id).where(
                PrivacyJournalOutbox.user_key == slot,
                PrivacyJournalOutbox.action == "consent_grant",
                PrivacyJournalOutbox.published_at.is_(None),
            ))
        assert pending_event_id is not None
        assert await attempt(maker, passcode, device()) == 401
        store.fail_commit = False
        await publish_privacy_event(maker, journal, pending_event_id)
        await provision_store_review.prepare_slot_consent(slot)
        await provision_store_review.prepare_slot_consent(slot)
        key = device()
        assert isinstance(await attempt(maker, passcode, key), tuple)
        async with maker() as session:
            owner = await resolve_user_key(session, key)
            assert owner == slot
            active = await latest_active_consent(session, owner)
            assert active and active.granted and not active.photos
        with pytest.raises(RuntimeError, match="unclaimed review reservation"):
            await provision_store_review.prepare_slot_consent(slot)
    finally:
        await redis.aclose()
        async with maker() as session:
            await session.execute(delete(PrivacyJournalOutbox).where(PrivacyJournalOutbox.user_key == slot))
            await session.execute(delete(UserConsent).where(UserConsent.user_key == slot))
            await session.execute(delete(AccountIdentity).where(AccountIdentity.user_key == slot))
            await session.commit()


async def test_code_rotation_and_recovery_have_single_winner(recovery_pg):
    maker, user_key, code = recovery_pg
    key = device()

    async def rotate():
        async with maker() as session:
            try:
                return await issue_recovery_code(session, user_key, user_key)
            except APIError as exc:
                return exc.status_code

    results = await asyncio.gather(attempt(maker, code, key), rotate())
    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(result == 401 for result in results) == 1


async def test_recovery_and_erasure_cannot_leave_a_live_deleted_session(recovery_pg):
    maker, user_key, code = recovery_pg
    key = device()

    async def erase():
        async with maker() as session:
            try:
                await revoke_deleted_account(session, user_key, user_key)
                await session.commit()
                return "deleted"
            except APIError as exc:
                return exc.status_code

    restored, erased = await asyncio.gather(attempt(maker, code, key), erase())
    if isinstance(restored, tuple):
        assert erased == 401
        async with maker() as session:
            assert await resolve_user_key(session, key) == user_key
    else:
        assert restored == 401 and erased == "deleted"
        async with maker() as session:
            with pytest.raises(APIError):
                await resolve_user_key(session, key)
