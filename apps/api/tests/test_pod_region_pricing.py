"""P1-6: POD 지역 가격 — 배송 국가 기준 서버 산출(클라이언트 가격 미신뢰, 글로벌)."""

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
