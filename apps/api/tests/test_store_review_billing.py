"""Review entitlement isolation with the real account recovery and settlement routes."""

import base64
from datetime import timedelta, timezone
import json
import secrets
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.utils import utcnow
from src.models.db import AccountIdentity, IAPReceipt, IapWebhookEvent
from src.routers.iap import CREDIT_PACK_PRODUCTS, SUBSCRIPTION_PRODUCTS, _apply_native_event
from src.services import store_notifications as notices
from src.services.account_recovery import credential_hash
from src.services.credits import SUBSCRIPTION_PLANS, credits_service
from src.services.privacy_journal import CredentialState, PrivacyJournal
from src.services.privacy_journal_transaction import prepare_transaction_event, publish_committed_event
from tests.test_privacy_journal_outbox import FakeStore


async def claim_review_account(client, db, monkeypatch, product):
    slot = str(uuid.uuid4())
    passcode = "ASB-R1-" + secrets.token_urlsafe(32)
    device = "asb_device_" + secrets.token_urlsafe(32)
    monkeypatch.setattr(settings, "generation_access_mode", "open")
    monkeypatch.setattr(settings, "review_sandbox_allowlist", product)
    monkeypatch.setattr(settings, "store_review_account_slots", slot)
    monkeypatch.setattr(settings, "store_review_pass_hash", credential_hash(passcode, kind="store-review"))
    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    db.info["privacy_journal"] = PrivacyJournal(FakeStore(), b"k" * 32)
    reserved = credential_hash(slot, kind="store-review-reservation")
    db.add(AccountIdentity(user_key=slot, device_key_hash=reserved))
    journal_event = await prepare_transaction_event(
        db, user_key=slot, action="credential_revoke", credential_state=CredentialState(reserved, None, None, None)
    )
    await db.commit()
    await publish_committed_event(db, journal_event)
    response = await client.post("/v1/account/recover", json={"recovery_code": passcode, "new_user_key": device})
    assert response.status_code == 200
    return slot, {"X-User-Key": device}


