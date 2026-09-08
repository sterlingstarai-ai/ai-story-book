"""Native notification trust boundary and paid-cycle reconciliation regressions."""

import base64
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.models.db import IAPReceipt, IapWebhookEvent
from src.routers.iap import _apply_native_event, _reapply_orphan_events, _store_period
from src.services import store_notifications as notices
from src.services.credits import SUBSCRIPTION_PLANS, credits_service
from src.services.iap_verifier import iap_verifier
from src.services.iap_verifier import IAPVerificationResult
from src.services.periodic_credits import _db_utcnow, periodic_credits
from src.services.store_notifications import StoreEvent


def ms(value):
    from datetime import timezone

    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


async def seed(db, *, elapsed=False):
    sub = await credits_service.create_subscription(db, "store-owner", "basic")
    sub.current_period_end = _db_utcnow() + timedelta(days=-1 if elapsed else 3)
    receipt = IAPReceipt(
        user_key="store-owner",
        platform="apple",
        product_id="subscription_basic",
        transaction_id="initial",
        store_transaction_id="initial",
        status="verified",
        subscription_id=sub.id,
        payload={
            "original_transaction_id": "original",
            "granted_credits": SUBSCRIPTION_PLANS["basic"]["credits_per_month"],
            "expires_date_ms": ms(sub.current_period_end),
        },
    )
    db.add(receipt)
    await db.commit()
    return sub, receipt


def renewal(**overrides):
    return StoreEvent(
        **{
            "platform": "apple",
            "transaction_id": "renewal-1",
            "product_id": "subscription_basic",
            "original_transaction_id": "original",
            "status": "active",
            "expires_date_ms": ms(_db_utcnow() + timedelta(days=33)),
            "environment": "Production",
            "grants_cycle": True,
            "signed_at_ms": 1000,
            **overrides,
        }
    )


@pytest.mark.asyncio
async def test_elapsed_store_subscription_never_refills_on_timer(db_session):
    sub, _ = await seed(db_session, elapsed=True)
    before = await credits_service.get_credits(db_session, "store-owner")
    assert await periodic_credits.grant_due_refills(db_session) == 0
    assert await credits_service.get_credits(db_session, "store-owner") == before
    assert sub.current_period_end < _db_utcnow()


@pytest.mark.asyncio
async def test_verified_renewal_grants_once_and_uses_exact_store_end(db_session):
    sub, _ = await seed(db_session)
    before = await credits_service.get_credits(db_session, "store-owner")
    event = renewal()
    await _apply_native_event(event, db_session)
    await _apply_native_event(event, db_session)
    assert (
        await credits_service.get_credits(db_session, "store-owner")
        == before + SUBSCRIPTION_PLANS["basic"]["credits_per_month"]
    )
    assert ms(sub.current_period_end) == event.expires_date_ms
    assert await db_session.scalar(select(func.count()).select_from(IAPReceipt)) == 2


@pytest.mark.asyncio
async def test_old_cycle_refund_does_not_expire_new_cycle(db_session):
    sub, initial = await seed(db_session)
    await _apply_native_event(renewal(), db_session)
    end = sub.current_period_end
    before = await credits_service.get_credits(db_session, "store-owner")
    event = renewal(
        transaction_id="initial",
        status="refunded",
        expires_date_ms=initial.payload["expires_date_ms"],
        grants_cycle=False,
    )
    await _apply_native_event(event, db_session)
    await _apply_native_event(event, db_session)
    assert sub.status == "active"
    assert sub.current_period_end == end
    assert (
        await credits_service.get_credits(db_session, "store-owner")
        == before - SUBSCRIPTION_PLANS["basic"]["credits_per_month"]
    )


@pytest.mark.asyncio
async def test_refund_current_cycle_cannot_be_reactivated_by_replay(db_session):
    sub, _ = await seed(db_session)
    event = renewal()
    await _apply_native_event(event, db_session)
    await _apply_native_event(renewal(status="refunded", signed_at_ms=2000), db_session)
    await _apply_native_event(event, db_session)
    assert sub.status == "expired"


@pytest.mark.asyncio
async def test_orphan_renewal_is_applied_after_matching_initial_verification(db_session):
    event = renewal()
    assert (await _apply_native_event(event, db_session))["status"] == "accepted_orphan"
    sub, initial = await seed(db_session)
    before = await credits_service.get_credits(db_session, "store-owner")
    await _reapply_orphan_events(db_session, initial)
    assert (
        await credits_service.get_credits(db_session, "store-owner")
        == before + SUBSCRIPTION_PLANS["basic"]["credits_per_month"]
    )
    assert (await db_session.scalar(select(IapWebhookEvent))).applied
    assert ms(sub.current_period_end) == event.expires_date_ms


