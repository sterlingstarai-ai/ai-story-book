"""IAP 결제 보안 하드닝 회귀 테스트.

감사 트리아지 F1/F2/F3/F4 + 비평 N1/N2 의 재발 방지:
- F2: 리플레이(같은 영수증, 다른 client transaction_id) 차단 — store_transaction_id 정본 dedup.
- F3: 보상 지급 + 영수증 기록이 단일 트랜잭션(더블그랜트 방지).
- F4: 재설치/기기 변경 시 구독 복원(권한 재연결).
- N1: 환불 웹훅이 구독 권한을 회수하고 크레딧을 클로백.
- F1/N2: 운영(testing=False) IAP 미설정 시 /health/ready 차단.
"""

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.models.db import IAPReceipt, Subscription, UserCredits
from src.services.credits import credits_service
from src.services.iap_verifier import IAPVerificationResult, iap_verifier


def _fake_verification(product_id: str, store_txn: str) -> IAPVerificationResult:
    return IAPVerificationResult(
        verified=True,
        source="apple_store",
        environment="Production",
        store_transaction_id=store_txn,
        store_product_id=product_id,
        raw={},
    )


async def _balance(db_session, user_key: str) -> int:
    db_session.expire_all()
    row = (
        await db_session.execute(
            select(UserCredits.credits).where(UserCredits.user_key == user_key)
        )
    ).scalar_one_or_none()
    return row or 0


# ───────────────────────── F2: 리플레이 차단 ─────────────────────────
@pytest.mark.asyncio
async def test_replay_with_different_transaction_id_is_blocked(
    client, headers, db_session, monkeypatch
):
    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-REPLAY-FIXED")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    body = {
        "platform": "apple",
        "product_id": "credit_pack_10",
        "transaction_id": "client-tx-1",
        "receipt_data": "AAAA",
    }
    r1 = await client.post("/v1/iap/verify", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "verified"
    assert r1.json()["credits_added"] == 10
    bal_after_1 = await _balance(db_session, headers["X-User-Key"])

    # 같은 영수증(store id 동일)을 다른 client transaction_id로 재제출 → 차단.
    body2 = {**body, "transaction_id": "client-tx-2"}
    r2 = await client.post("/v1/iap/verify", json=body2, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "already_processed"
    assert r2.json()["credits_added"] == 0
    assert await _balance(db_session, headers["X-User-Key"]) == bal_after_1


# ───────────────────────── F3: 원자적 지급 ─────────────────────────
@pytest.mark.asyncio
async def test_grant_and_receipt_are_atomic_no_double_grant(
    client, headers, db_session, monkeypatch
):
    """같은 store id로 두 번 호출해도 크레딧은 1회만 지급되고 영수증도 1건만."""

    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-ATOMIC-1")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)
    body = {
        "platform": "apple",
        "product_id": "credit_pack_5",
        "transaction_id": "tx-a",
        "receipt_data": "AAAA",
    }
    await client.post("/v1/iap/verify", json={**body, "transaction_id": "tx-a"}, headers=headers)
    bal1 = await _balance(db_session, headers["X-User-Key"])
    await client.post("/v1/iap/verify", json={**body, "transaction_id": "tx-b"}, headers=headers)
    bal2 = await _balance(db_session, headers["X-User-Key"])
    assert bal2 == bal1  # 더블그랜트 없음

    receipts = (
        await db_session.execute(
            select(IAPReceipt).where(IAPReceipt.store_transaction_id == "STORE-ATOMIC-1")
        )
    ).scalars().all()
    assert len(receipts) == 1


# ───────────────────────── F4: 복원 ─────────────────────────
@pytest.mark.asyncio
async def test_subscription_restore_relinks_to_new_user(
    client, db_session, monkeypatch
):
    # 기존 기기(OLD)에서 산 구독 영수증을 미리 기록.
    old = IAPReceipt(
        user_key="old-device-user",
        platform="apple",
        product_id="subscription_basic",
        transaction_id="orig-tx",
        store_transaction_id="STORE-SUB-RESTORE",
        status="verified",
        payload={},
    )
    db_session.add(old)
    await db_session.commit()

    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-SUB-RESTORE")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    new_user = "11111111-2222-3333-4444-555555555555"
    body = {
        "platform": "apple",
        "product_id": "subscription_basic",
        "transaction_id": "restored-tx",
        "receipt_data": "AAAA",
        "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "restored"
    assert r.json()["plan"] == "basic"

    # 새 사용자에게 활성 구독이 연결되었는지.
    sub = await credits_service.get_active_subscription(db_session, new_user)
    assert sub is not None
    assert sub.plan == "basic"


# ───────────────────────── N1: 환불 ─────────────────────────
@pytest.mark.asyncio
async def test_refund_webhook_revokes_subscription(client, db_session):
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "refund-sub-user"
    sub = Subscription(
        user_key=user,
        plan="premium",
        status="active",
        credits_per_month=50,
        current_period_start=utcnow(),
        current_period_end=utcnow() + timedelta(days=30),
    )
    db_session.add(sub)
    db_session.add(
        IAPReceipt(
            user_key=user,
            platform="apple",
            product_id="subscription_premium",
            transaction_id="refund-sub-tx",
            store_transaction_id="STORE-REFUND-SUB",
            status="verified",
            payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "refund-sub-tx", "status": "refunded"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    refreshed = (
        await db_session.execute(select(Subscription).where(Subscription.user_key == user))
    ).scalar_one()
    assert refreshed.status == "expired"
    assert refreshed.current_period_end < utcnow()


@pytest.mark.asyncio
async def test_refund_webhook_claws_back_credit_pack(client, db_session):
    user = "refund-cp-user"
    db_session.add(UserCredits(user_key=user, credits=10, total_purchased=10))
    db_session.add(
        IAPReceipt(
            user_key=user,
            platform="apple",
            product_id="credit_pack_10",
            transaction_id="refund-cp-tx",
            store_transaction_id="STORE-REFUND-CP",
            status="verified",
            payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "refund-cp-tx", "status": "refunded"},
    )
    assert r.status_code == 200, r.text
    assert await _balance(db_session, user) == 0

    # 멱등: 중복 환불 웹훅에도 음수로 내려가지 않고 에러 없음.
    r2 = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "refund-cp-tx", "status": "refunded"},
    )
    assert r2.status_code == 200, r2.text
    assert await _balance(db_session, user) == 0


# ───────────────────────── F1/N2: readiness 게이트 ─────────────────────────
@pytest.mark.asyncio
async def test_readiness_blocks_when_iap_not_strict_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_verification_mode", "local")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", None)
    monkeypatch.setattr(settings, "iap_webhook_secret", "")

    r = await client.get("/health/ready")
    assert r.status_code == 503
    missing = r.json().get("missing_keys", [])
    assert "iap_mode_not_strict" in missing
    assert "iap_store_credentials_missing" in missing
    assert "iap_webhook_secret_missing" in missing


@pytest.mark.asyncio
async def test_readiness_iap_ok_when_strict_and_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", "shared-secret")
    monkeypatch.setattr(settings, "iap_webhook_secret", "wh-secret")

    r = await client.get("/health/ready")
    # storage/기타로 503일 수 있으나 IAP 사유는 없어야 한다.
    missing = r.json().get("missing_keys", [])
    assert "iap_mode_not_strict" not in missing
    assert "iap_store_credentials_missing" not in missing
    assert "iap_webhook_secret_missing" not in missing
