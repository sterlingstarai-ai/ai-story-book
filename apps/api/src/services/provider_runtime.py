"""Numeric request usage and shared observations of provider availability.

Health probes never call paid AI APIs. Observations contain only fixed status
codes; credential fingerprints identify the same configuration across workers.
No prompts, image URLs, response bodies, user keys or API keys are retained.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
from functools import wraps
from inspect import signature
import json
import math
import time

import structlog

from src.core.config import settings
from src.core.errors import ErrorCode

logger = structlog.get_logger()
_LOCAL_OBSERVATIONS: dict[str, dict] = {}
_SCOPE: ContextVar[dict | None] = ContextVar("provider_usage", default=None)
_QUOTA_CODES = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached", "billing_not_active", "organization_usage_limit_exceeded",
                "organization_spend_limit_exceeded", "project_spend_limit_exceeded"}
_REASONS = {"quota_exhausted", "credentials_rejected", "request_succeeded"}


def _number(value) -> int:
    return value if type(value) is int and 0 <= value <= 10**10 else 0


def _identity(provider: str, model: str, kind: str, api_key: str | None) -> str:
    value = json.dumps([provider, model, kind, api_key], separators=(",", ":"))
    return "provider_runtime:v1:" + hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def job_provider_usage(job_id: str):
    """Share counters across concurrent image tasks; flush on success or failure."""
    if _SCOPE.get() is not None:
        yield
        return
    usage = {"job_id": job_id, "started": time.monotonic(), "requests": []}
    token = _SCOPE.set(usage)
    try:
        yield
    finally:
        requests = usage["requests"]
        estimates = [item["estimated_cost_usd"] for item in requests]
        logger.warning(
            "Generation provider usage", job_id=job_id,
            duration_seconds=round(time.monotonic() - usage["started"], 3),
            provider_requests=len(requests),
            image_requests=sum(item["kind"] == "image" for item in requests),
            input_tokens=sum(item["input_tokens"] for item in requests),
            output_tokens=sum(item["output_tokens"] for item in requests),
            failed_requests=sum(item["status"] != "succeeded" for item in requests),
            estimated_cost_usd=(round(sum(estimates), 8) if all(n is not None for n in estimates) else None),
            cost_is_estimate=True,
        )
        _SCOPE.reset(token)


def record_job_provider_usage(fn):
    """Cover ancillary job steps too; nested book work shares its outer scope."""
    call_signature = signature(fn)
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        job_id = call_signature.bind(*args, **kwargs).arguments["job_id"]
        with job_provider_usage(job_id):
            return await fn(*args, **kwargs)
    return wrapped


@dataclass
class ProviderRequest:
    provider: str
    model: str
    kind: str
    identity: str
    metrics: dict = field(default_factory=dict)


def begin_provider_request(provider: str, model: str, kind: str, api_key: str | None) -> ProviderRequest:
    metrics = {"kind": kind, "status": "incomplete", "input_tokens": 0, "output_tokens": 0,
               "estimated_cost_usd": None}
    scope = _SCOPE.get()
    if scope is not None:
        scope["requests"].append(metrics)
    return ProviderRequest(provider, model, kind, _identity(provider, model, kind, api_key), metrics)


def _estimated_cost(request: ProviderRequest, usage: dict) -> float | None:
    # Empty configuration explicitly means unknown, never a zero-cost claim.
    # Prices are operator-maintained reference rates, not a provider invoice.
    try:
        prices = json.loads(settings.provider_usage_prices_json).get(request.model, {})
        image_price = prices.get("image_request_usd") if request.kind == "image" else None
        if image_price is not None:
            cost = float(image_price)
        else:
            cost = (request.metrics["input_tokens"] * float(prices["input_usd_per_million"])
                    + request.metrics["output_tokens"] * float(prices["output_usd_per_million"])) / 1_000_000
            if not usage:
                return None
        return round(cost, 8) if math.isfinite(cost) and cost >= 0 else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


async def _record_observation(request: ProviderRequest, reason: str) -> None:
    assert reason in _REASONS
    value = {"status": "healthy" if reason == "request_succeeded" else "unavailable",
             "reason": reason, "observed_at": time.time()}
    _LOCAL_OBSERVATIONS[request.identity] = value
    if settings.testing:
        return
    try:
        from src.core.rate_limit import rate_limiter
        client = await rate_limiter.get_redis()
        await client.set(request.identity, json.dumps(value), ex=settings.provider_observation_ttl_seconds)
    except Exception:
        # Infrastructure readiness already fails when Redis is unavailable.
        logger.warning("Provider availability observation storage unavailable")


async def observe_provider_response(request: ProviderRequest, response) -> ErrorCode | None:
    """Classify permanent failures before general 429 retry handling."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    status = response.status_code
    success = 200 <= status < 300 and not payload.get("error")
    request.metrics["status"] = "succeeded" if success else "failed"
    usage = payload.get("usage", payload.get("usageMetadata", {}))
    usage = usage if isinstance(usage, dict) else {}
    request.metrics["input_tokens"] = _number(usage.get("input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount"))))
    request.metrics["output_tokens"] = _number(usage.get("output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount"))))
    request.metrics["estimated_cost_usd"] = _estimated_cost(request, usage) if success else None
    error = payload.get("error", {})
    error = error if isinstance(error, dict) else {}
    error_code = error.get("code")
    error_type = error.get("type")
    reason = None
    canonical = None
    if (isinstance(error_code, str) and error_code in _QUOTA_CODES) or (isinstance(error_type, str) and error_type in _QUOTA_CODES):
        reason, canonical = "quota_exhausted", ErrorCode.AI_PROVIDER_UNAVAILABLE
    elif status in {401, 403}:
        reason, canonical = "credentials_rejected", ErrorCode.AI_PROVIDER_UNAVAILABLE
    elif success:
        reason = "request_succeeded"
    if reason:
        await _record_observation(request, reason)
    scope = _SCOPE.get()
    logger.warning(
        "AI provider request usage", job_id=scope["job_id"] if scope else None,
        provider=request.provider, model=request.model, request_kind=request.kind,
        http_status=status, availability_reason=reason,
        input_tokens=request.metrics["input_tokens"], output_tokens=request.metrics["output_tokens"],
        estimated_cost_usd=request.metrics["estimated_cost_usd"], cost_is_estimate=True,
    )
    return canonical


