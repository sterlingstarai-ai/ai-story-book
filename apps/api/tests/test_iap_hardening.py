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
    """스토어 검증 결과 스텁.

    R2-6: 구독 상품의 `expires_date_ms` 부재는 이제 '만료'로 fail-closed 취급된다(부재는
    유효함의 증거가 아니다). 실제 Apple/Google 구독 영수증은 항상 만료 시각을 싣고 오므로,
    스텁도 구독 상품이면 **미래 만료**를 기본값으로 채운다 — 그래야 이 스텁을 쓰는
    테스트들이 '리플레이·복원·권한이전' 이라는 원래 관심사를 검증한다. 만료 시나리오는
    호출부가 명시값을 넘겨서 만든다.
    """
    if expires_date_ms is None and product_id.startswith("subscription_"):
        from datetime import timedelta

        from src.core.utils import utcnow

        expires_date_ms = int((utcnow() + timedelta(days=30)).timestamp() * 1000)
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


# ── C1/MA1 실경로 회귀 (verify_purchase 통째 mock 금지 — HTTP 경계만 mock) ──
#
# 구 테스트는 verify_purchase 전체를 monkeypatch해 expires_date_ms를 주입했기 때문에,
# 실제 Apple 검증 경로가 만료 시각을 추출하지 않아도 green이었다(false-green이 치명
# 결함을 은폐). 아래 테스트들은 최하위 I/O 경계인 _post_json(HTTP POST)만 mock하고
# verify_purchase → _verify_apple → _post_apple_receipt → _find_apple_transaction →
# 만료 추출까지 전부 실코드로 통과시킨다.

_APPLE_EXPIRED_MS = 1_600_000_000_000  # 2020-09 — 확정 과거
_APPLE_FUTURE_MS = 4_100_000_000_000  # 2099-xx — 확정 미래


def _apple_receipt_response(*, product_id: str, transaction_id: str, expires_date_ms: int) -> dict:
    """Apple verifyReceipt 성공 응답(자동갱신 구독). 만료 구독도 status=0으로 온다."""
    return {
        "status": 0,
        "environment": "Production",
        "receipt": {"bundle_id": "com.storybook.ai_story_book", "in_app": []},
        "latest_receipt_info": [
            {
                "product_id": product_id,
                "transaction_id": transaction_id,
                "original_transaction_id": transaction_id,
                # Apple은 ms epoch을 문자열로 준다.
                "expires_date_ms": str(expires_date_ms),
                "bid": "com.storybook.ai_story_book",
            }
        ],
    }


def _use_strict_apple(monkeypatch, response: dict) -> None:
    """strict 모드 실 Apple 검증을 태우되 네트워크만 차단(_post_json = 유일한 mock)."""
    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", "test-shared-secret")

    async def fake_post_json(url, payload):  # 인스턴스 속성이라 self 없음
        return response

    monkeypatch.setattr(iap_verifier, "_post_json", fake_post_json)


@pytest.mark.asyncio
async def test_apple_verification_extracts_expires_date_ms(monkeypatch):
    """C1/MA1: strict Apple 실검증이 만료 시각을 결과에 실어야 한다.

    이 값이 None이면 라우터의 _subscription_expired 가드가 항상 통과해 만료 영수증
    재제출로 active 구독이 재생성되고 periodic_credits가 영구 리필한다(무한 수익화).
    """
    _use_strict_apple(
        monkeypatch,
        _apple_receipt_response(
            product_id="subscription_premium",
            transaction_id="apple-expired-tx",
            expires_date_ms=_APPLE_EXPIRED_MS,
        ),
    )

    result = await iap_verifier.verify_purchase(
        platform="apple",
        product_id="subscription_premium",
        transaction_id="apple-expired-tx",
        receipt_data="AAAA",
        is_subscription=True,
    )

    assert result.verified is True
    assert result.source == "apple_store"
    assert result.expires_date_ms == _APPLE_EXPIRED_MS


