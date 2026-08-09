"""P1-6: POD 지역 가격 — 배송 국가 기준 서버 산출(클라이언트 가격 미신뢰, 글로벌)."""

import pytest

from src.core.exceptions import UnsupportedRegionError
from src.routers.pod import _pod_pricing_for


def test_pod_pricing_korea_is_krw():
    unit, shipping, currency = _pod_pricing_for("KR")
    assert currency == "KRW"
    assert unit == 18000


def test_pod_pricing_us_is_usd():
    _, _, currency = _pod_pricing_for("us")  # 소문자 국가코드도 처리
    assert currency == "USD"


def test_pod_pricing_rejects_unsupported_country():
    """L2: 미지원 국가는 조용한 USD 폴백이 아니라 명시 거부.

    폴백은 배송 불가 지역(BR)과 존재하지 않는 코드(ZZ)까지 주문받게 만들었다.
    지원 국가 확장은 창업자 결정(배송권역·관세·통화·반품 정책 동반)이다.
    """
    for country in ("BR", "ZZ", "XX", "NG"):
        with pytest.raises(UnsupportedRegionError) as exc:
            _pod_pricing_for(country)
        assert exc.value.error_code == "POD_REGION_UNSUPPORTED"
        assert exc.value.details["country"] == country.upper()
        assert set(exc.value.details["supported_countries"]) == {"KR", "US", "JP"}


@pytest.mark.asyncio
async def test_pod_quote_endpoint_returns_region_price_and_currency(client, headers):
    """GET /v1/pod/quote가 지역 단가·통화를 반환(H20 — 표시-청구 일치 단일 소스)."""
    r_us = await client.get("/v1/pod/quote", params={"country": "US", "quantity": 1}, headers=headers)
    assert r_us.status_code == 200
    assert r_us.json() == {"unit_price": 20, "shipping_fee": 5, "total_price": 25, "currency": "USD"}

    r_kr = await client.get("/v1/pod/quote", params={"country": "KR", "quantity": 2}, headers=headers)
    assert r_kr.json()["total_price"] == (18000 * 2) + 3000
    assert r_kr.json()["currency"] == "KRW"

    # L2: 미지원 국가는 400 + 명시 코드(조용한 USD 폴백 금지)
    r_br = await client.get("/v1/pod/quote", params={"country": "BR", "quantity": 1}, headers=headers)
    assert r_br.status_code == 400
    assert r_br.json()["error"]["code"] == "POD_REGION_UNSUPPORTED"

    r_zz = await client.get("/v1/pod/quote", params={"country": "ZZ", "quantity": 1}, headers=headers)
    assert r_zz.status_code == 400, "존재하지 않는 국가 코드가 통과했다"
