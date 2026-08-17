"""결제 우회/웹훅 인증 — 운영 보안 가드.

- /v1/credits/subscribe 유료 플랜 직접 지급을 운영에서 차단(검증 IAP만).
- IAP 웹훅은 시크릿 설정 시 X-Webhook-Token 헤더 일치를 요구(무인증 상태 변조 차단).
"""

import pytest

from src.core.config import settings


# ── 결제 우회: 유료 구독 직접 지급 차단 ──
@pytest.mark.asyncio
async def test_paid_subscribe_blocked_in_production(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "allow_unverified_subscribe", False)
    r = await client.post(
        "/v1/credits/subscribe", json={"plan": "basic"}, headers=headers
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_free_subscribe_allowed_in_production(client, headers, monkeypatch):
    # free 플랜 변경(다운그레이드)은 크레딧 남용이 아니므로 허용
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "allow_unverified_subscribe", False)
    r = await client.post(
        "/v1/credits/subscribe", json={"plan": "free"}, headers=headers
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_paid_subscribe_allowed_when_flag_set(client, headers, monkeypatch):
    # dev에서 명시 허용 시 동작
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "allow_unverified_subscribe", True)
    r = await client.post(
        "/v1/credits/subscribe", json={"plan": "basic"}, headers=headers
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_paid_subscribe_allowed_in_testing(client, headers):
    # 기본(testing=True) → 게이트 우회(테스트/개발 편의)
    r = await client.post(
        "/v1/credits/subscribe", json={"plan": "basic"}, headers=headers
    )
    assert r.status_code == 200, r.text


# ── M13: 활성 유료 구독 보유 시 free 전환 거부 + 잔여기간 보존 ──
@pytest.mark.asyncio
async def test_free_subscribe_rejected_when_active_paid_sub(
    client, db_session, headers, user_key, monkeypatch
):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "allow_unverified_subscribe", False)
    from src.services.credits import credits_service

    await credits_service.create_subscription(db_session, user_key, "premium")
    before = await credits_service.get_active_subscription(db_session, user_key)
    before_end = before.current_period_end

    r = await client.post(
        "/v1/credits/subscribe", json={"plan": "free"}, headers=headers
    )
    assert r.status_code == 400, r.text  # 거부(현재는 free가 유료 구독 즉시 소멸)

    db_session.expire_all()
    after = await credits_service.get_active_subscription(db_session, user_key)
    assert after is not None
    assert after.plan == "premium"
    assert after.status == "active"
    assert after.current_period_end == before_end  # 잔여기간 미소멸


@pytest.mark.asyncio
async def test_create_subscription_keeps_prev_period_end(db_session):
    from sqlalchemy import select

    from src.models.db import Subscription
    from src.services.credits import credits_service

    basic = await credits_service.create_subscription(db_session, "m13u", "basic")
    basic_id = basic.id
    basic_end = basic.current_period_end

    await credits_service.create_subscription(db_session, "m13u", "premium")

    db_session.expire_all()
    basic_row = await db_session.get(Subscription, basic_id)
    assert basic_row.status == "cancelled"
    assert basic_row.current_period_end == basic_end  # now로 즉시 소멸되지 않음

    active = await credits_service.get_active_subscription(db_session, "m13u")
    assert active is not None and active.plan == "premium"
    # 업그레이드 경로 정합: active 구독은 여전히 정확히 1행
    actives = (
        await db_session.execute(
            select(Subscription).where(
                Subscription.user_key == "m13u", Subscription.status == "active"
            )
        )
    ).scalars().all()
    assert len(actives) == 1


# ── IAP 웹훅 인증 ──
@pytest.mark.asyncio
async def test_iap_webhook_requires_secret_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "iap_webhook_secret", "s3cret")
    body = {"transaction_id": "tx-sec-1", "status": "cancelled"}

    # 토큰 없음 → 403
    r = await client.post("/v1/iap/webhook/apple", json=body)
    assert r.status_code == 403, r.text

    # 틀린 토큰(헤더) → 403
    r = await client.post(
        "/v1/iap/webhook/apple", json=body, headers={"X-Webhook-Token": "wrong"}
    )
    assert r.status_code == 403, r.text

    # 쿼리 토큰은 이제 인증 채널이 아니다(로그 유출 방지, 감사 iap.py:614) → 403
    r = await client.post("/v1/iap/webhook/apple?token=s3cret", json=body)
    assert r.status_code == 403, r.text

    # 올바른 토큰(헤더) → 가드 통과(핸들러 진입 — 403 아님)
    r = await client.post(
        "/v1/iap/webhook/apple", json=body, headers={"X-Webhook-Token": "s3cret"}
    )
    assert r.status_code != 403, r.text


@pytest.mark.asyncio
async def test_iap_webhook_open_when_secret_unset(client):
    # 미설정(기본) → 가드 통과(기존 동작 유지)
    body = {"transaction_id": "tx-sec-2", "status": "cancelled"}
    r = await client.post("/v1/iap/webhook/google", json=body)
    assert r.status_code != 403, r.text