@pytest.mark.asyncio
async def test_old_cancellation_cannot_cancel_new_cycle(db_session):
    sub, initial = await seed(db_session)
    await _apply_native_event(renewal(), db_session)
    await _apply_native_event(
        renewal(
            transaction_id="initial",
            status="cancelled",
            expires_date_ms=initial.payload["expires_date_ms"],
        ),
        db_session,
    )
    assert sub.status == "active"


def test_restore_keeps_actual_remaining_period():
    sub = SimpleNamespace(current_period_end=_db_utcnow() + timedelta(days=30))
    expiry = ms(_db_utcnow() + timedelta(hours=2))
    _store_period(sub, SimpleNamespace(expires_date_ms=expiry, raw={}))
    assert ms(sub.current_period_end) == expiry


@pytest.mark.asyncio
async def test_apple_v2_notification_uses_nested_verified_transaction(monkeypatch):
    transaction = SimpleNamespace(
        transactionId="renewal-1",
        originalTransactionId="original",
        productId="subscription_basic",
        revocationDate=None,
        expiresDate=123456,
        purchaseDate=123,
        environment="Production",
    )
    decoded = SimpleNamespace(
        notificationType="DID_RENEW",
        data=SimpleNamespace(signedTransactionInfo="inner", signedRenewalInfo=None),
        signedDate=100,
    )
    decoder = AsyncMock(return_value=decoded)
    monkeypatch.setattr(notices, "_apple_decode", decoder)
    tx_verifier = AsyncMock(return_value=transaction)
    monkeypatch.setattr(notices, "verify_apple_transaction", tx_verifier)
    event = await notices.decode_apple_notification("outer")
    tx_verifier.assert_awaited_once_with("inner")
    assert event.grants_cycle and event.original_transaction_id == "original"


@pytest.mark.asyncio
async def test_storekit2_jws_uses_signed_verification_not_verify_receipt(monkeypatch):
    transaction = SimpleNamespace(
        transactionId="tx",
        productId="credit_pack_1",
        revocationDate=None,
        environment="Production",
        expiresDate=None,
        originalTransactionId="tx",
        purchaseDate=123,
        bundleId="app",
    )
    monkeypatch.setattr(notices, "verify_apple_transaction", AsyncMock(return_value=transaction))
    legacy = AsyncMock(side_effect=AssertionError("must not call legacy endpoint"))
    monkeypatch.setattr(iap_verifier, "_post_apple_receipt", legacy)
    result = await iap_verifier._verify_apple(
        mode="strict",
        product_id="credit_pack_1",
        transaction_id="tx",
        receipt_data="header.payload.signature",
    )
    assert result.source == "apple_signed_transaction"
    legacy.assert_not_called()
    transaction.revocationDate = 100
    with pytest.raises(ValidationError):
        await iap_verifier._verify_apple(
            mode="strict",
            product_id="credit_pack_1",
            transaction_id="tx",
            receipt_data="header.payload.signature",
        )


