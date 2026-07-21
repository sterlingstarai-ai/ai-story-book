"""IAP 결제 보안 하드닝 회귀 테스트.

감사 트리아지 F1/F2/F3/F4 + 비평 N1/N2 의 재발 방지:
- F2: 리플레이(같은 영수증, 다른 client transaction_id) 차단 — store_transaction_id 정본 dedup.
- F3: 보상 지급 + 영수증 기록이 단일 트랜잭션(더블그랜트 방지).
- F4: 재설치/기기 변경 시 구독 복원(권한 재연결).
- N1: 환불 웹훅이 구독 권한을 회수하고 크레딧을 클로백.
- F1/N2: 운영(testing=False) IAP 미설정 시 /health/ready 차단.
"""

from typing import Optional

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.models.db import IAPReceipt, IapWebhookEvent, Subscription, UserCredits
from src.services.credits import credits_service
from src.services.iap_verifier import IAPVerificationResult, iap_verifier


def _fake_verification(
    product_id: str, store_txn: str, expires_date_ms: Optional[int] = None
) -> IAPVerificationResult:
    return IAPVerificationResult(
        verified=True,
        source="apple_store",
        environment="Production",
        store_transaction_id=store_txn,
        store_product_id=product_id,
        raw={},
        expires_date_ms=expires_date_ms,
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


# ───────────────────────── C1: 복원 무한 수익화 차단 ─────────────────────────
def _seed_owner_receipt_and_sub(db_session, owner: str, store_txn: str, plan: str = "premium"):
    from datetime import timedelta

    from src.core.utils import utcnow

    db_session.add(
        IAPReceipt(
            user_key=owner, platform="apple",
            product_id=f"subscription_{plan}", transaction_id=f"{store_txn}-orig",
            store_transaction_id=store_txn, status="verified", payload={},
        )
    )
    db_session.add(
        Subscription(
            user_key=owner, plan=plan, status="active",
            credits_per_month=30 if plan == "premium" else 10,
            current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=30),
        )
    )


@pytest.mark.asyncio
async def test_restore_does_not_regrant_monthly_credits(client, db_session, monkeypatch):
    """복원 시 구독 월간 크레딧을 재지급하지 않는다(G1: grant_credits=False)."""
    _seed_owner_receipt_and_sub(db_session, "old-owner-1", "STORE-REGRANT")
    await db_session.commit()

    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-REGRANT")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    new_user = "33333333-4444-5555-6666-777777777777"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "regrant-tx", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "restored"
    assert r.json()["credits_added"] == 0
    # 신규 사용자에게 구독 월간 크레딧(30)이 지급되지 않음(신규 보너스 3만 존재 가능).
    assert await _balance(db_session, new_user) < 30


@pytest.mark.asyncio
async def test_previous_owner_subscription_expired_on_restore(client, db_session, monkeypatch):
    """복원 시 이전 소유자의 해당 plan active 구독만 만료(권한 이전)."""
    _seed_owner_receipt_and_sub(db_session, "old-owner-2", "STORE-PREVOWNER")
    await db_session.commit()

    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-PREVOWNER")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    new_user = "44444444-5555-6666-7777-888888888888"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "prevowner-tx", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text

    db_session.expire_all()
    old_sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.user_key == "old-owner-2")
        )
    ).scalar_one()
    assert old_sub.status == "expired"
    # 새 사용자는 활성 구독 보유.
    assert await credits_service.get_active_subscription(db_session, new_user) is not None


@pytest.mark.asyncio
async def test_expired_receipt_restore_creates_no_active_sub(client, db_session, monkeypatch):
    """MA1: 스토어 만료 영수증 restore는 active 구독을 생성하지 않는다(무한 리필 차단)."""
    _seed_owner_receipt_and_sub(db_session, "old-owner-3", "STORE-EXPIRED")
    await db_session.commit()

    async def fake_verify(**kwargs):
        # expires_date_ms를 과거로 → 만료 영수증.
        return _fake_verification(kwargs["product_id"], "STORE-EXPIRED", expires_date_ms=1)

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    new_user = "55555555-6666-7777-8888-999999999999"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "expired-tx", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text
    # 만료 영수증 → 새 사용자에게 active 구독 미생성.
    assert await credits_service.get_active_subscription(db_session, new_user) is None


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


