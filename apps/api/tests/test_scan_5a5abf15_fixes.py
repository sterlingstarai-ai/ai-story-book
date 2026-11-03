"""Regression paths for the eight findings in scan 5a5abf15 (synthetic data only)."""
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.core.exceptions import APIError, AuthorizationError
from src.core.utils import utcnow
from src.models.db import (
    Character, IAPPurchaseClaim, IAPReceipt, Job, Series, Subscription, UserCredits,
)
from src.routers import books
from src.services.credits import credits_service
from src.services.iap_verifier import IAPVerificationResult, iap_verifier
from src.services.periodic_credits import periodic_credits
from src.services.purchase_claims import claim_purchase

OWNER = "550e8400-e29b-41d4-a716-446655440000"
OTHER = "660e8400-e29b-41d4-a716-446655440000"


def proof(product, transaction="canonical-purchase", *, expired=False):
    return IAPVerificationResult(
        verified=True, source="apple_signed_transaction", environment="Production",
        store_transaction_id=transaction, store_product_id=product, raw={},
        expires_date_ms=int((utcnow().replace(tzinfo=timezone.utc) + timedelta(
            days=-1 if expired else 20)).timestamp() * 1000),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["credit_pack_5", "subscription_basic"])
async def test_erasure_then_fresh_account_cannot_regrant(client, db_session, monkeypatch, product):
    async def verify(**kwargs):
        return proof(kwargs["product_id"])
    monkeypatch.setattr(iap_verifier, "verify_purchase", verify)
    from src.routers import users
    monkeypatch.setattr(users, "run_purge_tasks", AsyncMock(return_value=[]))
    body = dict(platform="apple", product_id=product, transaction_id="client-first", receipt_data="synthetic")
    first = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": OWNER})
    assert first.status_code == 200, first.text
    old_balance = await db_session.scalar(select(UserCredits.credits).where(UserCredits.user_key == OWNER))
    assert old_balance >= 5
    erased = await client.delete("/v1/users/me", headers={"X-User-Key": OWNER})
    assert erased.status_code == 200, erased.text
    assert (await db_session.scalars(select(IAPPurchaseClaim))).all()
    assert not (await db_session.scalars(select(IAPReceipt))).all()
    replay = await client.post("/v1/iap/verify", json={**body, "transaction_id": "different-client"},
                               headers={"X-User-Key": OTHER})
    assert replay.status_code == 200, replay.text
    balance = await db_session.scalar(select(UserCredits.credits).where(UserCredits.user_key == OTHER))
    assert (balance or 0) <= 3  # Only ordinary signup credit, never purchase credit.
    if product.startswith("subscription"):
        assert await credits_service.get_active_subscription(db_session, OTHER) is not None
    else:
        assert replay.json()["credits_added"] == 0


@pytest.mark.asyncio
async def test_claimed_purchase_restores_later_period_without_credits(client, db_session, monkeypatch):
    now = utcnow()
    sub = Subscription(user_key=OTHER, plan="basic", status="active", credits_per_month=5,
                       current_period_start=now-timedelta(days=10),
                       current_period_end=now+timedelta(days=2))
    db_session.add_all([sub, UserCredits(user_key=OTHER, credits=2)])
    assert await claim_purchase(db_session, "apple", "erased-renewal")
    await db_session.commit()
    verified = proof("subscription_basic", "erased-renewal")
    verified.raw["purchase_date_ms"] = int(now.replace(tzinfo=timezone.utc).timestamp()*1000)
    monkeypatch.setattr(iap_verifier, "verify_purchase", AsyncMock(return_value=verified))
    result = await client.post("/v1/iap/verify", json=dict(platform="apple",
        product_id="subscription_basic", transaction_id="restored-renewal", receipt_data="synthetic"),
        headers={"X-User-Key": OTHER})
    assert result.status_code == 200, result.text
    assert result.json()["credits_added"] == 0
    await db_session.refresh(sub)
    assert sub.current_period_end > now+timedelta(days=19)
    assert await db_session.scalar(select(UserCredits.credits).where(UserCredits.user_key == OTHER)) == 2