def _configured_providers(*, include_photo: bool) -> list[tuple[str, str, str, str | None]]:
    providers = [(settings.llm_provider, settings.llm_model, "llm", settings.llm_api_key),
                 (settings.image_provider, settings.image_model, "image", settings.image_api_key)]
    if include_photo and settings.photo_processing_enabled:
        providers.append((settings.photo_analysis_provider, settings.photo_analysis_model, "llm", settings.photo_analysis_api_key))
    return list(dict.fromkeys(item for item in providers if item[0] != "mock"))


async def provider_runtime_status(*, include_photo: bool = True) -> dict:
    observations = []
    configured = _configured_providers(include_photo=include_photo)
    client = None
    if not settings.testing and configured:
        try:
            from src.core.rate_limit import rate_limiter
            client = await rate_limiter.get_redis()
        except Exception:
            pass
    for provider, model, kind, api_key in configured:
        identity = _identity(provider, model, kind, api_key)
        value = _LOCAL_OBSERVATIONS.get(identity)
        if client is not None:
            try:
                raw = await client.get(identity)
                if raw is not None:
                    value = json.loads(raw)
            except Exception:
                pass
        if (not isinstance(value, dict) or value.get("reason") not in _REASONS
                or type(value.get("observed_at")) not in {int, float}
                or not 0 <= time.time() - value["observed_at"] < settings.provider_observation_ttl_seconds):
            value = {"status": "unverified", "reason": "no_recent_observation"}
        observations.append({"provider": provider, "kind": kind, **value})
    states = {item["status"] for item in observations}
    status = "unavailable" if "unavailable" in states else "unverified" if "unverified" in states else "healthy"
    return {"status": status, "observations": observations}


async def ensure_generation_available() -> None:
    """Avoid charging users while a shared, recent permanent outage is known."""
    state = await provider_runtime_status(include_photo=False)
    if state["status"] == "unavailable":
        from src.core.exceptions import APIError
        raise APIError(503, "AI_SERVICE_UNAVAILABLE", "동화 만들기를 잠시 이용할 수 없어요. 잠시 후 다시 확인해 주세요.",
                       details={"reason": "provider_unavailable"})