# ───────────────────────── L10: Sandbox 차단 + 웹훅 토큰 헤더 ─────────────────────────
def _fake_sandbox_verification(product_id: str, store_txn: str) -> IAPVerificationResult:
    return IAPVerificationResult(
        verified=True, source="apple_store", environment="Sandbox",
        store_transaction_id=store_txn, store_product_id=product_id, raw={},
    )


@pytest.mark.asyncio
async def test_sandbox_receipt_blocked_in_production(client, db_session, monkeypatch):
    """운영에서 Sandbox 영수증(21007 폴백)은 크레딧/구독을 발급받지 못한다(L10/G8)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "review_sandbox_allowlist", "")

    async def fake_verify(**kwargs):
        return _fake_sandbox_verification(kwargs["product_id"], "STORE-SANDBOX")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    user = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
    r = await client.post("/v1/iap/verify", json={
        "platform": "apple", "product_id": "credit_pack_10",
        "transaction_id": "sb-tx", "receipt_data": "AAAA",
    }, headers={"X-User-Key": user})
    assert r.status_code == 400, r.text
    assert "sandbox" in r.text.lower()  # UUID 검증이 아니라 sandbox 차단으로 400
    assert await _balance(db_session, user) == 0


@pytest.mark.asyncio
async def test_sandbox_receipt_allowed_when_in_allowlist(client, db_session, monkeypatch):
    """allowlist에 있는 상품은 Sandbox여도 지급(심사 통과)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "review_sandbox_allowlist", "credit_pack_10")

    async def fake_verify(**kwargs):
        return _fake_sandbox_verification(kwargs["product_id"], "STORE-SANDBOX-OK")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    user = "88888888-9999-aaaa-bbbb-cccccccccccc"
    r = await client.post("/v1/iap/verify", json={
        "platform": "apple", "product_id": "credit_pack_10",
        "transaction_id": "sb-ok-tx", "receipt_data": "AAAA",
    }, headers={"X-User-Key": user})
    assert r.status_code == 200, r.text
    assert r.json()["credits_added"] == 10


