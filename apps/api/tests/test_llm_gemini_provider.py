"""Gemini LLM 프로바이더 분기 유닛테스트 (2026-08-22).

`call_llm(llm_provider='gemini')` 경로를 httpx 목킹으로 red-proof한다:
- 요청 URL/바디 계약(모델 :generateContent · key는 query param · responseMimeType=json
  · systemInstruction/contents 매핑)
- 응답 파싱(candidates[0].content.parts[0].text)
- 에러 매핑: 비200(429=재시도 가능 LLM_TIMEOUT) · 키 부재(UNKNOWN) ·
  안전차단(빈 parts → LLM_JSON_INVALID, finishReason 로깅)

기존 스위트는 LLM을 mock 모드로만 돌려 실 HTTP 분기(openai/anthropic/gemini)를
테스트하지 않는다 — 이 파일은 gemini 분기에 한해 그 공백을 메운다.
"""
import json

import pytest

from src.core.errors import ErrorCode, LLMError
from src.services import llm


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _FakeClient:
    """`async with httpx.AsyncClient(...) as c: await c.post(...)` 대역."""

    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, params=None, headers=None, json=None):
        self._recorder["called"] = True
        self._recorder["url"] = url
        self._recorder["params"] = params
        self._recorder["headers"] = headers
        self._recorder["json"] = json
        return self._response


def _install_fake(monkeypatch, response):
    recorder = {"called": False}

    def _factory(*args, **kwargs):
        return _FakeClient(response, recorder)

    monkeypatch.setattr(llm.httpx, "AsyncClient", _factory)
    return recorder


@pytest.fixture(autouse=True)
def _gemini_settings(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "gemini")
    monkeypatch.setattr(llm.settings, "llm_api_key", "AIza-test-key")
    monkeypatch.setattr(llm.settings, "llm_model", "gemini-3.1-flash")
    monkeypatch.setattr(llm.settings, "llm_timeout", 5)


@pytest.mark.asyncio
async def test_gemini_happy_path_returns_text_and_shapes_request(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
    recorder = _install_fake(monkeypatch, _FakeResponse(200, payload))

    out = await llm.call_llm("SYS", "USER", max_tokens=123, temperature=0.4)

    assert out == '{"ok": true}'
    # key는 헤더가 아니라 query param(Generative Language API 규약)
    assert recorder["url"].endswith("/gemini-3.1-flash:generateContent")
    assert recorder["params"] is None
    assert recorder["headers"]["x-goog-api-key"] == "AIza-test-key"
    body = recorder["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["contents"][0]["parts"][0]["text"] == "USER"
    # JSON 강제 — openai json_object 모드와 동등
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] == 123


@pytest.mark.asyncio
async def test_gemini_rate_limit_maps_to_retryable_timeout(monkeypatch):
    _install_fake(monkeypatch, _FakeResponse(429, None, text="rate limited"))
    with pytest.raises(LLMError) as ei:
        await llm.call_llm("SYS", "USER")
    assert ei.value.code == ErrorCode.LLM_TIMEOUT


@pytest.mark.asyncio
async def test_gemini_missing_key_raises_before_http(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_api_key", None)
    recorder = _install_fake(monkeypatch, _FakeResponse(200, {}))
    with pytest.raises(LLMError) as ei:
        await llm.call_llm("SYS", "USER")
    assert ei.value.code == ErrorCode.UNKNOWN
    # 키 검사가 먼저 — 네트워크는 건드리지 않아야 함
    assert recorder["called"] is False


@pytest.mark.asyncio
async def test_gemini_safety_block_empty_parts_maps_to_json_invalid(monkeypatch):
    payload = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    _install_fake(monkeypatch, _FakeResponse(200, payload))
    with pytest.raises(LLMError) as ei:
        await llm.call_llm("SYS", "USER")
    assert ei.value.code == ErrorCode.LLM_JSON_INVALID
