"""Credential checker boundaries, with no external network or real credentials."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("ai_connection", ROOT / "scripts/check_ai_connection.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

KEY = "credential-sentinel-do-not-print"


def config(provider="anthropic", role="llm", model="claude-sonnet-5"):
    return {f"{role.upper()}_PROVIDER": provider, f"{role.upper()}_API_KEY": KEY,
            f"{role.upper()}_MODEL": model}


def run_check(handler, values=None, *, role="llm", **kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        result = checker.check_component(values or config(), role, client=client, **kwargs)
    assert KEY not in json.dumps(result)
    return result


def test_default_never_contacts_provider():
    def forbidden(request):
        pytest.fail("A live request requires --live")
    result = run_check(forbidden)
    assert result["status"] == "CONFIGURED_NOT_VERIFIED"
    assert result["metadata_verified"] is False


@pytest.mark.parametrize("provider,role,model,payload,host,key_header", [
    ("anthropic", "llm", "claude-sonnet-5", {"id": "claude-sonnet-5"},
     "api.anthropic.com", "x-api-key"),
    ("gemini", "image", "gemini-3.1-flash-image",
     {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
     "generativelanguage.googleapis.com", "x-goog-api-key"),
])
def test_metadata_get_uses_fixed_host_and_header_only(provider, role, model, payload, host, key_header):
    def handler(request):
        assert request.method == "GET"
        assert request.url.host == host
        assert request.url.scheme == "https"
        assert request.url.path.endswith("/" + model)
        assert request.url.query == b""
        assert request.content == b""
        assert request.headers[key_header] == KEY
        assert KEY not in str(request.url)
        if provider == "anthropic":
            assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json=payload)
    result = run_check(handler, config(provider, role, model), role=role, live=True)
    assert result["status"] == "METADATA_VERIFIED"
    assert result["resolved_model"] == model


@pytest.mark.parametrize("status,expected", [
    (401, "AUTHENTICATION_FAILED"), (403, "PERMISSION_DENIED"), (404, "MODEL_UNAVAILABLE"),
    (429, "RATE_LIMITED"), (503, "PROVIDER_UNAVAILABLE"), (302, "REDIRECT_REFUSED"),
])
def test_errors_and_redirects_are_not_followed_or_echoed(status, expected):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://unrelated.invalid/?key=" + KEY},
                              json={"error": {"message": KEY}})
    result = run_check(handler, live=True)
    assert len(requests) == 1
    assert result["status"] == expected


def test_network_exception_does_not_echo_key():
    def handler(request):
        raise httpx.ConnectError(KEY, request=request)
    assert run_check(handler, live=True)["status"] == "NETWORK_ERROR"


def test_model_discovery_filters_free_text_secrets_and_reports_incomplete_page():
    def handler(request):
        assert request.url.params["pageSize"] == "1000"
        return httpx.Response(200, json={"models": [
            {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-" + KEY, "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-invalid\n" + KEY, "supportedGenerationMethods": ["generateContent"]},
        ], "nextPageToken": KEY})
    result = run_check(handler, config("gemini", "image", ""), role="image", live=True, list_models=True)
    assert result["available_models"] == ["gemini-3.1-flash-image"]
    assert result["list_complete"] is False


def test_gemini_metadata_requires_generate_content():
    def handler(request):
        return httpx.Response(200, json={"name": "models/gemini-image", "supportedGenerationMethods": []})
    result = run_check(handler, config("gemini", "image", "gemini-image"), role="image", live=True)
    assert result["status"] == "MODEL_METADATA_UNSUPPORTED"
    assert result["metadata_verified"] is False


@pytest.mark.parametrize("payload", [[], {"id": KEY}, {"id": "claude-" + KEY}, {"unexpected": KEY}])
def test_malformed_success_cannot_verify_model(payload):
    result = run_check(lambda request: httpx.Response(200, json=payload), live=True)
    assert result["metadata_verified"] is False


def test_oversized_body_rejected(monkeypatch):
    monkeypatch.setattr(checker, "MAX_METADATA_BYTES", 10)
    result = run_check(lambda request: httpx.Response(200, content=b"x" * 11), live=True)
    assert result["status"] == "INVALID_METADATA"


def test_cli_env_file_is_data_and_report_does_not_claim_generation(tmp_path, monkeypatch, capsys):
    env_path = tmp_path / "ai.env"
    env_path.write_text("LLM_PROVIDER=anthropic\nLLM_MODEL=claude-sonnet-5\nLLM_API_KEY=" + KEY + "\n"
                        "UNUSED=$(touch /must-not-run)\n", encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    code = checker.main(["--env-file", str(env_path), "--component", "llm"])
    output = capsys.readouterr().out
    report = json.loads(output)
    assert code == 0
    assert KEY not in output
    assert report["components"][0]["provider"] == "anthropic"
    assert report["generation_requests"] == 0
    assert report["generation_verified"] is False
    assert report["billing_and_quota_verified"] is False
    assert report["launch_ready"] is False