@pytest.mark.asyncio
async def test_webhook_token_via_header(client, monkeypatch):
    """웹훅 토큰을 X-Webhook-Token 헤더로 전달 가능(쿼리 폴백도 유지)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_webhook_secret", "wh-secret")

    bad = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "unknown", "status": "refunded"},
        headers={"X-Webhook-Token": "wrong"},
    )
    assert bad.status_code == 403, bad.text

    ok = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "unknown", "status": "refunded"},
        headers={"X-Webhook-Token": "wh-secret"},
    )
    assert ok.status_code == 200, ok.text


# ───────────────────────── H4: 웹훅 미기록/선도착 ─────────────────────────
@pytest.mark.asyncio
async def test_webhook_refund_matches_by_store_transaction_id(client, db_session):
    """store_transaction_id로만 도착한 환불 통지가 구독을 만료시킨다(현재는 미스→ignored)."""
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "h4-store-match"
    db_session.add(
        Subscription(
            user_key=user, plan="premium", status="active", credits_per_month=30,
            current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=30),
        )
    )
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_premium",
            transaction_id="client-T", store_transaction_id="STORE-X",
            status="verified", payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "STORE-X", "status": "refunded"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    sub = (
        await db_session.execute(select(Subscription).where(Subscription.user_key == user))
    ).scalar_one()
    assert sub.status == "expired"


@pytest.mark.asyncio
async def test_orphan_webhook_persisted_not_lost(client, db_session):
    """미기록 트랜잭션 웹훅은 유실되지 않고 IapWebhookEvent(applied=False)로 보존, 중복은 멱등."""
    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "ORPHAN-1", "status": "refunded"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    events = (
        await db_session.execute(
            select(IapWebhookEvent).where(IapWebhookEvent.transaction_id == "ORPHAN-1")
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].applied is False

    # 동일 웹훅 재전송 → 부분 유니크로 중복 행 없음.
    r2 = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "ORPHAN-1", "status": "refunded"},
    )
    assert r2.status_code == 200, r2.text
    db_session.expire_all()
    events2 = (
        await db_session.execute(
            select(IapWebhookEvent).where(IapWebhookEvent.transaction_id == "ORPHAN-1")
        )
    ).scalars().all()
    assert len(events2) == 1


@pytest.mark.asyncio
async def test_webhook_refund_before_verify_is_sticky(client, db_session, monkeypatch):
    """verify 이전 선도착한 환불이 verify 시 sticky 재적용되어 구독이 활성화되지 않는다."""

    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-STICKY")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    # 영수증 없이 환불 웹훅 선도착 → orphan 적재.
    r0 = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "STORE-STICKY", "status": "refunded"},
    )
    assert r0.status_code == 200, r0.text

    new_user = "22222222-3333-4444-5555-666666666666"
    body = {
        "platform": "apple", "product_id": "subscription_basic",
        "transaction_id": "client-sticky", "receipt_data": "AAAA",
        "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text

    # 선도착 환불이 재적용되어 활성 구독이 남지 않음.
    db_session.expire_all()
    sub = await credits_service.get_active_subscription(db_session, new_user)
    assert sub is None
    event = (
        await db_session.execute(
            select(IapWebhookEvent).where(IapWebhookEvent.transaction_id == "STORE-STICKY")
        )
    ).scalar_one()
    assert event.applied is True


@pytest.mark.asyncio
async def test_refunded_receipt_not_reverted_by_later_active(client, db_session):
    """환불된 영수증은 이후 active 통지로 뒤집히지 않는다(sticky terminal)."""
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "h4-sticky-terminal"
    db_session.add(
        Subscription(
            user_key=user, plan="basic", status="active", credits_per_month=10,
            current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=30),
        )
    )
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_basic",
            transaction_id="sticky-tx", store_transaction_id="STORE-STICKY-2",
            status="verified", payload={},
        )
    )
    await db_session.commit()

    await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "sticky-tx", "status": "refunded"},
    )
    # 이후 active 통지가 도착해도 되돌리지 않음.
    await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "sticky-tx", "status": "active"},
    )
    db_session.expire_all()
    receipt = (
        await db_session.execute(
            select(IAPReceipt).where(IAPReceipt.transaction_id == "sticky-tx")
        )
    ).scalar_one()
    assert receipt.status == "refunded"
    sub = (
        await db_session.execute(select(Subscription).where(Subscription.user_key == user))
    ).scalar_one()
    assert sub.status == "expired"


# ───────────────────────── H5: 웹훅이 해당 영수증 구독만 갱신 ─────────────────────────
@pytest.mark.asyncio
async def test_webhook_targets_receipt_subscription_not_latest(client, db_session, monkeypatch):
    """업그레이드 후 옛 영수증 통지가 방금 결제한 최신 구독을 죽이지 않는다(H5)."""
    user = "66666666-7777-8888-9999-000000000000"

    async def fake_verify(**kwargs):
        # store_txn을 transaction_id로 구분.
        return _fake_verification(kwargs["product_id"], f"STORE-{kwargs['transaction_id']}")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    await client.post("/v1/iap/verify", json={
        "platform": "apple", "product_id": "subscription_basic",
        "transaction_id": "T1", "receipt_data": "AAAA", "is_subscription": True,
    }, headers={"X-User-Key": user})
    await client.post("/v1/iap/verify", json={
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "T2", "receipt_data": "AAAA", "is_subscription": True,
    }, headers={"X-User-Key": user})

    # 옛 basic 영수증(T1)에 대한 만료 통지 → basic만 만료, 최신 premium은 유지.
    r = await client.post(
        "/v1/iap/webhook/apple", json={"transaction_id": "T1", "status": "expired"}
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    active = await credits_service.get_active_subscription(db_session, user)
    assert active is not None and active.plan == "premium"
    basic = (
        await db_session.execute(
            select(Subscription).where(
                Subscription.user_key == user, Subscription.plan == "basic"
            )
        )
    ).scalar_one()
    assert basic.status == "expired"


# ───────────────────────── M14: 구독 환불 clawback ─────────────────────────
@pytest.mark.asyncio
async def test_refund_webhook_claws_back_subscription_credits(client, db_session):
    """구독 상품 환불 웹훅은 지급된 월간 크레딧을 회수한다(0클램프)."""
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "m14-sub-refund"
    db_session.add(UserCredits(user_key=user, credits=30, total_purchased=0))
    db_session.add(
        Subscription(
            user_key=user, plan="premium", status="active", credits_per_month=30,
            current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=30),
        )
    )
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_premium",
            transaction_id="m14-tx", store_transaction_id="STORE-M14",
            status="verified", payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "m14-tx", "status": "refunded"},
    )
    assert r.status_code == 200, r.text
    assert await _balance(db_session, user) == 0  # 30 회수(0클램프)

    # 멱등: 중복 환불 웹훅에도 음수로 안 내려가고 중복 회수 없음.
    r2 = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "m14-tx", "status": "refunded"},
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


# ─────── 출시 감사 2026-07-13: fail-open 영수증/웹훅을 요청 경로에서 차단 ───────
# readiness 프로브는 '트래픽 보내지 마'만 신호할 뿐 라우트를 막지 않는다. 위조 영수증이
# 크레딧/구독을 발급받거나 무인증 웹훅이 상태를 변조하는 것을 운영(testing=False)에서
# fail-closed로 강제한다.
@pytest.mark.asyncio
async def test_local_verification_fails_closed_in_production(monkeypatch):
    """운영에서 local 모드(무검증 성공)는 위조 영수증을 통과시키지 않고 거부한다."""
    from src.core.exceptions import ValidationError

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_verification_mode", "local")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", None)

    with pytest.raises(ValidationError):
        await iap_verifier.verify_purchase(
            platform="apple",
            product_id="credit_pack_10",
            transaction_id="forged-tx",
            receipt_data="AAAA",
        )


@pytest.mark.asyncio
async def test_hybrid_missing_config_fails_closed_in_production(monkeypatch):
    """운영에서 hybrid 설정 누락 폴백도 무검증 성공이므로 fail-closed."""
    from src.core.exceptions import ValidationError

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_verification_mode", "hybrid")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", None)

    with pytest.raises(ValidationError):
        await iap_verifier.verify_purchase(
            platform="apple",
            product_id="credit_pack_10",
            transaction_id="forged-tx",
            receipt_data="AAAA",
        )


@pytest.mark.asyncio
async def test_local_verification_allowed_in_testing(monkeypatch):
    """테스트/개발(testing=True)에서는 기존 local 성공 동작을 유지한다."""
    monkeypatch.setattr(settings, "testing", True)
    monkeypatch.setattr(settings, "iap_verification_mode", "local")

    result = await iap_verifier.verify_purchase(
        platform="apple",
        product_id="credit_pack_10",
        transaction_id="dev-tx",
        receipt_data="AAAA",
    )
    assert result.verified is True


@pytest.mark.asyncio
async def test_webhook_rejected_when_secret_unset_in_production(client, monkeypatch):
    """운영에서 웹훅 시크릿 미설정이면 무인증 상태변조를 거부(fail-closed)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_webhook_secret", "")

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "any-tx", "status": "refunded"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_webhook_requires_matching_token_when_secret_set(client, monkeypatch):
    """시크릿 설정 시: 잘못된 토큰 거부(403), 올바른 토큰 통과(200)."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_webhook_secret", "wh-secret")

    bad = await client.post(
        "/v1/iap/webhook/apple?token=wrong",
        json={"transaction_id": "unknown-tx", "status": "refunded"},
    )
    assert bad.status_code == 403, bad.text

    ok = await client.post(
        "/v1/iap/webhook/apple?token=wh-secret",
        json={"transaction_id": "unknown-tx", "status": "refunded"},
    )
    # 인증 통과 — 미지의 transaction_id는 'ignored'로 처리되나 인증 자체는 성공.
    assert ok.status_code == 200, ok.text
