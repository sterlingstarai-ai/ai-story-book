"""Two-request smoke validation through real adapters with deterministic HTTP transport."""

import base64
import importlib.util
from io import BytesIO
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("generation_smoke", ROOT / "scripts/run_ai_generation_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

TEXT_KEY = "synthetic-anthropic-credential-sentinel"
IMAGE_KEY = "AQ.synthetic-google-credential-sentinel"
STORY = {"title": "토끼와 반딧불이", "text": "토끼는 숲에서 길을 잃은 반딧불이를 만났어요. 토끼가 집까지 데려다주자 반딧불이는 고맙다고 빛났어요."}
VALUES = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-sonnet-5", "LLM_API_KEY": TEXT_KEY,
          "IMAGE_PROVIDER": "gemini", "IMAGE_MODEL": "gemini-3.1-flash-image", "IMAGE_API_KEY": IMAGE_KEY}


def image_response(data=None, size=(96, 128)):
    if data is None:
        buffer = BytesIO()
        Image.new("RGB", size, "blue").save(buffer, format="PNG")
        data = buffer.getvalue()
    return httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "image/png", "data": base64.b64encode(data).decode(),
        }}]}}], "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 100, "totalTokenCount": 140},
    })


def no_secret_artifacts(output):
    for path in output.glob("*.json"):
        content = path.read_text()
        assert TEXT_KEY not in content
        assert IMAGE_KEY not in content


def test_no_live_flag_never_loads_environment_or_calls_network(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Live flag is required")
    monkeypatch.setattr(smoke, "dotenv_values", forbidden)
    monkeypatch.setattr(smoke, "run_smoke", forbidden)
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["generation_requests"] == 0


@pytest.mark.asyncio
async def test_real_adapters_use_two_requests_and_local_validated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.scheme == "https" and request.url.query == b""
        body = json.loads(request.content)
        if request.url.host == "api.anthropic.com":
            assert body["max_tokens"] == 384
            assert body["thinking"] == {"type": "disabled"}
            assert body["system"] == smoke.TEXT_SYSTEM
            assert request.headers["x-api-key"] == TEXT_KEY
            return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(STORY)}],
                                           "usage": {"input_tokens": 80, "output_tokens": 90,
                                                     "untrusted": TEXT_KEY}})
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == IMAGE_KEY
        text = body["contents"][0]["parts"][0]["text"]
        assert text.startswith(smoke.IMAGE_PROMPT)
        assert "Exclude these elements: No people or personal data" in text
        return image_response()
    output = tmp_path / "run"
    result = await smoke.run_smoke(VALUES, output, transport_factory=lambda: httpx.MockTransport(handler))
    assert len(requests) == 2
    assert result["status"] == "PASSED"
    assert result["components"]["llm"]["requests"] == result["components"]["image"]["requests"] == 1
    assert result["components"]["llm"]["token_usage"] == {"input_tokens": 80, "output_tokens": 90}
    assert result["components"]["image"]["artifact"]["width"] == 96
    assert result["storage"] == "local_only" and not result["pipeline_verified"] and not result["s3_verified"]
    assert json.loads((output / "story.json").read_text()) == STORY
    with Image.open(output / "rabbit.png") as decoded:
        decoded.verify()
    no_secret_artifacts(output)


@pytest.mark.asyncio
async def test_image_only_makes_no_text_request(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        return image_response()
    output = tmp_path / "image-only"
    result = await smoke.run_smoke(VALUES, output, component="image",
                                   transport_factory=lambda: httpx.MockTransport(handler))
    assert len(requests) == 1
    assert result["status"] == "PASSED"
    assert result["request_counts"] == {"llm": 0, "image": 1}
    assert not (output / "story.json").exists()
    assert result["components"]["image"]["artifact"]["requested_aspect_ratio"] == "3:4"
    assert result["components"]["image"]["artifact"]["actual_aspect_ratio"] == "96:128"


@pytest.mark.asyncio
async def test_image_aspect_ratio_mismatch_fails_without_saving_image(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", tmp_path)
    output = tmp_path / "wrong-ratio"
    result = await smoke.run_smoke(VALUES, output, component="image", aspect_ratio="3:4",
                                   transport_factory=lambda: httpx.MockTransport(lambda request: image_response(size=(128, 64))))
    assert result["status"] == "FAILED"
    assert result["components"]["image"]["status"] == "IMAGE_ASPECT_RATIO_MISMATCH"
    assert result["components"]["image"]["image_validation"]["actual_aspect_ratio"] == "128:64"
    assert result["request_counts"] == {"llm": 0, "image": 1}
    assert not (output / "rabbit.png").exists()


@pytest.mark.asyncio
async def test_provider_failure_not_retried_and_errors_do_not_leak(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": TEXT_KEY + IMAGE_KEY}})
    output = tmp_path / "failed"
    result = await smoke.run_smoke(VALUES, output, transport_factory=lambda: httpx.MockTransport(handler))
    assert len(requests) == 2
    assert result["status"] == "FAILED"
    assert all(v["requests"] == 1 and v["http_status"] == 429 for v in result["components"].values())
    assert sorted(p.name for p in output.iterdir()) == ["result.json"]
    no_secret_artifacts(output)


@pytest.mark.asyncio
async def test_invalid_or_secret_outputs_are_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", tmp_path)
    def handler(request):
        if request.url.host == "api.anthropic.com":
            return httpx.Response(200, json={"content": [{"type": "text", "text": TEXT_KEY}]})
        return image_response(b"not-an-image-" + IMAGE_KEY.encode())
    output = tmp_path / "invalid"
    result = await smoke.run_smoke(VALUES, output, transport_factory=lambda: httpx.MockTransport(handler))
    assert result["status"] == "FAILED"
    assert result["components"]["llm"]["status"] == "INVALID_TEXT_OUTPUT"
    assert result["components"]["image"]["status"] == "INVALID_IMAGE_OUTPUT"
    assert sorted(p.name for p in output.iterdir()) == ["result.json"]
    no_secret_artifacts(output)


@pytest.mark.asyncio
async def test_transport_guard_blocks_second_request_and_wrong_host():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})
    budget = smoke.RequestBudget(smoke.runtime_config(VALUES), lambda: httpx.MockTransport(handler))
    async with budget.client(timeout=1) as client:
        await client.post("https://api.anthropic.com/v1/messages", headers={}, json={"max_tokens": 384})
        with pytest.raises(smoke.SmokeError, match="REQUEST_LIMIT_OR_HOST_BLOCKED"):
            await client.post("https://api.anthropic.com/v1/messages", headers={}, json={"max_tokens": 384})
        with pytest.raises(smoke.SmokeError, match="REQUEST_LIMIT_OR_HOST_BLOCKED"):
            await client.post("https://unrelated.invalid", headers={}, json={"max_tokens": 384})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_output_outside_acceptance_rejected_before_request(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", tmp_path / "acceptance")
    with pytest.raises(smoke.SmokeError, match="OUTPUT_MUST_BE_IN_IGNORED_ACCEPTANCE_DIRECTORY"):
        await smoke.run_smoke(VALUES, tmp_path / "outside")
    assert not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_output_symlink_escape_rejected_before_request(tmp_path, monkeypatch):
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (acceptance / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(smoke, "ACCEPTANCE_ROOT", acceptance)
    with pytest.raises(smoke.SmokeError, match="OUTPUT_MUST_BE_IN_IGNORED_ACCEPTANCE_DIRECTORY"):
        await smoke.run_smoke(VALUES, acceptance / "link" / "run")
    assert list(outside.iterdir()) == []