@pytest.mark.asyncio
async def test_claim_is_atomic_and_platform_scoped(db_session):
    assert await claim_purchase(db_session, "apple", "rollback")
    await db_session.rollback()
    assert await claim_purchase(db_session, "apple", "rollback")
    await db_session.commit()
    assert not await claim_purchase(db_session, "apple", "rollback")
    assert await claim_purchase(db_session, "google", "rollback")


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_restore_does_not_leave_source_entitlement_or_calendar_refill(client, db_session, monkeypatch, expired):
    now = utcnow()
    source = Subscription(user_key=OWNER, plan="basic", status="active" if expired else "cancelled",
                          credits_per_month=5, current_period_start=now-timedelta(days=31),
                          current_period_end=now+timedelta(days=-1 if expired else 20))
    db_session.add(source)
    await db_session.flush()
    source_id = source.id
    unrelated = Subscription(user_key=OWNER, plan="basic", status="cancelled", credits_per_month=5,
                             current_period_start=now, current_period_end=now+timedelta(days=40))
    db_session.add(unrelated)
    db_session.add(IAPReceipt(user_key=OWNER, platform="apple", product_id="subscription_basic",
                             transaction_id="restore", store_transaction_id="restore", status="verified",
                             subscription_id=source_id, payload={"granted_credits": 5}))
    await db_session.commit()
    async def verify(**kwargs):
        return proof(kwargs["product_id"], "restore", expired=expired)
    monkeypatch.setattr(iap_verifier, "verify_purchase", verify)
    result = await client.post("/v1/iap/verify", json=dict(platform="apple", product_id="subscription_basic",
        transaction_id="restore-new", receipt_data="synthetic"), headers={"X-User-Key": OTHER})
    assert result.status_code == 200, result.text
    await db_session.refresh(source)
    await db_session.refresh(unrelated)
    assert unrelated.status == "cancelled"
    assert source.calendar_refill_enabled is False
    if not expired:
        assert source.status == "expired"
    assert await periodic_credits.grant_due_refills(db_session) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["books.create", "books.series", "streak.today_generate"])
async def test_creditless_rejections_preserve_global_budget(db_session, monkeypatch, endpoint):
    db_session.add(UserCredits(user_key=OWNER, credits=0))
    await db_session.commit()
    consume = AsyncMock()
    monkeypatch.setattr(books, "consume_generation_budget", consume)
    for n in range(2):
        with pytest.raises(APIError) as error:
            await books._create_job_with_credit(db=db_session, user_key=OWNER, job_id=f"reject-{n}",
                current_step="queued", credit_description="test", budget_endpoint=endpoint)
        assert error.value.status_code == 402
    consume.assert_not_awaited()
    assert not (await db_session.scalars(select(Job))).all()


@pytest.mark.asyncio
async def test_budget_denial_rolls_back_credit_and_legitimate_job_uses_one_slot(db_session, monkeypatch):
    db_session.add(UserCredits(user_key=OWNER, credits=2))
    await db_session.commit()
    consume = AsyncMock(side_effect=APIError(429, "RATE_LIMIT_EXCEEDED", "budget"))
    monkeypatch.setattr(books, "consume_generation_budget", consume)
    with pytest.raises(APIError):
        await books._create_job_with_credit(db=db_session, user_key=OWNER, job_id="denied",
            current_step="queued", credit_description="test")
    assert await db_session.scalar(select(UserCredits.credits)) == 2
    assert await db_session.get(Job, "denied") is None
    consume.side_effect = None
    await books._create_job_with_credit(db=db_session, user_key=OWNER, job_id="allowed",
        current_step="queued", credit_description="test", idempotency_key="once")
    await books._create_job_with_credit(db=db_session, user_key=OWNER, job_id="retry",
        current_step="queued", credit_description="test", idempotency_key="once")
    assert consume.await_count == 2  # one denied admission, one successful; no retry
    assert await db_session.scalar(select(UserCredits.credits)) == 1


@pytest.mark.asyncio
async def test_foreign_series_rejected_by_route_and_worker(client, db_session, monkeypatch):
    from src.models.dto import SeriesNextRequest
    from src.services import orchestrator
    from tests.conftest import TestSessionLocal
    char = Character(id="own-char", user_key=OWNER, name="synthetic", master_description="rabbit",
                     appearance={}, clothing={}, personality_traits=[])
    db_session.add(char)
    await db_session.flush()
    db_session.add(Series(id="foreign-series", title="foreign", user_key=OTHER, character_id=char.id,
                          language="ko", target_age="5-7", style="watercolor"))
    await db_session.commit()
    consume = AsyncMock()
    monkeypatch.setattr(books, "consume_generation_budget", consume)
    body = dict(character_id=char.id, series_id="foreign-series", topic="synthetic adventure")
    response = await client.post("/v1/books/series", json=body, headers={"X-User-Key": OWNER})
    assert response.status_code == 403, response.text
    consume.assert_not_awaited()
    import src.core.database as database
    monkeypatch.setattr(database, "AsyncSessionLocal", TestSessionLocal)
    with pytest.raises(AuthorizationError):
        await orchestrator.start_series_generation("job-test", SeriesNextRequest(**body), OWNER,
            SimpleNamespace(name="synthetic"), None)
