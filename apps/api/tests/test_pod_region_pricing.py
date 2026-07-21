"""P1-6: POD 지역 가격 — 배송 국가 기준 서버 산출(클라이언트 가격 미신뢰, 글로벌)."""

import pytest

from src.routers.pod import _pod_pricing_for


def test_pod_pricing_korea_is_krw():
    unit, shipping, currency = _pod_pricing_for("KR")
    assert currency == "KRW"
    assert unit == 18000


def test_pod_pricing_us_is_usd():
    _, _, currency = _pod_pricing_for("us")  # 소문자 국가코드도 처리
    assert currency == "USD"


def test_pod_pricing_unknown_country_defaults_to_usd():
    _, _, currency = _pod_pricing_for("BR")
    assert currency == "USD"


@pytest.mark.asyncio
async def test_pod_quote_endpoint_returns_region_price_and_currency(client, headers):
    """GET /v1/pod/quote가 지역 단가·통화를 반환(H20 — 표시-청구 일치 단일 소스)."""
    r_us = await client.get("/v1/pod/quote", params={"country": "US", "quantity": 1}, headers=headers)
    assert r_us.status_code == 200
    assert r_us.json() == {"unit_price": 20, "shipping_fee": 5, "total_price": 25, "currency": "USD"}

    r_kr = await client.get("/v1/pod/quote", params={"country": "KR", "quantity": 2}, headers=headers)
    assert r_kr.json()["total_price"] == (18000 * 2) + 3000
    assert r_kr.json()["currency"] == "KRW"

    r_br = await client.get("/v1/pod/quote", params={"country": "BR", "quantity": 1}, headers=headers)
    assert r_br.json()["currency"] == "USD"  # 미지원국 기본
