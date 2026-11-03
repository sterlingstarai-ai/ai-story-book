"""Actual HTTP error classification, bounded retries and shared availability."""
import asyncio
import json
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, LLMError, StoryBookError, is_retryable
from src.services import provider_runtime as runtime, openai_contract, orchestrator, image


@pytest.fixture(autouse=True)
def isolated_observations(monkeypatch):
    monkeypatch.setattr(runtime, "_LOCAL_OBSERVATIONS", {})
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_model", "gpt-5.6-sol")
    monkeypatch.setattr(settings, "llm_api_key", "runtime-test-text-credential")
    monkeypatch.setattr(settings, "image_provider", "openai")
    monkeypatch.setattr(settings, "image_model", "gpt-image-2")
    monkeypatch.setattr(settings, "image_api_key", "runtime-test-image-credential")
    monkeypatch.setattr(settings, "photo_processing_enabled", False)


def request(kind="llm"):
    return runtime.begin_provider_request("openai", settings.llm_model if kind == "llm" else settings.image_model,
        kind, settings.llm_api_key if kind == "llm" else settings.image_api_key)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["insufficient_quota", "credit_balance_exhausted"])
async def test_openai_exhausted_quota_is_single_http_attempt_and_non_retryable(monkeypatch, code):
    calls = []
    def response(req):
        calls.append(req)
        return httpx.Response(429, json={"error": {"code": code, "message": "private provider response"}})
    client = httpx.AsyncClient
    monkeypatch.setattr(openai_contract, "httpx", SimpleNamespace(
        AsyncClient=lambda **kw: client(transport=httpx.MockTransport(response), **kw),
        TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError,
    ))
    with pytest.raises(LLMError) as caught:
        await openai_contract.request_openai_json(model=settings.llm_model, api_key=settings.llm_api_key,
            timeout=1, user_prompt="private narrative", max_tokens=16)
    assert caught.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert not is_retryable(caught.value) and len(calls) == 1
    assert "private" not in str(caught.value)
    state = await runtime.provider_runtime_status()
    assert state["status"] == "unavailable"
    from src.core.exceptions import APIError
    with pytest.raises(APIError) as rejection:
        await runtime.ensure_generation_available()
    assert rejection.value.status_code == 503


@pytest.mark.asyncio
async def test_true_rate_limit_remains_transient_and_does_not_claim_exhausted_balance():
    result = await runtime.observe_provider_response(request(), httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}}))
    assert result is None
    assert (await runtime.provider_runtime_status())["status"] == "unverified"
    await runtime.ensure_generation_available()


@pytest.mark.asyncio
async def test_quota_failure_is_seen_across_workers_without_exposing_credentials(monkeypatch):
    from src.core.rate_limit import rate_limiter
    stored = {}
    async def put(key, value, ex):
        stored[key] = value
    client = SimpleNamespace(set=put, get=AsyncMock(side_effect=lambda key: stored.get(key)))
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=client))
    await runtime.observe_provider_response(request(), httpx.Response(429, json={"error": {"code": "insufficient_quota"}}))
    runtime._LOCAL_OBSERVATIONS.clear()  # Separate API process must use Redis.
    assert (await runtime.provider_runtime_status())["status"] == "unavailable"
    assert settings.llm_api_key not in json.dumps(stored)
    assert "insufficient_quota" not in json.dumps(stored)
    assert "quota_exhausted" in json.dumps(stored)


@pytest.mark.asyncio
async def test_expiry_and_credential_rotation_become_unverified_not_healthy(monkeypatch):
    await runtime.observe_provider_response(request(), httpx.Response(401, json={}))
    assert (await runtime.provider_runtime_status())["status"] == "unavailable"
    monkeypatch.setattr(settings, "llm_api_key", "rotated-test-credential")
    assert (await runtime.provider_runtime_status())["status"] == "unverified"
    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    await runtime.observe_provider_response(request("image"), httpx.Response(200, json={}))
    assert (await runtime.provider_runtime_status())["status"] == "healthy"
    for value in runtime._LOCAL_OBSERVATIONS.values():
        value["observed_at"] -= settings.provider_observation_ttl_seconds + 1
    assert (await runtime.provider_runtime_status())["status"] == "unverified"


@pytest.mark.asyncio
async def test_successful_explicit_probe_clears_observed_failure():
    await runtime.observe_provider_response(request(), httpx.Response(429, json={"error": {"code": "insufficient_quota"}}))
    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    await runtime.observe_provider_response(request("image"), httpx.Response(200, json={}))
    assert (await runtime.provider_runtime_status())["status"] == "healthy"