def signed_transaction(product, transaction_id, environment):
    now = utcnow().replace(tzinfo=timezone.utc)
    return SimpleNamespace(
        transactionId=transaction_id, originalTransactionId=transaction_id, productId=product,
        revocationDate=None, purchaseDate=int(now.timestamp() * 1000),
        expiresDate=int((now + timedelta(days=30)).timestamp() * 1000) if product in SUBSCRIPTION_PRODUCTS else None,
        environment=environment, bundleId="our.app",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("product", [*CREDIT_PACK_PRODUCTS, *SUBSCRIPTION_PRODUCTS])
async def test_review_storekit_products_require_bound_device_and_grant_once(client, db_session, monkeypatch, product):
    slot, headers = await claim_review_account(client, db_session, monkeypatch, product)
    tx = signed_transaction(product, "store-transaction", "Sandbox")
    store = AsyncMock(return_value=tx)
    monkeypatch.setattr(notices, "verify_apple_transaction", store)
    body = {"platform": "apple", "product_id": product, "transaction_id": tx.transactionId,
            "receipt_data": "sample.signed.transaction"}
    assert (await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": slot})).status_code == 401
    before = await credits_service.get_credits(db_session, slot)
    assert (await client.post("/v1/iap/verify", json=body, headers=headers)).status_code == 200
    store.assert_awaited_with(body["receipt_data"], environment="Sandbox")
    assert (await client.post("/v1/iap/verify", json=body, headers=headers)).json()["credits_added"] == 0
    expected = CREDIT_PACK_PRODUCTS.get(product) or SUBSCRIPTION_PLANS[SUBSCRIPTION_PRODUCTS[product]]["credits_per_month"]
    assert await credits_service.get_credits(db_session, slot) == before + expected
    assert (await db_session.scalar(select(IAPReceipt))).platform == "apple_sandbox"


@pytest.mark.asyncio
async def test_review_orphan_with_same_id_as_paid_purchase_only_reconciles_review_receipt(
    client, db_session, monkeypatch, headers,
):
    product = "credit_pack_5"
    slot, reviewer = await claim_review_account(client, db_session, monkeypatch, product)
    paid_before = await credits_service.get_credits(db_session, headers["X-User-Key"])
    review_before = await credits_service.get_credits(db_session, slot)
    def transaction(signed, *, environment=None):
        return signed_transaction(product, "same-order-id", environment or "Production")
    monkeypatch.setattr(notices, "verify_apple_transaction", AsyncMock(side_effect=transaction))
    event = notices.StoreEvent(platform="apple", transaction_id="same-order-id", product_id=product,
                               status="refunded", environment="Sandbox")
    assert (await _apply_native_event(event, db_session))["status"] == "accepted_orphan"
    body = {"platform": "apple", "product_id": product, "transaction_id": event.transaction_id,
            "receipt_data": "sample.signed.transaction"}
    paid = await client.post("/v1/iap/verify", json=body, headers=headers)
    assert paid.status_code == 200 and paid.json()["credits_added"] == 5
    pending = await db_session.scalar(select(IapWebhookEvent))
    assert pending.platform == "apple_sandbox" and not pending.applied
    demo = await client.post("/v1/iap/verify", json=body, headers=reviewer)
    assert demo.status_code == 200 and demo.json()["credits_added"] == 0
    await db_session.refresh(pending)
    assert pending.applied
    assert await credits_service.get_credits(db_session, headers["X-User-Key"]) == paid_before + 5
    assert await credits_service.get_credits(db_session, slot) == review_before


@pytest.mark.asyncio
@pytest.mark.parametrize("product_type,field", [(1, "testPurchase"), (2, "testPurchaseContext")])
async def test_google_voided_purchase_uses_publisher_environment(monkeypatch, product_type, field):
    monkeypatch.setattr(settings, "google_play_package_name", "our.app")
    publisher = AsyncMock(return_value={field: {}})
    monkeypatch.setattr(notices, "_google_purchase_v2", publisher)
    payload = {"packageName": "our.app", "voidedPurchaseNotification": {
        "purchaseToken": "token", "orderId": "order", "productType": product_type, "refundType": 1}}
    envelope = {"message": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}}
    event = await notices.decode_google_notification(envelope)
    assert event.environment == "Sandbox" and event.status == "refunded" and not event.grants_cycle
    assert "token" not in json.dumps(event.persisted_payload())


@pytest.mark.asyncio
async def test_private_capabilities_offer_only_apple_to_current_claimed_review_device(
    client, db_session, monkeypatch, headers
):
    product = "credit_pack_1"
    slot, reviewer = await claim_review_account(client, db_session, monkeypatch, product)
    monkeypatch.setattr(settings, "purchases_enabled", False)
    monkeypatch.setattr(settings, "apple_app_id", 123456)
    monkeypatch.setattr(settings, "apple_bundle_id", "our.app")
    monkeypatch.setattr(settings, "google_play_package_name", "our.app")
    monkeypatch.setattr(settings, "google_play_access_token", "test")
    monkeypatch.setattr(settings, "google_rtdn_audience", "https://example.test")
    monkeypatch.setattr(settings, "google_rtdn_service_account_email", "test@example.test")
    endpoint = "/v1/config/capabilities"
    # This build queries all five products together. Partial configuration cannot advertise checkout.
    assert not (await client.get(endpoint, headers=reviewer)).json()["purchases_supported"]
    monkeypatch.setattr(settings, "review_sandbox_allowlist", ",".join([*CREDIT_PACK_PRODUCTS, *SUBSCRIPTION_PRODUCTS]))
    demo = await client.get(endpoint, headers=reviewer)
    assert demo.json()["purchases_supported"] and demo.json()["apple_purchases_supported"]
    assert not demo.json()["google_purchases_supported"]
    assert "no-store" in demo.headers["cache-control"] and "private" in demo.headers["cache-control"]
    assert "x-user-key" in demo.headers["vary"].lower()
    for anonymous in ({}, headers, {"X-User-Key": slot}, {"X-User-Key": "asb_device_invalid"}):
        response = await client.get(endpoint, headers=anonymous)
        assert response.status_code == 200
        assert not response.json()["purchases_supported"]
        assert "no-store" in response.headers["cache-control"]

    another = "asb_device_" + secrets.token_urlsafe(32)
    code = (await client.post("/v1/account/recovery-code", headers=reviewer)).json()["recovery_code"]
    assert (await client.post("/v1/account/recover", json={"recovery_code": code, "new_user_key": another})).status_code == 200
    assert not (await client.get(endpoint, headers=reviewer)).json()["apple_purchases_supported"]
    assert (await client.get(endpoint, headers={"X-User-Key": another})).json()["apple_purchases_supported"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_signature", [False, True])
async def test_apple_notification_review_fallback_only_retries_verified_environment_mismatch(
    monkeypatch, invalid_signature,
):
    from appstoreserverlibrary.signed_data_verifier import VerificationException, VerificationStatus
    from src.core.exceptions import AuthorizationError

    monkeypatch.setattr(settings, "apple_notification_environment", "Production")
    monkeypatch.setattr(settings, "review_sandbox_allowlist", "credit_pack_1")
    monkeypatch.setattr(settings, "store_review_account_slots", str(uuid.uuid4()))
    environments = []
    def factory(env):
        environments.append(env)
        def verify(signed):
            if invalid_signature:
                raise VerificationException(VerificationStatus.INVALID_CERTIFICATE)
            if env == "Production":
                raise VerificationException(VerificationStatus.INVALID_ENVIRONMENT)
            return object()
        return SimpleNamespace(verify_and_decode_notification=verify)
    monkeypatch.setattr(notices, "apple_verifier", factory)
    if invalid_signature:
        with pytest.raises(AuthorizationError):
            await notices._apple_decode("sample", "verify_and_decode_notification", allow_review_fallback=True)
        assert environments == ["Production"]
    else:
        await notices._apple_decode("sample", "verify_and_decode_notification", allow_review_fallback=True)
        assert environments == ["Production", "Sandbox"]


@pytest.mark.asyncio
async def test_known_google_refund_still_settles_when_publisher_token_is_no_longer_available(
    client, db_session, monkeypatch,
):
    order = "GPA.refunded-order"
    token = "stored-purchase-token"
    monkeypatch.setattr(settings, "google_play_package_name", "our.app")
    monkeypatch.setattr(notices, "_google_purchase_v2", AsyncMock(side_effect=AssertionError("no re-fetch")))
    monkeypatch.setattr("src.routers.iap.verify_google_push_identity", AsyncMock())
    owner = str(uuid.uuid4())
    db_session.add(IAPReceipt(platform="google", user_key=owner, store_transaction_id=order,
                              transaction_id=order, product_id="credit_pack_1", purchase_token=token,
                              payload={"verification_environment": "Production"}, status="verified"))
    await db_session.commit()
    payload = {"packageName": "our.app", "voidedPurchaseNotification": {
        "purchaseToken": token, "orderId": order, "productType": 2, "refundType": 1}}
    response = await client.post("/v1/iap/notifications/google", json={
        "message": {"data": base64.b64encode(json.dumps(payload).encode()).decode(), "messageId": "one"},
        "subscription": "projects/test/subscriptions/test"})
    assert response.status_code == 200, response.text
    assert (await db_session.scalar(select(IAPReceipt))).status == "refunded"