@pytest.mark.asyncio
async def test_google_push_authentication_is_required_before_publisher_call(client, monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(notices, "google_subscription", fetch)
    response = await client.post(
        "/v1/iap/notifications/google",
        json={
            "message": {"data": "e30=", "messageId": "m"},
            "subscription": "projects/test/subscriptions/rtdn",
        },
    )
    assert response.status_code == 403
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_apple_notification_rejects_unconfigured_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "apple_root_ca_paths", "")
    response = await client.post(
        "/v1/iap/notifications/apple", json={"signedPayload": "header.payload.signature"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_google_rtdn_uses_publisher_state_not_notification_claim(monkeypatch):
    monkeypatch.setattr(settings, "google_play_package_name", "our.app")
    raw = {
        "packageName": "our.app",
        "subscriptionNotification": {"purchaseToken": "opaque-token", "notificationType": 2},
    }
    envelope = {"message": {"data": base64.b64encode(json.dumps(raw).encode()).decode()}}
    fetch = AsyncMock(
        return_value={
            "subscriptionState": "SUBSCRIPTION_STATE_EXPIRED",
            "latestOrderId": "GPA.order..1",
            "lineItems": [
                {"productId": "subscription_basic", "expiryTime": "2026-01-01T00:00:00Z"}
            ],
        }
    )
    monkeypatch.setattr(notices, "google_subscription", fetch)
    event = await notices.decode_google_notification(envelope)
    assert event.status == "expired" and not event.grants_cycle
    assert event.original_transaction_id == "GPA.order"
    assert "opaque-token" not in json.dumps(event.persisted_payload())


@pytest.mark.asyncio
async def test_mismatched_google_package_is_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(settings, "google_play_package_name", "our.app")
    encoded = base64.b64encode(json.dumps({"packageName": "another.app"}).encode()).decode()
    fetch = AsyncMock()
    monkeypatch.setattr(notices, "google_subscription", fetch)
    with pytest.raises(ValidationError):
        await notices.decode_google_notification({"message": {"data": encoded}})
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_tier_upgrade_downgrade_loop_does_not_mint_more_credits(db_session):
    _, _ = await seed(db_session)
    before = await credits_service.get_credits(db_session, "store-owner")
    expiry = ms(_db_utcnow() + timedelta(days=3))
    start = ms(_db_utcnow())
    await _apply_native_event(
        renewal(
            transaction_id="upgrade",
            product_id="subscription_premium",
            purchased_at_ms=start,
            expires_date_ms=expiry,
        ),
        db_session,
    )
    await _apply_native_event(
        renewal(
            transaction_id="downgrade",
            product_id="subscription_basic",
            purchased_at_ms=start,
            expires_date_ms=expiry,
        ),
        db_session,
    )
    await _apply_native_event(
        renewal(
            transaction_id="upgrade-again",
            product_id="subscription_premium",
            purchased_at_ms=start,
            expires_date_ms=expiry,
        ),
        db_session,
    )
    difference = (
        SUBSCRIPTION_PLANS["premium"]["credits_per_month"]
        - SUBSCRIPTION_PLANS["basic"]["credits_per_month"]
    )
    assert await credits_service.get_credits(db_session, "store-owner") == before + difference


@pytest.mark.asyncio
async def test_real_apple_library_rejects_unsigned_transaction(monkeypatch):
    monkeypatch.setattr(settings, "apple_notification_environment", "Production")
    monkeypatch.setattr(settings, "apple_bundle_id", "com.storybook.aiStoryBook")
    monkeypatch.setattr(settings, "apple_app_id", 123456)
    monkeypatch.setattr(settings, "apple_root_ca_paths", "")
    with pytest.raises(Exception) as caught:
        await notices.verify_apple_transaction("header.payload.signature")
    assert caught.value.__class__.__name__ == "AuthorizationError"


@pytest.mark.asyncio
async def test_consumable_restore_keeps_refund_on_original_owner(
    client, db_session, monkeypatch, headers
):
    row = IAPReceipt(
        user_key="original-buyer",
        platform="apple",
        product_id="credit_pack_5",
        transaction_id="paid-pack",
        store_transaction_id="paid-pack",
        status="verified",
    )
    db_session.add(row)
    await db_session.commit()
    monkeypatch.setattr(
        iap_verifier,
        "verify_purchase",
        AsyncMock(
            return_value=IAPVerificationResult(
                verified=True,
                source="apple_store",
                environment="Production",
                store_transaction_id="paid-pack",
                store_product_id="credit_pack_5",
                raw={},
            )
        ),
    )
    response = await client.post(
        "/v1/iap/verify",
        headers=headers,
        json={
            "platform": "apple",
            "product_id": "credit_pack_5",
            "transaction_id": "copied-receipt",
            "receipt_data": "AAAA",
        },
    )
    assert response.status_code == 200
    assert response.json()["credits_added"] == 0
    await db_session.refresh(row)
    assert row.user_key == "original-buyer"


def test_google_purchase_with_unknown_completion_state_fails_closed():
    with pytest.raises(ValidationError):
        iap_verifier._assert_google_purchase_valid(
            google_data={"orderId": "GPA.1"}, expected_transaction_id="GPA.1", is_subscription=False
        )


def test_legacy_apple_secret_does_not_advertise_unconfigured_storekit2(monkeypatch):
    from src.core.billing_feature import purchase_capabilities

    monkeypatch.setattr(settings, "purchases_enabled", True)
    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", "test")
    monkeypatch.setattr(settings, "apple_bundle_id", "com.storybook.aiStoryBook")
    monkeypatch.setattr(settings, "apple_app_id", 0)
    monkeypatch.setattr(settings, "apple_notification_environment", "Production")
    assert purchase_capabilities()["apple_purchases_supported"] is False


def test_google_licensed_review_requires_explicit_product_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "enable_test_hooks", False)
    monkeypatch.setattr(settings, "review_sandbox_allowlist", "credit_pack_1")
    args = {
        "google_data": {"orderId": "GPA.1", "purchaseState": 0, "purchaseType": 0},
        "expected_transaction_id": "GPA.1",
        "is_subscription": False,
    }
    iap_verifier._assert_google_purchase_valid(**args, expected_product_id="credit_pack_1")
    with pytest.raises(ValidationError):
        iap_verifier._assert_google_purchase_valid(**args, expected_product_id="credit_pack_10")