@pytest.mark.asyncio
async def test_narration_only_excludes_unconfigured_stt_but_keeps_tts_gate(monkeypatch):
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', True)
    monkeypatch.setattr(settings, 'tts_provider', 'google_gemini')
    monkeypatch.setattr(settings, 'google_gemini_tts_project', 'test-project-123')
    monkeypatch.setattr(settings, 'stt_provider', 'google')
    monkeypatch.setattr(settings, 'google_stt_api_key', None)
    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    await runtime.observe_provider_response(request('image'), httpx.Response(200, json={}))
    narration = runtime.begin_provider_request('google_gemini', 'gemini-2.5-flash-tts',
                                               'tts', 'test-project-123')
    state = await runtime.provider_runtime_status(include_audio=True)
    assert state['status'] == 'unverified'
    assert {item['kind'] for item in state['observations']} == {'llm', 'image', 'tts'}
    await runtime.observe_provider_response(narration, httpx.Response(200, json={}))
    assert (await runtime.provider_runtime_status(include_audio=True))['status'] == 'healthy'
    await runtime.observe_provider_response(narration, httpx.Response(401, json={}))
    assert (await runtime.provider_runtime_status(include_audio=True))['status'] == 'unavailable'


@pytest.mark.asyncio
async def test_narration_only_still_checks_configured_stt(monkeypatch):
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', True)
    monkeypatch.setattr(settings, 'tts_provider', 'google_gemini')
    monkeypatch.setattr(settings, 'google_gemini_tts_project', 'test-project-123')
    monkeypatch.setattr(settings, 'stt_provider', 'google')
    monkeypatch.setattr(settings, 'google_stt_api_key', 'synthetic-key')
    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    await runtime.observe_provider_response(request('image'), httpx.Response(200, json={}))
    narration = runtime.begin_provider_request('google_gemini', 'gemini-2.5-flash-tts',
                                               'tts', 'test-project-123')
    await runtime.observe_provider_response(narration, httpx.Response(200, json={}))
    state = await runtime.provider_runtime_status(include_audio=True)
    assert state['status'] == 'unverified'
    assert any(item['kind'] == 'stt' and item['status'] == 'unverified' for item in state['observations'])


@pytest.mark.asyncio
async def test_realtime_observation_matches_readiness_and_requires_valid_audio(monkeypatch):
    from src.services.tts import RealtimeTTSProvider
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'audio_narration_only_enabled', True)
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'synthetic-realtime-key')
    monkeypatch.setattr(settings, 'stt_provider', 'mock')
    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    await runtime.observe_provider_response(request('image'), httpx.Response(200, json={}))
    synth = AsyncMock(side_effect=ValueError('invalid audio'))
    monkeypatch.setattr('src.services.realtime_tts.synthesize_realtime', synth)
    with pytest.raises(ValueError):
        await RealtimeTTSProvider().synthesize('test')
    assert (await runtime.provider_runtime_status(include_audio=True))['status'] == 'unverified'
    synth.side_effect = None
    synth.return_value = b'RIFF-synthetic'
    assert await RealtimeTTSProvider().synthesize('test') == b'RIFF-synthetic'
    state = await runtime.provider_runtime_status(include_audio=True)
    assert state['status'] == 'healthy'
    assert any(item['provider'] == 'openai_realtime' and item['kind'] == 'tts'
               and item['status'] == 'healthy' for item in state['observations'])
    assert 'synthetic-realtime-key' not in json.dumps(state)


@pytest.mark.asyncio
async def test_readiness_unavailable_without_paid_health_request(client, monkeypatch):
    monkeypatch.setattr(settings, "testing", True)
    await runtime.observe_provider_response(request(), httpx.Response(429, json={"error": {"code": "insufficient_quota"}}))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["services"]["provider_runtime"] == "unavailable"
    assert data["services"]["provider_access_observed"] is False
    assert "quota_exhausted" not in response.text
    assert settings.llm_api_key not in response.text


