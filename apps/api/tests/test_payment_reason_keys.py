"""M5 회귀 게이트 — 402 응답이 안정 사유 키(details.reason)를 반드시 싣는다.

2026-08-09 중간 E2E: 모바일이 402 를 '플랜 업그레이드' 와 '크레딧 충전' 중 무엇으로
보여줄지 **서버가 준 한국어 메시지 본문을 부분 매칭**해 정했다
(`message.contains('스타일')`, `message.contains('오디오')`…). 서버가 402 를 로컬라이즈
하거나 문구를 다듬는 순간 조용히 깨지는 결합이다.

여기서는 서버가 모든 402 경로에 안정 키를 싣는지 고정한다. 짝 테스트는 모바일
`test/api_error_test.dart` 의 '402 분기는 reason 기반' 케이스.
"""

import pytest

from src.core.errors import PaymentReason
from src.core.exceptions import PaymentRequiredError
from src.routers.books import (
    _enforce_free_plan_create_limits,
    _enforce_free_plan_feature_access,
)


@pytest.fixture()
def free_plan_enforced(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True, raising=False)
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True, raising=False)


def test_plan_upgrade_reason_set_is_explicit():
    """'업그레이드로 해소되는 사유'가 코드에 명시돼 있다(클라 분기의 정본)."""
    assert PaymentReason.PLAN_UPGRADE == {
        PaymentReason.FREE_PLAN_STYLE,
        PaymentReason.FREE_PLAN_MONTHLY_LIMIT,
        PaymentReason.FREE_PLAN_FEATURE,
    }
    assert PaymentReason.INSUFFICIENT_CREDITS not in PaymentReason.PLAN_UPGRADE
    assert PaymentReason.CREDIT_CHARGE_FAILED not in PaymentReason.PLAN_UPGRADE


@pytest.mark.asyncio
async def test_style_restriction_carries_reason(db_session, free_plan_enforced):
    with pytest.raises(PaymentRequiredError) as exc:
        await _enforce_free_plan_create_limits(db_session, "u-style", "pixel")
    assert exc.value.details["reason"] == PaymentReason.FREE_PLAN_STYLE


@pytest.mark.asyncio
async def test_blocked_feature_carries_reason(db_session, free_plan_enforced):
    for feature in ("pdf", "audio"):
        with pytest.raises(PaymentRequiredError) as exc:
            await _enforce_free_plan_feature_access(db_session, "u-feat", feature)
        details = exc.value.details
        assert details["reason"] == PaymentReason.FREE_PLAN_FEATURE
        assert details.get("feature"), "어떤 기능이 막혔는지 함께 내려야 한다"


@pytest.mark.asyncio
async def test_monthly_limit_carries_reason(db_session, free_plan_enforced, monkeypatch):
    from src.routers import books as books_router

    async def over_limit(_db, _user_key):
        return 999

    monkeypatch.setattr(books_router, "_count_monthly_book_creations", over_limit)

    with pytest.raises(PaymentRequiredError) as exc:
        await _enforce_free_plan_create_limits(db_session, "u-month", "watercolor")
    details = exc.value.details
    assert details["reason"] == PaymentReason.FREE_PLAN_MONTHLY_LIMIT
    assert isinstance(details.get("monthly_limit"), int)


def test_credit_reasons_are_not_plan_upgrade():
    """크레딧 부족은 업그레이드가 아니라 충전 안내여야 한다(UI 오분류 방지)."""
    err = PaymentRequiredError(
        "크레딧이 부족합니다.", details={"reason": PaymentReason.INSUFFICIENT_CREDITS}
    )
    assert err.details["reason"] not in PaymentReason.PLAN_UPGRADE
