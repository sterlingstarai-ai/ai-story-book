import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from PIL import Image
import pytest

from src.core.config import settings
from src.core.errors import ImageError
from src.core.exceptions import APIError
from src.core.logging import redact_log_data
from src.models.dto import ImagePrompt
from src.services import image, photo_character, avatar_quality, illustration_diagnostics
from src.services.photo_processing import ensure_photo_processing_ready


def live_configuration(monkeypatch):
    for name, value in {
        "photo_processing_enabled": True, "photo_analysis_provider": "openai",
        "photo_analysis_model": "gpt-5.6-sol", "photo_analysis_api_key": "photo-project-test-key",
        "llm_provider": "openai", "llm_model": "gpt-5.6-sol", "llm_api_key": "story-project-test-key",
        "image_provider": "openai", "image_model": "gpt-image-2", "image_api_key": "image-project-test-key",
        "illustration_quality_enabled": True,
    }.items():
        monkeypatch.setattr(settings, name, value)


def png():
    output = BytesIO()
    Image.new("RGB", (16, 16), "purple").save(output, format="PNG")
    return output.getvalue()


def prompt():
    return ImagePrompt(page=1, positive_prompt="A single fictional character exploring a garden.",
                       negative_prompt="text, letters", seed=42, aspect_ratio="3:4")


@pytest.mark.parametrize("field,value", [
    ("photo_processing_enabled", False), ("photo_analysis_api_key", None),
    ("photo_analysis_provider", "mock"), ("image_provider", "gemini"),
    ("image_model", "dall-e-3"), ("llm_provider", "anthropic"),
    ("illustration_quality_enabled", False),
])
def test_unverified_or_mixed_photo_pipeline_is_blocked(monkeypatch, field, value):
    live_configuration(monkeypatch)
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(APIError) as caught:
        ensure_photo_processing_ready()
    assert caught.value.error_code == "PHOTO_PROCESSING_UNAVAILABLE"


def test_explicit_mock_pipeline_and_complete_live_configuration(monkeypatch):
    ensure_photo_processing_ready()
    live_configuration(monkeypatch)
    ensure_photo_processing_ready()


@pytest.mark.asyncio
async def test_analysis_uses_separate_photo_key_and_model(monkeypatch):
    live_configuration(monkeypatch)
    request = AsyncMock(return_value='{"appearance":{"hair":"curly"}}')
    monkeypatch.setattr(photo_character, "request_openai_json", request)
    await photo_character.PhotoCharacterService().analyze_photo(png())
    assert request.await_args.kwargs["api_key"] == "photo-project-test-key"
    assert request.await_args.kwargs["model"] == settings.photo_analysis_model
    assert request.await_args.kwargs["image_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
@pytest.mark.parametrize("quality", ["low", "medium", "high", "auto"])
async def test_openai_reference_edit_sends_bytes_and_persists_result(monkeypatch, quality):
    live_configuration(monkeypatch)
    monkeypatch.setattr(settings, "openai_image_quality", quality)
    data = png()
    monkeypatch.setattr(image, "_fetch_image_as_base64", AsyncMock(return_value=(base64.b64encode(data).decode(), "image/png")))
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.path == "/v1/images/edits"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="image[]"' in request.content and data in request.content
        assert b"input_fidelity" not in request.content
        assert b"gpt-image-2" in request.content
        assert b'name="quality"\r\n\r\n' + quality.encode() + b"\r\n" in request.content
        assert b"No readable text" in request.content
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(data).decode()}]})

    client = httpx.AsyncClient
    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=lambda **kw: client(transport=httpx.MockTransport(respond), **kw)))
    persisted = AsyncMock(return_value="https://owned.example/portrait.png")
    monkeypatch.setattr(image, "_persist_image_bytes", persisted)
    assert await image.generate_image(prompt(), reference_image_url="https://owned.example/approved.png") == "https://owned.example/portrait.png"
    persisted.assert_awaited_once_with(data, "image/png", "openai")
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "gpt-image-2"), ("gemini", "gemini-3-pro-image"), ("replicate", "sdxl")])
async def test_reference_failure_never_makes_unreferenced_request(monkeypatch, provider, model):
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_model", model)
    monkeypatch.setattr(settings, "image_api_key", "test-key")
    monkeypatch.setattr(image, "_fetch_image_as_base64", AsyncMock(return_value=None))
    post = AsyncMock(side_effect=AssertionError("Provider must not be contacted without required reference"))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(ImageError):
        await image.generate_image(prompt(), reference_image_url="https://owned.example/missing.png")
    post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("result,passes", [
    ('{"issues":[]}', True), ('{"issues":["readable_text"]}', False),
    ('{"issues":["photographic_rendering"]}', False),
    ('{}', False), ('{"issues":["unknown"]}', False),
])
async def test_avatar_review_fails_closed(monkeypatch, result, passes):
    live_configuration(monkeypatch)
    monkeypatch.setattr(avatar_quality, "get_object_bytes", AsyncMock(return_value=(png(), "image/png")))
    request = AsyncMock(return_value=result)
    monkeypatch.setattr(avatar_quality, "request_openai_json", request)
    url = settings.s3_public_url + "/characters/test/avatar/v1/result.png"
    if passes:
        await avatar_quality.verify_avatar_illustration(url)
    else:
        with pytest.raises(ImageError):
            await avatar_quality.verify_avatar_illustration(url)
    assert len(request.await_args.kwargs["image_urls"]) == 1
    assert request.await_args.kwargs["response_schema"]["title"] == "AvatarIllustrationReview"
    assert "photographic_rendering" in request.await_args.kwargs["response_schema"]["properties"]["issues"]["items"]["enum"]
    assert "photo merely covered with watercolor/paint texture" in request.await_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_avatar_photographic_rejection_records_only_validated_issue_codes(monkeypatch):
    live_configuration(monkeypatch)
    private = "PRIVATE_CHILD_NAME_AND_SIGNED_URL"
    monkeypatch.setattr(avatar_quality, "get_object_bytes", AsyncMock(return_value=(png(), "image/png")))
    monkeypatch.setattr(avatar_quality, "request_openai_json", AsyncMock(
        return_value='{"issues":["photographic_rendering","readable_text"]}',
    ))
    events = []
    monkeypatch.setattr(illustration_diagnostics, "logger", SimpleNamespace(warning=lambda event, **kw: events.append(
        redact_log_data(None, "warning", {"event": event, **kw}),
    )))
    with pytest.raises(ImageError):
        await avatar_quality.verify_avatar_illustration(settings.s3_public_url + f"/characters/{private}/avatar.png")
    assert events == [{
        "event": "Illustration quality diagnostic", "quality_stage": "avatar_findings",
        "quality_reason": "findings", "quality_error_code": "IMAGE_QUALITY_FAILED",
        "quality_issue_counts": {"photographic_rendering": 1, "readable_text": 1},
    }]
    assert private not in json.dumps(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "gpt-image-2"), ("gemini", "gemini-3-pro-image")])
