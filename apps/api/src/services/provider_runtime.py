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
_REASONS = {"quota_exhausted", "credentials_rejected", "request_succeeded", "invalid_response"}
_PERMANENT_FAILURES = {"quota_exhausted", "credentials_rejected"}
_REASON_STATUS = {"request_succeeded": "healthy", "invalid_response": "unverified",
                  "quota_exhausted": "unavailable", "credentials_rejected": "unavailable"}
_INVALID_RESPONSE_UPDATE = """
local current = redis.call('GET', KEYS[1])
if current then
  local ok, decoded = pcall(cjson.decode, current)
  if not ok or type(decoded) ~= 'table' then return -1 end
  if decoded.reason == 'credentials_rejected' or decoded.reason == 'quota_exhausted' then return 0 end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""
_VALIDATED_SUCCESS_UPDATE = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('DEL', KEYS[2])
return 1
"""


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


async def _record_observation(request: ProviderRequest, reason: str, *, validated: bool = False) -> None:
    assert reason in _REASONS
    status = "healthy" if reason == "request_succeeded" else "unverified" if reason == "invalid_response" else "unavailable"
    value = {"status": status,
             "reason": reason, "observed_at": time.time()}
    current = _LOCAL_OBSERVATIONS.get(request.identity, {})
    if reason != "invalid_response" or current.get("reason") not in _PERMANENT_FAILURES:
        _LOCAL_OBSERVATIONS[request.identity] = value
    if settings.testing:
        return
    try:
        from src.core.rate_limit import rate_limiter
        client = await rate_limiter.get_redis()
        invalid_key = request.identity + ':invalid'
        if reason == "invalid_response":
            # Publish the conservative marker first: if Lua is denied or
            # interrupted, other workers must not keep an old healthy result.
            await client.set(invalid_key, '1', ex=settings.provider_observation_ttl_seconds)
            result = await client.eval(_INVALID_RESPONSE_UPDATE, 1, request.identity,
                                       json.dumps(value), settings.provider_observation_ttl_seconds)
            if result not in (0, 1):
                raise ValueError("Observation state is invalid")
        elif reason == "request_succeeded" and validated:
            result = await client.eval(_VALIDATED_SUCCESS_UPDATE, 2, request.identity, invalid_key,
                                       json.dumps(value), settings.provider_observation_ttl_seconds)
            if result != 1:
                raise ValueError("Observation state is invalid")
        else:
            await client.set(request.identity, json.dumps(value), ex=settings.provider_observation_ttl_seconds)
    except Exception:
        # Infrastructure readiness already fails when Redis is unavailable.
        logger.warning("Provider availability observation storage unavailable")


async def observe_validated_provider_success(request: ProviderRequest) -> None:
    """Record a non-HTTP success only after its adapter validates the result."""
    request.metrics['status'] = 'succeeded'
    await _record_observation(request, 'request_succeeded', validated=True)


async def observe_invalid_provider_response(request: ProviderRequest) -> None:
    """Replace stale success with unknown without clearing a permanent failure."""
    request.metrics['status'] = 'failed'
    await _record_observation(request, 'invalid_response')


async def observe_json_output(request: ProviderRequest, text: object) -> None:
    """Accept syntactically valid structured output; schema checks remain separate."""
    try:
        if not isinstance(text, str):
            raise ValueError('output is not text')
        content = text.strip()
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        if not isinstance(json.loads(content.strip()), (dict, list)):
            raise ValueError('output is not structured')
    except (TypeError, ValueError):
        await observe_invalid_provider_response(request)
        return
    await observe_validated_provider_success(request)


async def observe_provider_response(request: ProviderRequest, response, *, defer_success: bool = False) -> ErrorCode | None:
    """Classify permanent failures before general 429 retry handling."""
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    status = response.status_code
    success = 200 <= status < 300 and not payload.get("error")
    request.metrics["status"] = ("incomplete" if defer_success else "succeeded") if success else "failed"
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
    elif success and not defer_success:
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


def _configured_providers(*, include_photo: bool, include_audio: bool = False) -> list[tuple[str, str, str, str | None]]:
    providers = [(settings.llm_provider, settings.llm_model, "llm", settings.llm_api_key),
                 (settings.image_provider, settings.image_model, "image", settings.image_api_key)]
    if include_photo and settings.photo_processing_enabled:
        providers.append((settings.photo_analysis_provider, settings.photo_analysis_model, "llm", settings.photo_analysis_api_key))
    if include_audio and settings.audio_feature_enabled:
        tts_keys = {"openai": settings.openai_tts_api_key, "openai_realtime": settings.openai_tts_api_key,
                    "google": settings.google_tts_api_key,
                    "google_gemini": settings.google_gemini_tts_project,
                    "elevenlabs": settings.elevenlabs_api_key}
        realtime_model = None
        if settings.tts_provider == 'openai_realtime':
            from src.services.realtime_tts import MODEL
            realtime_model = MODEL
        providers.append((settings.tts_provider,
            settings.openai_tts_model if settings.tts_provider == "openai" else
            realtime_model if settings.tts_provider == "openai_realtime" else
            "gemini-2.5-flash-tts" if settings.tts_provider == "google_gemini" else settings.tts_provider + "-tts",
            "tts", tts_keys.get(settings.tts_provider)))
        # Narration-only mode deliberately leaves pronunciation unavailable
        # when STT is not configured. Do not require observations from that
        # inactive provider, but continue gating TTS and any configured STT.
        from src.core.audio_feature import stt_readiness_issues
        if not settings.audio_narration_only_enabled or not stt_readiness_issues():
            stt_key = (settings.stt_api_key or (
                settings.llm_api_key if settings.llm_provider == "openai" else None
            )) if settings.stt_provider == "openai" else settings.google_stt_api_key
            providers.append((settings.stt_provider,
                settings.stt_model if settings.stt_provider == "openai" else settings.stt_provider + "-stt",
                "stt", stt_key))
    return list(dict.fromkeys(item for item in providers if item[0] != "mock"))


async def provider_runtime_status(*, include_photo: bool = True, include_audio: bool = False) -> dict:
    observations = []
    configured = _configured_providers(include_photo=include_photo, include_audio=include_audio)
    client = None
    if not settings.testing and configured:
        try:
            from src.core.rate_limit import rate_limiter
            client = await rate_limiter.get_redis()
        except Exception:
            pass
    for provider, model, kind, api_key in configured:
        identity = _identity(provider, model, kind, api_key)
        # Production health is shared across processes. A missing Redis entry
        # must not revive a success cached in this particular process.
        value = _LOCAL_OBSERVATIONS.get(identity) if settings.testing else None
        if client is not None:
            try:
                raw = await client.get(identity)
                if raw is not None:
                    value = json.loads(raw)
                invalid = await client.get(identity + ':invalid')
                if invalid is not None and (not isinstance(value, dict) or not isinstance(value.get('reason'), str)
                                            or value.get('reason') not in _PERMANENT_FAILURES):
                    value = {"status": "unverified", "reason": "invalid_response", "observed_at": time.time()}
            except Exception:
                # A failed observation read cannot prove provider health,
                # even if this process has an older local success.
                value = {"status": "unverified", "reason": "no_recent_observation", "observed_at": time.time()}
        if (not isinstance(value, dict) or not isinstance(value.get("reason"), str)
                or value.get("reason") not in _REASONS
                or value.get("status") != _REASON_STATUS.get(value.get("reason"))
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
