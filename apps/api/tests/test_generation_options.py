"""Preflight choices must match creation policy and existing paid entitlements."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.exceptions import PaymentRequiredError
from src.core.rate_limit import rate_limiter
from src.core.utils import utcnow
from src.models.db import Job, Subscription, UserCredits
from src.models.dto import Style
from src.routers.books import _enforce_free_plan_create_limits, get_generation_options
from src.services.credits import credits_service

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def enforce_policy(monkeypatch):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)


async def subscription(db, user_key, plan, status="active", days=10):
    db.add(Subscription(user_key=user_key, plan=plan, status=status, credits_per_month=20,
                        current_period_start=utcnow() - timedelta(days=20),
                        current_period_end=utcnow() + timedelta(days=days)))
    await db.commit()


async def test_free_options_match_server_enforcement_without_creating_state(client, headers, user_key, db_session):
    response = await client.get("/v1/books/generation-options", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"allowed_styles": ["watercolor", "cartoon"]}
    assert response.headers["cache-control"] == "private, no-store"
    for style in Style:
        if style.value in response.json()["allowed_styles"]:
            await _enforce_free_plan_create_limits(db_session, user_key, style)
        else:
            with pytest.raises(PaymentRequiredError):
                await _enforce_free_plan_create_limits(db_session, user_key, style)
    assert (await db_session.execute(select(Job))).scalars().all() == []
    assert (await db_session.execute(select(UserCredits))).scalars().all() == []


@pytest.mark.parametrize("plan,status", [("basic", "active"), ("premium", "active"), ("premium", "cancelled")])
async def test_existing_paid_rights_survive_disabled_purchases(client, headers, user_key, db_session, plan, status, monkeypatch):
    monkeypatch.setattr(settings, "purchases_enabled", False)
    await subscription(db_session, user_key, plan, status)
    response = await client.get("/v1/books/generation-options", headers=headers)
    assert response.json()["allowed_styles"] == [style.value for style in Style]
    for style in Style:
        await _enforce_free_plan_create_limits(db_session, user_key, style)


@pytest.mark.parametrize("status", ["active", "cancelled", "expired"])
async def test_expired_subscriptions_return_free_choices(client, headers, user_key, db_session, status):
    await subscription(db_session, user_key, "premium", status, days=-1)
    response = await client.get("/v1/books/generation-options", headers=headers)
    assert response.json()["allowed_styles"] == ["watercolor", "cartoon"]


async def test_other_accounts_do_not_inherit_styles(client, headers, user_key, db_session):
    await subscription(db_session, user_key, "premium")
    other = {"X-User-Key": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}
    assert (await client.get("/v1/books/generation-options", headers=other)).json()["allowed_styles"] == ["watercolor", "cartoon"]
    assert (await client.get("/v1/books/generation-options")).status_code == 422


async def test_options_follow_explicit_disabled_policy(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", False)
    response = await client.get("/v1/books/generation-options", headers=headers)
    assert response.json()["allowed_styles"] == [style.value for style in Style]


async def test_options_fail_when_entitlements_cannot_be_read(db_session, user_key, monkeypatch):
    monkeypatch.setattr(credits_service, "get_active_subscription", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        await get_generation_options(db_session, user_key)


async def test_options_are_rate_limited(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(return_value=(False, 0)))
    assert (await client.get("/v1/books/generation-options", headers=headers)).status_code == 429