@pytest.fixture
def configured_production_readiness(client, monkeypatch):
    """Healthy infrastructure with real-provider settings and fake HTTP/Redis."""
    from src.services import storage, image_quality, job_monitor
    from src.core.rate_limit import rate_limiter

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "illustration_quality_enabled", True)
    monkeypatch.setattr(settings, "purchases_enabled", False)
    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    monkeypatch.setattr(settings, "apple_iap_shared_secret", None)
    monkeypatch.setattr(settings, "google_play_package_name", None)
    monkeypatch.setattr(settings, "audio_feature_enabled", False)
    monkeypatch.setattr(settings, "pod_ordering_enabled", False)
    monkeypatch.setattr(settings, "daily_generation_budget", 20)
    monkeypatch.setattr(storage, "ensure_bucket_exists", AsyncMock())
    monkeypatch.setattr(image_quality, "review_provider_configured", lambda: True)
    monkeypatch.setattr(job_monitor, "get_job_metrics", AsyncMock(return_value={}))
    monkeypatch.setattr(rate_limiter, "ping", AsyncMock(return_value=True))
    stored = {}
    async def put(key, value, ex):
        stored[key] = value
    async def evaluate(script, count, *args):
        if script == runtime._VALIDATED_SUCCESS_UPDATE and count == 2:
            key, invalid_key, value, _ttl = args
            stored[key] = value
            stored.pop(invalid_key, None)
            return 1
        if script == runtime._INVALID_RESPONSE_UPDATE and count == 1:
            key, value, _ttl = args
            previous = json.loads(stored.get(key, '{}'))
            if previous.get('reason') in {'credentials_rejected', 'quota_exhausted'}:
                return 0
            stored[key] = value
            return 1
        raise AssertionError('unexpected provider observation script')
    redis = SimpleNamespace(set=put, get=AsyncMock(side_effect=lambda key: stored.get(key)), eval=evaluate)
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=redis))


@pytest.mark.asyncio
async def test_unobserved_real_credentials_cannot_pass_production_readiness(
    client, configured_production_readiness, monkeypatch
):
    # Health must not spend money to discover whether configured credentials work.
    paid_request = AsyncMock(side_effect=AssertionError("health must not call providers"))
    monkeypatch.setattr(openai_contract, "request_openai_json", paid_request)
    monkeypatch.setattr(image, "generate_image", paid_request)

    response = await client.get("/health/ready")
    assert response.status_code == 503
    services = response.json()["services"]
    assert all(services[key] == "healthy" for key in (
        "database", "redis", "job_monitor", "storage", "provider_keys"
    ))
    assert services["provider_runtime"] == "unverified"
    assert services["provider_access_observed"] is False
    assert (await client.get("/health/live")).status_code == 200
    # An explicit private generation can still establish first observations.
    await runtime.ensure_generation_available()
    paid_request.assert_not_called()


@pytest.mark.asyncio
async def test_production_readiness_requires_all_probes_and_recovers_after_quota(
    client, configured_production_readiness
):
    from src.core.exceptions import APIError

    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    assert (await client.get("/health/ready")).status_code == 503  # Image unverified.
    await runtime.observe_provider_response(request("image"), httpx.Response(200, json={}))
    runtime._LOCAL_OBSERVATIONS.clear()  # API sees the worker's shared observation.
    assert (await client.get("/health/ready")).status_code == 200

    await runtime.observe_provider_response(request(), httpx.Response(429, json={
        "error": {"code": "insufficient_quota"}
    }))
    runtime._LOCAL_OBSERVATIONS.clear()
    for _ in range(2):
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["services"]["provider_runtime"] == "unavailable"
    with pytest.raises(APIError):
        await runtime.ensure_generation_available()

    # Billing changes alone cannot erase the observed failure. A subsequent
    # successful response from an explicit probe restores the exact combination.
    await runtime.observe_provider_response(request(), httpx.Response(200, json={}))
    runtime._LOCAL_OBSERVATIONS.clear()
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["services"]["provider_access_observed"] is True
    await runtime.ensure_generation_available()


