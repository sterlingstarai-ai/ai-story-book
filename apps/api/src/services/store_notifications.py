"""Authenticated native store notifications; no client-supplied entitlement decisions.

Apple JWS is verified with Apple's maintained library and pinned Apple roots.
Google Pub/Sub OIDC proves the sender; Publisher API proves the purchase state.
Only normalized, non-secret transaction metadata is persisted by the router.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from src.core.config import settings
from src.core.exceptions import AuthorizationError, ValidationError


@dataclass
class StoreEvent:
    platform: str
    transaction_id: str
    product_id: str
    status: str
    original_transaction_id: str | None = None
    expires_date_ms: int | None = None
    purchased_at_ms: int | None = None
    signed_at_ms: int | None = None
    environment: str | None = None
    # True only when the store reports a successfully paid subscription cycle.
    grants_cycle: bool = False
    purchase_token: str | None = None
    linked_purchase_token: str | None = None

    def persisted_payload(self) -> dict:
        values = asdict(self)
        values.pop("purchase_token", None)
        values.pop("linked_purchase_token", None)
        return {"native_store_event": values}


def apple_verifier():
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

    env = settings.apple_notification_environment
    if env not in {"Production", "Sandbox"}:
        raise AuthorizationError("Apple 알림 환경이 구성되지 않았습니다.")
    paths = [p.strip() for p in settings.apple_root_ca_paths.split(",") if p.strip()]
    if not paths:
        bundled = Path(__file__).resolve().parent.parent / "resources" / "apple"
        paths = [str(bundled / name) for name in ("AppleRootCA-G2.cer", "AppleRootCA-G3.cer")]
    if (
        not paths
        or not settings.apple_bundle_id
        or (env == "Production" and (settings.apple_app_id or 0) <= 0)
    ):
        raise AuthorizationError("Apple 서명 검증이 구성되지 않았습니다.")
    try:
        roots = [Path(path).read_bytes() for path in paths]
        return SignedDataVerifier(
            roots, True, Environment(env), settings.apple_bundle_id, settings.apple_app_id
        )
    except (OSError, ValueError) as exc:
        raise AuthorizationError("Apple 서명 검증 설정을 읽을 수 없습니다.") from exc


async def _apple_decode(signed: str, method: str):
    # Decode only after certificate-chain / signature / bundle / environment checks.
    verifier = apple_verifier()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(getattr(verifier, method), signed), timeout=30
        )
    except Exception as exc:
        raise AuthorizationError("Apple 서명을 확인할 수 없습니다.") from exc


async def verify_apple_transaction(signed: str):
    return await _apple_decode(signed, "verify_and_decode_signed_transaction")


def _enum(value: Any) -> str | None:
    return getattr(value, "value", value)


async def decode_apple_notification(signed: str) -> StoreEvent | None:
    notification = await _apple_decode(signed, "verify_and_decode_notification")
    kind = _enum(notification.notificationType)
    if kind == "TEST":
        return None
    data = notification.data
    if data is None or not data.signedTransactionInfo:
        return None  # Summary / consumption-request events do not grant access.
    transaction = await verify_apple_transaction(data.signedTransactionInfo)
    renewal = None
    if data.signedRenewalInfo:
        renewal = await _apple_decode(data.signedRenewalInfo, "verify_and_decode_renewal_info")
    status = {
        "SUBSCRIBED": "active",
        "DID_RENEW": "active",
        "RENEWAL_EXTENDED": "active",
        "REFUND": "refunded",
        "REVOKE": "refunded",
        "EXPIRED": "expired",
        "GRACE_PERIOD_EXPIRED": "expired",
    }.get(kind)
    if kind == "DID_CHANGE_RENEWAL_STATUS" and renewal is not None:
        status = "active" if _enum(renewal.autoRenewStatus) == 1 else "cancelled"
    if kind == "DID_FAIL_TO_RENEW":
        # Preserve a verified grace period, otherwise stop the expired entitlement.
        grace = getattr(renewal, "gracePeriodExpiresDate", None)
        status = "active" if grace else "expired"
    else:
        grace = None
    if status is None:
        return None
    if not transaction.transactionId or not transaction.productId:
        raise ValidationError("Apple 알림에 거래 식별자가 없습니다.")
    if transaction.revocationDate:
        status = "refunded"
    return StoreEvent(
        platform="apple",
        transaction_id=transaction.transactionId,
        original_transaction_id=transaction.originalTransactionId,
        product_id=transaction.productId,
        status=status,
        expires_date_ms=grace or transaction.expiresDate,
        purchased_at_ms=transaction.purchaseDate,
        signed_at_ms=notification.signedDate,
        environment=_enum(transaction.environment),
        grants_cycle=kind in {"SUBSCRIBED", "DID_RENEW"} and status == "active",
    )


async def verify_google_push_identity(authorization: str | None) -> None:
    audience = settings.google_rtdn_audience
    email = settings.google_rtdn_service_account_email
    if not audience or not email or not authorization or not authorization.startswith("Bearer "):
        raise AuthorizationError("Google 알림 인증이 필요합니다.")
    token = authorization[7:]
    if len(token) > 10000:
        raise AuthorizationError("Google 알림 인증이 올바르지 않습니다.")

    def verify():
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import verify_oauth2_token

        transport = Request()

        def request(*args, **kwargs):
            kwargs["timeout"] = 10
            return transport(*args, **kwargs)

        return verify_oauth2_token(token, request, audience=audience)

    try:
        claims = await asyncio.wait_for(asyncio.to_thread(verify), timeout=20)
    except Exception as exc:
        raise AuthorizationError("Google 알림 서명을 확인할 수 없습니다.") from exc
    if claims.get("email") != email or claims.get("email_verified") is not True:
        raise AuthorizationError("허용되지 않은 Google 알림 발신자입니다.")


def _rfc3339_ms(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return int(stamp.astimezone(timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


async def google_subscription(token: str) -> dict:
    from src.services.iap_verifier import iap_verifier

    access = await asyncio.to_thread(iap_verifier._resolve_google_access_token)
    package = settings.google_play_package_name
    if not access or not package:
        raise AuthorizationError("Google Publisher API가 구성되지 않았습니다.")
    base = settings.google_play_verify_base_url.rstrip("/")
    url = f"{base}/androidpublisher/v3/applications/{quote(package, safe='')}/purchases/subscriptionsv2/tokens/{quote(token, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {access}"})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid object")
        return data
    except (httpx.HTTPError, ValueError) as exc:
        # No raw exception: request URLs include the reusable purchase token.
        raise ValidationError("Google 구매 상태를 다시 확인할 수 없습니다.") from exc


async def decode_google_notification(envelope: dict) -> StoreEvent | None:
    message = envelope.get("message")
    encoded = message.get("data") if isinstance(message, dict) else None
    try:
        if not isinstance(encoded, str) or len(encoded) > 32000:
            raise ValueError("invalid envelope")
        data = json.loads(base64.b64decode(encoded, validate=True))
        if (
            not isinstance(data, dict)
            or data.get("packageName") != settings.google_play_package_name
        ):
            raise ValueError("package mismatch")
    except (ValueError, binascii.Error, TypeError) as exc:
        raise ValidationError("Google 알림 형식이 올바르지 않습니다.") from exc
    if "testNotification" in data:
        return None
    notice = data.get("subscriptionNotification")
    if not isinstance(notice, dict):
        one_time = data.get("oneTimeProductNotification")
        if isinstance(one_time, dict) and one_time.get("notificationType") == 2:
            from src.services.iap_verifier import iap_verifier

            token, product = one_time.get("purchaseToken"), one_time.get("sku")
            if not isinstance(token, str) or not isinstance(product, str) or len(token) > 500:
                raise ValidationError("Google 취소 알림의 구매 식별자가 없습니다.")
            access = await asyncio.to_thread(iap_verifier._resolve_google_access_token)
            if not access:
                raise AuthorizationError("Google Publisher API가 구성되지 않았습니다.")
            purchase = await iap_verifier._fetch_google_purchase(
                package_name=settings.google_play_package_name or "",
                product_id=product,
                purchase_token=token,
                access_token=access,
                is_subscription=False,
            )
            if purchase.get("purchaseState") != 1:
                return None
            order = purchase.get("orderId")
            if not isinstance(order, str) or not order:
                raise ValidationError("Google 취소 거래의 주문 번호가 없습니다.")
            return StoreEvent(
                platform="google",
                transaction_id=order,
                product_id=product,
                status="refunded",
                purchase_token=token,
            )
        # Voided purchases carry a store-authenticated order ID. No grant is ever
        # made from this message; reconciliation can only revoke that exact receipt.
        voided = data.get("voidedPurchaseNotification")
        if isinstance(voided, dict) and isinstance(voided.get("orderId"), str):
            if voided.get("refundType", 1) != 1:
                raise ValidationError("부분 환불은 수량을 확인한 후 처리해야 합니다.")
            return StoreEvent(
                platform="google",
                transaction_id=voided["orderId"],
                product_id="",
                status="refunded",
                purchase_token=voided.get("purchaseToken"),
                original_transaction_id=voided["orderId"].split("..", 1)[0],
            )
        return None
    token = notice.get("purchaseToken")
    if not isinstance(token, str) or not token or len(token) > 500:
        raise ValidationError("Google 알림에 구매 토큰이 없습니다.")
    purchase = await google_subscription(token)
    items = purchase.get("lineItems")
    if isinstance(items, list) and len(items) > 1:
        # A deferred replacement has no successful order yet, and therefore must
        # not displace the currently owned item before the next paid renewal.
        items = [
            item for item in items if isinstance(item, dict) and item.get("latestSuccessfulOrderId")
        ]
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise ValidationError("Google 구독 상품을 하나로 확인할 수 없습니다.")
    item = items[0]
    order = item.get("latestSuccessfulOrderId") or purchase.get("latestOrderId")
    product = item.get("productId")
    if not isinstance(order, str) or not isinstance(product, str):
        raise ValidationError("Google 구독 거래 식별자가 없습니다.")
    state = purchase.get("subscriptionState")
    status = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "active",
        "SUBSCRIPTION_STATE_CANCELED": "cancelled",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_ON_HOLD": "expired",
        "SUBSCRIPTION_STATE_PAUSED": "expired",
    }.get(state)
    if status is None:
        return None  # pending purchase is not paid
    return StoreEvent(
        platform="google",
        transaction_id=order,
        product_id=product,
        status=status,
        original_transaction_id=order.split("..", 1)[0],
        purchase_token=token,
        linked_purchase_token=purchase.get("linkedPurchaseToken"),
        expires_date_ms=_rfc3339_ms(item.get("expiryTime")),
        purchased_at_ms=_rfc3339_ms(purchase.get("startTime")),
        environment="Sandbox" if "testPurchase" in purchase else "Production",
        # The current successful order is authoritative even for a delayed RTDN.
        grants_cycle=state == "SUBSCRIPTION_STATE_ACTIVE",
    )
