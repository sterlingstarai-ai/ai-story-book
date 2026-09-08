from datetime import datetime, timezone, timedelta

from src.routers.credits import TransactionResponse, SubscriptionResponse


def test_naive_utc_transaction_has_wire_timezone():
    response = TransactionResponse(
        id=1, amount=1, balance_after=2, transaction_type="bonus",
        description=None, created_at=datetime(2026, 9, 8, 4, 30),
    )
    assert response.model_dump(mode="json")["created_at"] == "2026-09-08T04:30:00Z"


def test_subscription_preserves_aware_offset():
    response = SubscriptionResponse(
        plan="free", plan_name="Free", status="active", credits_per_month=2,
        current_period_end=datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=9))),
        features=[],
    )
    assert response.model_dump(mode="json")["current_period_end"] == "2026-10-01T00:00:00+09:00"
