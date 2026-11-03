"""Production paid-call admission does not rely on health-check routing."""

import pytest

from src.core import cost_budget
from src.core.config import settings
from src.core.exceptions import APIError


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_unconfigured_budget_blocks_nontest_paid_calls(monkeypatch, limit):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "daily_generation_budget", limit)

    async def unexpected_redis():
        raise AssertionError("misconfiguration must fail before Redis access")

    monkeypatch.setattr(cost_budget.rate_limiter, "get_redis", unexpected_redis)
    with pytest.raises(APIError) as exc:
        await cost_budget.consume_daily_generation_budget()
    assert exc.value.status_code == 503
    assert exc.value.error_code == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_disabled_budget_keeps_existing_test_mode_behavior(monkeypatch):
    monkeypatch.setattr(settings, "testing", True)
    monkeypatch.setattr(settings, "daily_generation_budget", 0)
    assert await cost_budget.consume_daily_generation_budget() == (True, 0)


@pytest.mark.asyncio
async def test_text_character_route_blocks_before_paid_provider(monkeypatch):
    from src.core import generation_access
    from src.routers import characters
    from src.services import provider_runtime

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "daily_generation_budget", 0)
    calls = []

    async def allowed(*_args, **_kwargs):
        return None

    async def paid_provider(**_kwargs):
        calls.append("paid")
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(characters, "require_parental_consent", allowed)
    monkeypatch.setattr(generation_access, "require_generation_access", lambda _key: None)
    monkeypatch.setattr(provider_runtime, "ensure_generation_available", allowed)
    monkeypatch.setattr(
        characters.photo_character_service, "create_character_from_text", paid_provider
    )
    with pytest.raises(APIError) as exc:
        await characters.create_character_from_text(
            name="Test", age="5", traits="kind", style="cartoon",
            db=object(), user_key="synthetic-user",
        )
    assert exc.value.status_code == 503
    assert calls == []


@pytest.mark.asyncio
async def test_audio_provider_budget_guard_also_blocks_without_budget(monkeypatch):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "daily_generation_budget", 0)
    with pytest.raises(APIError) as exc:
        await cost_budget.require_daily_generation_budget("audio.tts")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_http_character_route_denies_paid_work_with_no_budget(client, headers, monkeypatch):
    from src.core import generation_access
    from src.core.rate_limit import check_rate_limit
    from src.main import app
    from src.routers import characters
    from src.services import provider_runtime

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "daily_generation_budget", 0)
    calls = []

    async def allowed(*_args, **_kwargs):
        return None

    async def paid_provider(**_kwargs):
        calls.append("paid")
        raise AssertionError("provider must not be called")

    async def no_rate_limit():
        return None

    app.dependency_overrides[check_rate_limit] = no_rate_limit
    monkeypatch.setattr(characters, "require_parental_consent", allowed)
    monkeypatch.setattr(generation_access, "require_generation_access", lambda _key: None)
    monkeypatch.setattr(provider_runtime, "ensure_generation_available", allowed)
    monkeypatch.setattr(
        characters.photo_character_service, "create_character_from_text", paid_provider
    )
    try:
        response = await client.post(
            "/v1/characters/from-text",
            data={"name": "Test", "age": "5", "traits": "kind", "style": "cartoon"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(check_rate_limit, None)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert calls == []
