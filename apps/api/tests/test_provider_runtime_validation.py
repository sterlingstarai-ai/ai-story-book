"""Provider availability must reflect validated content, not a bare HTTP 2xx."""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.core.config import settings
from src.core.errors import LLMError
from src.models.dto import ImagePrompt
from src.services import image, openai_contract
from src.services import provider_runtime as runtime
from tests.fake_redis import FakePipeline, FakeRedis


@pytest.fixture(autouse=True)
def observation_settings(monkeypatch):
    monkeypatch.setattr(runtime, '_LOCAL_OBSERVATIONS', {})
    monkeypatch.setattr(settings, 'testing', True)
    monkeypatch.setattr(settings, 'llm_provider', 'openai')
    monkeypatch.setattr(settings, 'llm_model', 'gpt-5.6-sol')
    monkeypatch.setattr(settings, 'llm_api_key', 'synthetic-llm-key')
    monkeypatch.setattr(settings, 'image_provider', 'openai')
    monkeypatch.setattr(settings, 'image_model', 'gpt-image-2')
    monkeypatch.setattr(settings, 'image_api_key', 'synthetic-image-key')
    monkeypatch.setattr(settings, 'photo_processing_enabled', False)


def attempt(kind):
    return runtime.begin_provider_request('openai', settings.llm_model if kind == 'llm' else settings.image_model,
                                          kind, settings.llm_api_key if kind == 'llm' else settings.image_api_key)


def assistant_reply(text):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text}]}]}


@pytest.mark.asyncio
async def test_missing_shared_observation_does_not_revive_process_cache(monkeypatch):
    from src.core.rate_limit import rate_limiter

    await runtime.observe_validated_provider_success(attempt('llm'))
    await runtime.observe_validated_provider_success(attempt('image'))
    monkeypatch.setattr(settings, 'testing', False)
    monkeypatch.setattr(rate_limiter, 'get_redis', AsyncMock(return_value=FakeRedis()))
    assert (await runtime.provider_runtime_status())['status'] == 'unverified'


@pytest.mark.asyncio
async def test_inconsistent_observation_cannot_report_healthy():
    import time

    await runtime.observe_validated_provider_success(attempt('llm'))
    await runtime.observe_validated_provider_success(attempt('image'))
    runtime._LOCAL_OBSERVATIONS[attempt('llm').identity] = {
        'status': 'healthy', 'reason': 'credentials_rejected', 'observed_at': time.time(),
    }
    assert (await runtime.provider_runtime_status())['status'] == 'unverified'


@pytest.mark.asyncio
async def test_malformed_observation_fails_closed_without_raising():
    import time

    await runtime.observe_validated_provider_success(attempt('image'))
    runtime._LOCAL_OBSERVATIONS[attempt('llm').identity] = {
        'status': 'healthy', 'reason': [], 'observed_at': time.time(),
    }
    assert (await runtime.provider_runtime_status())['status'] == 'unverified'


@pytest.mark.asyncio
async def test_invalid_text_body_invalidates_old_success_then_valid_json_recovers(monkeypatch):
    llm = attempt('llm')
    await runtime.observe_validated_provider_success(llm)
    await runtime.observe_validated_provider_success(attempt('image'))
    assert (await runtime.provider_runtime_status())['status'] == 'healthy'
    body = {'status': 'completed', 'output': []}
    original = httpx.AsyncClient
    monkeypatch.setattr(openai_contract, 'httpx', SimpleNamespace(
        AsyncClient=lambda **kwargs: original(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
                                               **kwargs),
        TimeoutException=httpx.TimeoutException, HTTPError=httpx.HTTPError,
    ))
    async def invoke():
        return await openai_contract.request_openai_json(model=settings.llm_model, api_key=settings.llm_api_key,
                                                         timeout=3, user_prompt='fictional', max_tokens=50)
    with pytest.raises(LLMError):
        await invoke()
    status = await runtime.provider_runtime_status()
    assert status['status'] == 'unverified'
    assert any(o['kind'] == 'llm' and o['reason'] == 'invalid_response' for o in status['observations'])
    body.clear()
    body.update(assistant_reply('this is not JSON'))
    assert await invoke() == 'this is not JSON'
    assert (await runtime.provider_runtime_status())['status'] == 'unverified'
    body.clear()
    body.update(assistant_reply('{"ok":true}'))
    assert await invoke() == '{"ok":true}'
    assert (await runtime.provider_runtime_status())['status'] == 'healthy'