@pytest.mark.asyncio
async def test_expired_receipt_restore_creates_no_active_sub(client, db_session, monkeypatch):
    """MA1 실경로: 만료 Apple 영수증 restore는 active 구독을 생성하지 않는다."""
    _seed_owner_receipt_and_sub(db_session, "old-owner-3", "STORE-EXPIRED")
    await db_session.commit()

    _use_strict_apple(
        monkeypatch,
        _apple_receipt_response(
            product_id="subscription_premium",
            transaction_id="STORE-EXPIRED",
            expires_date_ms=_APPLE_EXPIRED_MS,
        ),
    )

    new_user = "55555555-6666-7777-8888-999999999999"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "STORE-EXPIRED", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text
    # 만료 영수증 → 새 사용자에게 active 구독 미생성.
    assert await credits_service.get_active_subscription(db_session, new_user) is None


@pytest.mark.asyncio
async def test_unexpired_receipt_restore_still_activates_sub(client, db_session, monkeypatch):
    """만료 가드가 정당한(미만료) 복원까지 막지 않는다 — 과잉 차단 회귀 방지."""
    _seed_owner_receipt_and_sub(db_session, "old-owner-4", "STORE-LIVE")
    await db_session.commit()

    _use_strict_apple(
        monkeypatch,
        _apple_receipt_response(
            product_id="subscription_premium",
            transaction_id="STORE-LIVE",
            expires_date_ms=_APPLE_FUTURE_MS,
        ),
    )

    new_user = "66666666-7777-8888-9999-aaaaaaaaaaaa"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "STORE-LIVE", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text
    assert await credits_service.get_active_subscription(db_session, new_user) is not None


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
    """웹훅 토큰을 X-Webhook-Token 헤더로 전달(헤더 전용 — 쿼리 폴백 제거됨)."""
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
    """구독 상품 환불 웹훅은 **실제 지급된** 월간 크레딧을 회수한다(0클램프).

    M3/R2-3: 회수액의 정본은 플랜 상수가 아니라 원장(credit_transactions)이다. 그래서
    픽스처도 실제 지급 경로와 동일하게 구성한다 — 영수증이 개설한 구독 + 그 구독을
    reference_id로 하는 'subscription' 지급 원장.
    """
    from datetime import timedelta

    from src.core.utils import utcnow
    from src.models.db import CreditTransaction

    user = "m14-sub-refund"
    db_session.add(UserCredits(user_key=user, credits=30, total_purchased=0))
    subscription = Subscription(
        user_key=user, plan="premium", status="active", credits_per_month=30,
        current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=30),
    )
    db_session.add(subscription)
    await db_session.flush()
    db_session.add(
        CreditTransaction(
            user_key=user, amount=30, balance_after=30,
            transaction_type="subscription", description="프리미엄 구독 크레딧",
            reference_id=str(subscription.id),
        )
    )
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_premium",
            transaction_id="m14-tx", store_transaction_id="STORE-M14",
            status="verified", subscription_id=subscription.id, payload={},
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
    # M9: 공개 /ready는 provider_keys boolean만; 상세 IAP 사유는 인증된 detailed에만.
    assert r.json()["services"]["provider_keys"] == "unhealthy"
    assert "missing_keys" not in r.json()
    monkeypatch.setattr(settings, "admin_api_key", "testadminkey")
    d = await client.get("/health/detailed", headers={"X-Admin-Key": "testadminkey"})
    missing = d.json().get("missing_keys", [])
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
    """시크릿 설정 시: 잘못된 토큰 거부(403), 올바른 토큰 통과(200) — 헤더 전용."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_webhook_secret", "wh-secret")

    bad = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "unknown-tx", "status": "refunded"},
        headers={"X-Webhook-Token": "wrong"},
    )
    assert bad.status_code == 403, bad.text

    ok = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "unknown-tx", "status": "refunded"},
        headers={"X-Webhook-Token": "wh-secret"},
    )
    # 인증 통과 — 미지의 transaction_id는 'ignored'로 처리되나 인증 자체는 성공.
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_webhook_rejects_querystring_token(client, monkeypatch):
    """감사 iap.py:614 봉인: ?token= 쿼리 폴백이 제거돼 로그 유출 경로가 닫혔다.

    올바른 시크릿을 쿼리로만 넘기고 헤더는 비우면 이제 거부(403)된다 — 쿼리는 nginx
    액세스 로그($request)에 평문 기록되므로 인증 채널로 인정하지 않는다.
    """
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "iap_webhook_secret", "wh-secret")

    resp = await client.post(
        "/v1/iap/webhook/apple?token=wh-secret",
        json={"transaction_id": "unknown-tx", "status": "refunded"},
    )
    assert resp.status_code == 403, resp.text


# ── 감사 #14/#7: 만료 영수증 restore의 부작용 2종 ──


@pytest.mark.asyncio
async def test_expired_restore_keeps_previous_owner_subscription(
    client, db_session, monkeypatch
):
    """#14: 만료 영수증 restore가 이전 소유자의 정당한 active 구독을 죽이면 안 된다.

    만료 영수증은 아무 권한도 이전하지 않는데, expire 호출이 만료 검사보다 먼저 실행돼
    이전 소유자가 그 사이 신규 결제한 같은 plan 구독까지 소멸시켰다.
    """
    _seed_owner_receipt_and_sub(db_session, "old-owner-5", "STORE-EXP-KEEP")
    await db_session.commit()

    _use_strict_apple(
        monkeypatch,
        _apple_receipt_response(
            product_id="subscription_premium",
            transaction_id="STORE-EXP-KEEP",
            expires_date_ms=_APPLE_EXPIRED_MS,
        ),
    )

    new_user = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "STORE-EXP-KEEP", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text

    old_sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.user_key == "old-owner-5")
        )
    ).scalar_one()
    assert old_sub.status == "active", "만료 영수증 restore가 이전 소유자 구독을 만료시키면 안 됨"


@pytest.mark.asyncio
async def test_expired_restore_clears_previous_owner_subscription_ref(
    client, db_session, monkeypatch
):
    """#7(H5): 만료 restore 후에도 남는 타인 구독 참조가 이전 소유자의 계정 삭제를 막는다.

    receipt.user_key만 새 사용자로 넘어가고 subscription_id는 이전 소유자 구독을 가리킨 채
    남으면, 그 소유자의 DELETE /v1/users/me가 FK 위반으로 500 — 법적 삭제권이 봉쇄된다.
    """
    _seed_owner_receipt_and_sub(db_session, "old-owner-6", "STORE-EXP-FK")
    await db_session.commit()

    # 영수증을 소유자의 구독에 실제로 연결(H5 배선 재현).
    old_sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.user_key == "old-owner-6")
        )
    ).scalar_one()
    receipt = (
        await db_session.execute(
            select(IAPReceipt).where(IAPReceipt.store_transaction_id == "STORE-EXP-FK")
        )
    ).scalar_one()
    receipt.subscription_id = old_sub.id
    await db_session.commit()

    _use_strict_apple(
        monkeypatch,
        _apple_receipt_response(
            product_id="subscription_premium",
            transaction_id="STORE-EXP-FK",
            expires_date_ms=_APPLE_EXPIRED_MS,
        ),
    )

    new_user = "88888888-9999-aaaa-bbbb-cccccccccccc"
    body = {
        "platform": "apple", "product_id": "subscription_premium",
        "transaction_id": "STORE-EXP-FK", "receipt_data": "AAAA", "is_subscription": True,
    }
    r = await client.post("/v1/iap/verify", json=body, headers={"X-User-Key": new_user})
    assert r.status_code == 200, r.text

    db_session.expire_all()
    moved = (
        await db_session.execute(
            select(IAPReceipt).where(IAPReceipt.store_transaction_id == "STORE-EXP-FK")
        )
    ).scalar_one()
    assert moved.user_key == new_user
    assert moved.subscription_id is None, (
        "만료 restore 후 타인 구독 참조가 남으면 이전 소유자 계정 삭제가 FK로 실패한다"
    )


@pytest.mark.asyncio
async def test_orphan_google_suffix_refund_reapplies_on_verify(
    client, db_session, monkeypatch
):
    """#6(H4): 접미사 orderId(..0)로 선도착한 환불 orphan이 base verify에서 재적용돼야 한다.

    재적용되지 않으면 환불된 구독이 active로 남아 periodic_credits가 매월 리필한다 —
    H4가 막으려던 buy→refund 무한 무료 크레딧이 Google 접미사 케이스에서 그대로 재현.
    provider는 200을 받았으므로 재전송도 없어 결정이 영구 유실된다.
    """
    base_order = "GPA.1234-5678-9012-34567"

    # 1) 환불 웹훅이 갱신 접미사가 붙은 orderId로 먼저 도착 → orphan 적재.
    wh = await client.post(
        "/v1/iap/webhook/google",
        json={"transaction_id": f"{base_order}..0", "status": "refunded", "payload": {}},
        headers={"X-IAP-Webhook-Secret": settings.iap_webhook_secret or ""},
    )
    assert wh.status_code in (200, 202), wh.text
    assert wh.json()["status"] == "accepted_orphan", wh.text

    # 2) 이후 사용자가 verify(스토어는 base orderId 반환).
    async def fake_verify(**kwargs):
        return IAPVerificationResult(
            verified=True,
            source="google_play",
            environment="production",
            store_transaction_id=base_order,
            store_product_id=kwargs["product_id"],
            raw={},
        )

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    user = "99999999-aaaa-bbbb-cccc-dddddddddddd"
    r = await client.post(
        "/v1/iap/verify",
        json={
            "platform": "google", "product_id": "subscription_premium",
            "transaction_id": base_order, "purchase_token": "tok", "is_subscription": True,
        },
        headers={"X-User-Key": user},
    )
    assert r.status_code == 200, r.text

    # 3) 선도착 환불 결정이 반영돼 active 구독이 남아 있으면 안 된다.
    db_session.expire_all()
    assert await credits_service.get_active_subscription(db_session, user) is None, (
        "접미사 orderId 환불 orphan이 재적용되지 않아 환불된 구독이 active로 남았다"
    )
    event = (
        await db_session.execute(
            select(IapWebhookEvent).where(
                IapWebhookEvent.transaction_id == f"{base_order}..0"
            )
        )
    ).scalar_one()
    assert event.applied is True


# ══════════════════ R2 (2026-08-17 보안감사): 결제 정합 회귀 ══════════════════


@pytest.mark.asyncio
async def test_cancelled_subscription_is_reactivated_by_new_purchase(
    client, headers, db_session, monkeypatch
):
    """H3/R2-1: 취소(cancelled, 잔여기간 내) 상태의 새 검증 결제가 구독을 **재활성**한다.

    수정 전에는 `already_subscribed` 가드가 `get_active_subscription`
    (status ∈ {active, cancelled})을 그대로 써서, 이 결제를 삼키고 구독을 만들지도
    갱신하지도 않았다 — 과금은 되고 권한은 미지급, 서버측 복구 수단 없음.

    red-proof: 가드의 `and active_subscription.status == "active"` 를 지우면
    status가 'already_subscribed'로 돌아오고 active 구독이 없어 FAIL한다.
    """
    from datetime import timedelta

    from src.core.utils import utcnow

    user = headers["X-User-Key"]
    db_session.add(
        Subscription(
            user_key=user, plan="premium", status="cancelled", credits_per_month=30,
            current_period_start=utcnow() - timedelta(days=5),
            current_period_end=utcnow() + timedelta(days=25),
        )
    )
    await db_session.commit()

    async def fake_verify(**kwargs):
        return _fake_verification(kwargs["product_id"], "STORE-REACTIVATE-1")

    monkeypatch.setattr(iap_verifier, "verify_purchase", fake_verify)

    r = await client.post(
        "/v1/iap/verify",
        headers=headers,
        json={
            "platform": "apple",
            "product_id": "subscription_premium",
            "transaction_id": "reactivate-tx-1",
            "receipt_data": "AAAA",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified", r.json()

    db_session.expire_all()
    subs = (
        await db_session.execute(
            select(Subscription).where(Subscription.user_key == user)
        )
    ).scalars().all()
    active = [s for s in subs if s.status == "active"]
    assert len(active) == 1, [(s.plan, s.status) for s in subs]
    assert active[0].plan == "premium"
    # 대체된 옛 cancelled 행은 종료돼 entitlement가 둘로 갈리지 않는다.
    assert all(s.status != "cancelled" for s in subs), [
        (s.plan, s.status) for s in subs
    ]


@pytest.mark.asyncio
async def test_active_webhook_restores_cancelled_subscription(client, db_session):
    """H3/R2-1: 'active' 통지가 cancelled 구독을 복귀시킨다(cancelled는 터미널이 아니다).

    red-proof: `_STATUS_RANK`에 `"cancelled": 2` 를 되돌리면 sticky 가드가 조기 반환해
    구독이 cancelled에 갇혀 FAIL한다.
    """
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "r21-webhook-active"
    subscription = Subscription(
        user_key=user, plan="basic", status="cancelled", credits_per_month=10,
        current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=20),
    )
    db_session.add(subscription)
    await db_session.flush()
    subscription_id = subscription.id
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_basic",
            transaction_id="r21-tx", store_transaction_id="STORE-R21",
            status="cancelled", subscription_id=subscription_id, payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "r21-tx", "status": "active"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    refreshed = (
        await db_session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
    ).scalar_one()
    assert refreshed.status == "active"


@pytest.mark.asyncio
async def test_refunded_receipt_stays_sticky_against_active_webhook(client, db_session):
    """H4 유지 확인: 터미널(refunded)은 여전히 'active' 통지로 뒤집히지 않는다.

    R2-1이 sticky 범위를 좁혔으므로, 좁히다가 환불 부활까지 열지 않았음을 반대 방향으로 봉인.
    """
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "r21-refund-sticky"
    subscription = Subscription(
        user_key=user, plan="basic", status="expired", credits_per_month=10,
        current_period_start=utcnow() - timedelta(days=40),
        current_period_end=utcnow() - timedelta(seconds=1),
    )
    db_session.add(subscription)
    await db_session.flush()
    subscription_id = subscription.id
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_basic",
            transaction_id="r21-refund-tx", store_transaction_id="STORE-R21-REF",
            status="refunded", subscription_id=subscription_id, payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "r21-refund-tx", "status": "active"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    refreshed = (
        await db_session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
    ).scalar_one()
    assert refreshed.status == "expired"


@pytest.mark.asyncio
async def test_zero_grant_subscription_refund_does_not_claw_back(client, db_session):
    """M3/R2-3: 0지급 영수증(restored/already_subscribed)의 환불은 크레딧을 차감하지 않는다.

    수정 전에는 플랜 고정액(30)을 회수해, 아무 잘못 없는 사용자의 잔액이 사라졌다.

    red-proof: `_granted_subscription_credits(...)` 를 다시
    `SUBSCRIPTION_PLANS[plan]["credits_per_month"]` 로 되돌리면 잔액이 30 → 0이 되어 FAIL.
    """
    from datetime import timedelta

    from src.core.utils import utcnow

    user = "r23-zero-grant"
    db_session.add(UserCredits(user_key=user, credits=30, total_purchased=0))
    subscription = Subscription(
        user_key=user, plan="premium", status="active", credits_per_month=30,
        current_period_start=utcnow(), current_period_end=utcnow() + timedelta(days=30),
    )
    db_session.add(subscription)
    await db_session.flush()
    # 복원 영수증 — grant_credits=False 였으므로 'subscription' 지급 원장이 없다.
    db_session.add(
        IAPReceipt(
            user_key=user, platform="apple", product_id="subscription_premium",
            transaction_id="r23-tx", store_transaction_id="STORE-R23",
            status="restored", subscription_id=subscription.id, payload={},
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/iap/webhook/apple",
        json={"transaction_id": "r23-tx", "status": "refunded"},
    )
    assert r.status_code == 200, r.text
    assert await _balance(db_session, user) == 30  # 무고한 차감 없음


@pytest.mark.asyncio
async def test_google_license_test_purchase_rejected_in_production(monkeypatch):
    """M4/R2-4: 운영(strict)에서 Google purchaseType=0(라이선스/테스트 구매)은 fail-closed.

    Apple sandbox 영수증 차단과 대칭 — 무결제 지급 채널을 남기지 않는다.

    red-proof: `_assert_google_purchase_valid`의 purchase_type 가드를 지우면 예외가
    발생하지 않아 이 테스트가 FAIL한다.
    """
    from src.core.exceptions import ValidationError

    monkeypatch.setattr(settings, "testing", False)
    with pytest.raises(ValidationError):
        iap_verifier._assert_google_purchase_valid(
            google_data={"orderId": "GPA.1", "purchaseState": 0, "purchaseType": 0},
            expected_transaction_id="GPA.1",
            is_subscription=False,
        )
    # 정상(실결제)은 통과 — 반대 방향 봉인.
    iap_verifier._assert_google_purchase_valid(
        google_data={"orderId": "GPA.1", "purchaseState": 0},
        expected_transaction_id="GPA.1",
        is_subscription=False,
    )


@pytest.mark.asyncio
async def test_google_missing_order_id_is_rejected(monkeypatch):
    """R2-6: orderId 부재 시 매칭을 '스킵'하면 리플레이 dedup이 무력해진다 — 거부한다."""
    from src.core.exceptions import ValidationError

    monkeypatch.setattr(settings, "testing", False)
    with pytest.raises(ValidationError):
        iap_verifier._assert_google_purchase_valid(
            google_data={"purchaseState": 0},
            expected_transaction_id="GPA.1",
            is_subscription=False,
        )


def test_apple_bundle_id_mismatch_is_rejected(monkeypatch):
    """M5/R2-5: 기대 bundle_id와 다른 앱의 영수증은 거부한다(master secret 하 cross-app 리플레이).

    red-proof: `_assert_apple_bundle_id(...)` 호출을 지우면 예외가 없어 FAIL한다.
    """
    from src.core.exceptions import ValidationError

    monkeypatch.setattr(settings, "apple_bundle_id", "com.aistorybook.app")

    # 일치 → 통과
    iap_verifier._assert_apple_bundle_id(
        {"receipt": {"bundle_id": "com.aistorybook.app"}}, matched={}
    )
    # 불일치 → 거부
    with pytest.raises(ValidationError):
        iap_verifier._assert_apple_bundle_id(
            {"receipt": {"bundle_id": "com.attacker.other"}}, matched={}
        )


def test_subscription_receipt_without_expiry_is_treated_as_expired():
    """R2-6: 구독 영수증에 expires_date_ms 가 없으면 '만료 아님'으로 fail-open하지 않는다."""
    from src.routers.iap import _subscription_expired

    # 스텁 기본값을 우회해 '만료 필드가 아예 없는' 구독 영수증을 만든다.
    no_expiry = IAPVerificationResult(
        verified=True,
        source="apple_store",
        environment="Production",
        store_transaction_id="S1",
        store_product_id="subscription_premium",
        raw={},
        expires_date_ms=None,
    )
    assert _subscription_expired(no_expiry, is_subscription=True) is True
    # 크레딧팩(비구독)은 만료 필드가 원래 없다 — 영향 없음.
    assert _subscription_expired(no_expiry, is_subscription=False) is False