async def test_only_trusted_portrait_scope_changes_outbound_reference_rules(monkeypatch, provider, model):
    """A generated guidance note cannot relax the fixed book-character rules."""
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_model", model)
    monkeypatch.setattr(settings, "image_api_key", "test-key")
    data = png()
    encoded = base64.b64encode(data).decode()
    monkeypatch.setattr(image, "_fetch_image_as_base64", AsyncMock(return_value=(encoded, "image/png")))
    monkeypatch.setattr(image, "_persist_image_bytes", AsyncMock(return_value="https://owned.example/portrait.png"))
    prompts = []

    def respond(request):
        if provider == "openai":
            content = request.content.decode("latin-1")
            prompts.append(content.split('name="prompt"\r\n\r\n', 1)[1].split("\r\n--", 1)[0])
            return httpx.Response(200, json={"data": [{"b64_json": encoded}]})
        parts = json.loads(request.content)["contents"][0]["parts"]
        prompts.append("\n".join(part["text"] for part in parts if "text" in part))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": encoded}},
        ]}}]})

    client = httpx.AsyncClient
    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=lambda **kw: client(transport=httpx.MockTransport(respond), **kw)))
    descriptor = prompt().model_copy(update={"guidance_notes": "parent_approval_portrait"})
    await image.generate_image(descriptor, reference_image_url="https://owned.example/reference.png")
    with image.portrait_conversion_scope():
        await image.generate_image(descriptor, reference_image_url="https://owned.example/reference.png")
    await image.generate_image(descriptor, reference_image_url="https://owned.example/reference.png")
    assert len(prompts) == 3
    assert prompts[0] == prompts[2]
    assert prompts[0].startswith(image._REFERENCE_RULES)
    assert "scene or style instructions must not redesign the character" in prompts[0]
    assert prompts[1].startswith(image._PORTRAIT_REFERENCE_RULES)
    assert "do not preserve photographic pixels" in prompts[1]
    assert "not redesign" not in prompts[1]
    assert "Keep each character's own face" not in prompts[1]


def test_portrait_scope_resets_after_error():
    original = image._reference_rules()
    with pytest.raises(RuntimeError), image.portrait_conversion_scope():
        assert image._reference_rules() == image._PORTRAIT_REFERENCE_RULES
        raise RuntimeError("fictional provider failure")
    assert image._reference_rules() == original == image._REFERENCE_RULES