@pytest.mark.asyncio
async def test_openai_image_requires_real_image_bytes_before_success(monkeypatch):
    await runtime.observe_validated_provider_success(attempt('llm'))
    await runtime.observe_validated_provider_success(attempt('image'))
    raw = b'not-a-real-image'
    original = httpx.AsyncClient
    def respond(_):
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(raw).decode()}]})
    monkeypatch.setattr(image, 'httpx', SimpleNamespace(
        AsyncClient=lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs)))
    monkeypatch.setattr(image, '_persist_image_bytes', AsyncMock(return_value='https://owned.example/generated.png'))
    prompt = ImagePrompt(page=1, positive_prompt='Fictional watercolor scene',
                         negative_prompt='text, letters', seed=1)
    assert (await image._generate_openai(prompt)).endswith('generated.png')
    status = await runtime.provider_runtime_status()
    assert status['status'] == 'unverified'
    assert any(o['kind'] == 'image' and o['reason'] == 'invalid_response' for o in status['observations'])
    raw = image._mock_png_bytes(5)
    assert (await image._generate_openai(prompt)).endswith('generated.png')
    assert (await runtime.provider_runtime_status())['status'] == 'healthy'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429])
async def test_invalid_response_does_not_erase_permanent_failure(status):
    failure = httpx.Response(status, json={'error': {'code': 'insufficient_quota' if status == 429 else 'other'}})
    await runtime.observe_provider_response(attempt('llm'), failure, defer_success=True)
    await runtime.observe_invalid_provider_response(attempt('llm'))
    state = await runtime.provider_runtime_status()
    assert state['status'] == 'unavailable'
    assert any(o['kind'] == 'llm' and o['reason'] in {'credentials_rejected', 'quota_exhausted'}
               for o in state['observations'])


@pytest.mark.asyncio
async def test_simultaneous_invalid_and_permanent_failure_remains_unavailable():
    import asyncio
    await runtime.observe_validated_provider_success(attempt('llm'))
    await asyncio.gather(runtime.observe_invalid_provider_response(attempt('llm')),
                         runtime.observe_provider_response(attempt('llm'), httpx.Response(401, json={}),
                                                           defer_success=True))
    assert (await runtime.provider_runtime_status())['status'] == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['invalid_response', 'credentials_unavailable'])
async def test_invalid_marker_survives_failed_lua_and_validated_success_clears_it(monkeypatch, reason):
    import json
    from src.core.rate_limit import rate_limiter

    class SharedRedis:
        def __init__(self):
            self.values = {}
            self.fail_invalid = True

        async def set(self, key, value, ex):
            self.values[key] = value

        async def get(self, key):
            return self.values.get(key)

        def pipeline(self, *, transaction):
            assert transaction
            return FakePipeline(self)

        async def eval(self, script, count, key, marker, value, _ttl, validated):
            assert script == runtime._ORDERED_OBSERVATION_UPDATE and count == 2
            if json.loads(value)['status'] == 'unverified':
                if self.fail_invalid:
                    raise RuntimeError('synthetic Lua denial')
                self.values[marker] = value
                return 1
            elif validated == '1':
                self.values.pop(marker, None)
            self.values[key] = value
            return 1

    shared = SharedRedis()
    monkeypatch.setattr(settings, 'testing', False)
    monkeypatch.setattr(rate_limiter, 'get_redis', AsyncMock(return_value=shared))
    async def mark_unverified():
        if reason == 'invalid_response':
            await runtime.observe_invalid_provider_response(attempt('llm'))
        else:
            await runtime.observe_provider_credentials_unavailable(
                settings.llm_provider, settings.llm_model, 'llm', settings.llm_api_key,
            )

    await runtime.observe_provider_response(attempt('llm'), httpx.Response(200, json={}))
    await runtime.observe_provider_response(attempt('image'), httpx.Response(200, json={}))
    assert (await runtime.provider_runtime_status())['status'] == 'healthy'
    await mark_unverified()
    runtime._LOCAL_OBSERVATIONS.clear()  # Simulate a different process.
    state = await runtime.provider_runtime_status()
    assert state['status'] == 'unverified'
    assert next(item['reason'] for item in state['observations'] if item['kind'] == 'llm') == reason
    await runtime.observe_validated_provider_success(attempt('llm'))
    runtime._LOCAL_OBSERVATIONS.clear()
    assert (await runtime.provider_runtime_status())['status'] == 'healthy'
    await runtime.observe_provider_response(attempt('llm'), httpx.Response(401, json={}))
    shared.fail_invalid = False
    await mark_unverified()
    runtime._LOCAL_OBSERVATIONS.clear()
    assert (await runtime.provider_runtime_status())['status'] == 'unavailable'
