"""A release cannot silently omit visual review or use an unsupported model."""

import pytest

from src.core.config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,provider,model,reason", [
    (False, "openai", "gpt-5.6-sol", "illustration_quality_disabled"),
    (True, "anthropic", "claude-sonnet-5", "illustration_quality_model_unsupported"),
    (True, "openai", "gpt-unverified", "illustration_quality_model_unsupported"),
    (True, "openai", "gpt-5.6-sol", None),
])
async def test_readiness_requires_supported_visual_review(client, monkeypatch, enabled, provider, model, reason):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "illustration_quality_enabled", enabled)
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(settings, "admin_api_key", "review-test-admin")
    details = await client.get("/health/detailed", headers={"X-Admin-Key": "review-test-admin"})
    reasons = details.json().get("missing_keys", [])
    if reason:
        assert reason in reasons
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert "missing_keys" not in response.json()
    else:
        assert not any(item.startswith("illustration_quality_") for item in reasons)
