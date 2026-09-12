import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.core.config import settings
from src.core.cost_budget import generation_budget_snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,status,used", [(None, "available", 0), (b"16", "available", 16), (b"20", "exhausted", 20), (b"bad", "unavailable", None), (b"-1", "unavailable", None)])
async def test_budget_snapshot_is_read_only(monkeypatch, raw, status, used):
    from src.core.cost_budget import rate_limiter
    client = AsyncMock()
    client.get.return_value = raw
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=client))
    monkeypatch.setattr(settings, "daily_generation_budget", 20)
    result = await generation_budget_snapshot()
    assert result == {"limit": 20, "used": used, "unit": "generation_requests", "status": status}
    client.incr.assert_not_awaited()
    client.expire.assert_not_awaited()


def test_monitor_alerts_and_does_not_forward_private_fields(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    assess = importlib.import_module("check_operations").assess
    payload = {"status": "healthy", "secret": "never-forward", "jobs": {
        "queued": 1, "running": 1, "stuck": 0, "completed_last_hour": 2, "failed_last_hour": 0,
    }, "generation_budget": {"used": 2, "limit": 20}}
    assert assess(payload)["status"] == "OK"
    payload["jobs"]["stuck"] = 1
    payload["jobs"]["failed_last_hour"] = 1
    payload["generation_budget"]["used"] = 16
    result = assess(payload)
    assert result["alerts"] == ["stuck_jobs", "generation_failures_last_hour", "generation_budget_near_limit"]
    assert "never-forward" not in str(result)
    assert assess({})["status"] == "ALERT"
    assert assess(None)["status"] == "ALERT"


def test_generation_configuration_is_forwarded_to_all_deployments():
    root = Path(__file__).resolve().parents[3]
    names = ["GENERATION_ACCESS_MODE", "GENERATION_ALLOWED_USER_HASHES"]
    for name in names:
        for file in ["apps/api/.env.example", "infra/.env.example", "env.schema.json", ".github/workflows/ci.yml"]:
            assert name in (root / file).read_text()
        for file in ["infra/docker-compose.yml", "infra/docker-compose.prod.yml", "infra/docker-compose.external.yml"]:
            assert "${" + name + ":-" in (root / file).read_text()
        render = (root / "infra/render.yaml.template").read_text()
        assert f"key: {name}" in render and f"envVarKey: {name}" in render