@pytest.mark.asyncio
async def test_explicit_preflight_recovers_quota_with_generic_json_for_separate_photo_key(
    client, configured_production_readiness, monkeypatch, capsys
):
    from src.core.rate_limit import rate_limiter
    from src.services import photo_processing, storage

    monkeypatch.setattr(settings, "photo_processing_enabled", True)
    monkeypatch.setattr(settings, "photo_analysis_provider", "openai")
    monkeypatch.setattr(settings, "photo_analysis_model", "gpt-4.1-mini")
    monkeypatch.setattr(settings, "photo_analysis_api_key", "runtime-test-photo-credential")
    monkeypatch.setattr(photo_processing, "ensure_photo_processing_ready", lambda: None)
    monkeypatch.setattr(rate_limiter, "close", AsyncMock())
    calls = []

    def response(req):
        payload = json.loads(req.content)
        calls.append(payload)
        messages = payload.get("messages", payload.get("input"))
        # OpenAI JSON mode rejects a request with no JSON instruction. Exercise
        # both the Responses book model and separate photo Chat Completions model.
        if "json" not in json.dumps(messages).lower():
            return httpx.Response(400, json={"error": {"code": "invalid_request_error"}})
        assert all(item["content"] in {"Return only JSON.", 'Return {"ok":true}.'} for item in messages)
        if "messages" in payload:
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop", "message": {"content": '{"ok":true}'}
            }]})
        return httpx.Response(200, json={"status": "completed", "output": [{
            "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": '{"ok":true}'}]
        }]})

    http_client = httpx.AsyncClient
    monkeypatch.setattr(openai_contract, "httpx", SimpleNamespace(
        AsyncClient=lambda **kw: http_client(transport=httpx.MockTransport(response), **kw),
        TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError,
    ))
    async def image_probe(prompt):
        assert prompt.positive_prompt == "A single blue circle on plain white paper, flat illustration."
        await runtime.observe_provider_response(request("image"), httpx.Response(200, json={}))
        return "https://test.invalid/operator-preflight/circle.png"
    image_call = AsyncMock(side_effect=image_probe)
    monkeypatch.setattr(image, "generate_image", image_call)
    monkeypatch.setattr(storage, "key_from_public_url", lambda _: "operator-preflight/circle.png")
    cleanup = AsyncMock(return_value=[])
    monkeypatch.setattr(storage, "delete_keys", cleanup)

    await runtime.observe_provider_response(request(), httpx.Response(429, json={
        "error": {"code": "insufficient_quota"}
    }))
    preflight = runpy.run_path("scripts/provider_preflight.py")["main"]
    assert await preflight(False) == 1
    assert not calls and image_call.await_count == 0
    assert (await client.get("/health/ready")).status_code == 503

    assert await preflight(True) == 0
    assert len(calls) == 2 and image_call.await_count == 1
    cleanup.assert_awaited_once_with(["operator-preflight/circle.png"])
    runtime._LOCAL_OBSERVATIONS.clear()
    assert (await client.get("/health/ready")).status_code == 200
    assert "runtime-test-" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_image_unavailable_does_not_retry_or_return_placeholder(monkeypatch):
    fail = AsyncMock(side_effect=StoryBookError(ErrorCode.AI_PROVIDER_UNAVAILABLE, "Unavailable"))
    monkeypatch.setattr(orchestrator, "generate_image", fail)
    with pytest.raises(StoryBookError) as caught:
        await orchestrator.generate_image_with_retry(SimpleNamespace(page=1), "test-job", 1)
    assert caught.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert fail.await_count == 1


@pytest.mark.asyncio
async def test_openai_image_exhausted_quota_is_non_retryable_on_wire(monkeypatch):
    from src.models.dto import ImagePrompt
    client = httpx.AsyncClient
    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=lambda **kw: client(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, json={"error": {"code": "insufficient_quota"}})), **kw)))
    with pytest.raises(StoryBookError) as caught:
        await image.generate_image(ImagePrompt(page=0, positive_prompt="A blue circle.", negative_prompt="text, numbers", seed=1))
    assert caught.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
    assert (await runtime.provider_runtime_status())["status"] == "unavailable"


@pytest.mark.asyncio
async def test_usage_aggregates_concurrency_and_flushes_on_failure_without_child_data(monkeypatch):
    monkeypatch.setattr(settings, "provider_usage_prices_json", json.dumps({
        settings.llm_model: {"input_usd_per_million": 2, "output_usd_per_million": 10},
        settings.image_model: {"image_request_usd": 0.1},
    }))
    async def success(kind):
        await runtime.observe_provider_response(request(kind), httpx.Response(200, json={
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": "PRIVATE_CHILD_STORY", "url": "PRIVATE_CHILD_IMAGE",
        }))
    logs = []
    monkeypatch.setattr(runtime, "logger", SimpleNamespace(warning=lambda event, **fields: logs.append({"event": event, **fields})))
    with pytest.raises(RuntimeError), runtime.job_provider_usage("qa-usage-job"):
        await asyncio.gather(success("llm"), success("image"), success("image"))
        raise RuntimeError("pipeline failed later")
    summary = [event for event in logs if event["event"] == "Generation provider usage"][0]
    assert summary["provider_requests"] == 3 and summary["image_requests"] == 2
    assert summary["input_tokens"] == 300 and summary["output_tokens"] == 60
    assert summary["estimated_cost_usd"] == 0.2004
    assert "PRIVATE_CHILD" not in json.dumps(logs)
    assert settings.llm_api_key not in json.dumps(logs)
    assert runtime._SCOPE.get() is None
