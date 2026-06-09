"""결제 우회/웹훅 인증 — 운영 보안 가드.

- /v1/credits/subscribe 유료 플랜 직접 지급을 운영에서 차단(검증 IAP만).
- IAP 웹훅은 시크릿 설정 시 ?token= 일치를 요구(무인증 상태 변조 차단).
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


# ── IAP 웹훅 인증 ──
@pytest.mark.asyncio
async def test_iap_webhook_requires_secret_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "iap_webhook_secret", "s3cret")
    body = {"transaction_id": "tx-sec-1", "status": "cancelled"}

    # 토큰 없음 → 403
    r = await client.post("/v1/iap/webhook/apple", json=body)
    assert r.status_code == 403, r.text

    # 틀린 토큰 → 403
    r = await client.post("/v1/iap/webhook/apple?token=wrong", json=body)
    assert r.status_code == 403, r.text

    # 올바른 토큰 → 가드 통과(핸들러 진입 — 403 아님)
    r = await client.post("/v1/iap/webhook/apple?token=s3cret", json=body)
    assert r.status_code != 403, r.text


@pytest.mark.asyncio
async def test_iap_webhook_open_when_secret_unset(client):
    # 미설정(기본) → 가드 통과(기존 동작 유지)
    body = {"transaction_id": "tx-sec-2", "status": "cancelled"}
    r = await client.post("/v1/iap/webhook/google", json=body)
    assert r.status_code != 403, r.text
