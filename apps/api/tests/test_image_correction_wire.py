"""Real adapter serialization must send the selected owned image bytes, with no network."""

import base64
from email import policy
from email.parser import BytesParser
import json
from types import SimpleNamespace

import httpx
import pytest

from src.core.config import settings
from src.core.errors import StoryBookError
from src.models.dto import ImagePrompt
from src.services import image, storage
from src.services.image_correction import CORRECTION_INSTRUCTIONS, image_correction_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("issue", list(CORRECTION_INSTRUCTIONS))
async def test_real_reference_payload_uses_page_for_local_defects_and_avatar_for_identity(
    monkeypatch, provider, issue,
):
    page_url = "https://owned.invalid/jobs/inert/page-7.png"
    avatar_url = "https://owned.invalid/jobs/inert/approved-avatar.png"
    page_bytes, avatar_bytes = image._mock_png_bytes(123), image._mock_png_bytes(456)
    assert page_bytes != avatar_bytes
    objects = {"page-7": page_bytes, "approved-avatar": avatar_bytes}
    keys = {page_url: "page-7", avatar_url: "approved-avatar"}
    loaded = []
    sent = []

    async def object_bytes(key):
        loaded.append(key)
        return objects[key], "image/png"

    def respond(request):
        assert request.method == "POST"
        if provider == "openai":
            assert request.url.path == "/v1/images/edits"
            message = BytesParser(policy=policy.default).parsebytes(
                b"MIME-Version: 1.0\r\nContent-Type: "
                + request.headers["content-type"].encode("ascii")
                + b"\r\n\r\n" + request.content
            )
            fields = {part.get_param("name", header="content-disposition"): part
                      for part in message.iter_parts()}
            assert fields["image[]"].get_content_type() == "image/png"
            assert fields["n"].get_payload(decode=True) == b"1"
            assert fields["quality"].get_payload(decode=True) == b"medium"
            sent.append((fields["image[]"].get_payload(decode=True),
                         fields["prompt"].get_payload(decode=True).decode("utf-8")))
        else:
            assert request.url.path.endswith(":generateContent")
            parts = json.loads(request.content)["contents"][0]["parts"]
            references = [part["inline_data"] for part in parts if "inline_data" in part]
            assert len(references) == 1 and references[0]["mime_type"] == "image/png"
            sent.append((base64.b64decode(references[0]["data"]),
                         "\n".join(part["text"] for part in parts if "text" in part)))
        # Stop after observing serialized input. No generated output/storage or paid call.
        return httpx.Response(500, json={})

    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=client))
    monkeypatch.setattr(storage, "key_from_public_url", keys.get)
    monkeypatch.setattr(storage, "get_object_bytes", object_bytes)
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_model", "gpt-image-2" if provider == "openai" else "gemini-3-pro-image")
    monkeypatch.setattr(settings, "image_api_key", "test-only-not-real")
    monkeypatch.setattr(settings, "openai_image_quality", "medium")
    prompt = ImagePrompt(page=7, positive_prompt="An illustrated garden scene.", negative_prompt="text, letters", seed=7)
    with image_correction_scope(
        page_text="The watering can fills through its top opening.",
        issues=[issue], source_image_url=page_url,
    ):
        with pytest.raises(StoryBookError):
            await image.generate_image(prompt, reference_image_url=avatar_url)
    with pytest.raises(StoryBookError):
        await image.generate_image(prompt, reference_image_url=avatar_url)

    local = issue not in {"identity_swap", "duplicate_character"}
    assert loaded == ["page-7" if local else "approved-avatar", "approved-avatar"]
    assert sent[0][0] == (page_bytes if local else avatar_bytes)
    assert ("EDIT THE GENERATED STORYBOOK PAGE" in sent[0][1]) is local
    assert "CORRECTION REQUIREMENTS" in sent[0][1]
    assert sent[1][0] == avatar_bytes
    assert "EDIT THE GENERATED STORYBOOK PAGE" not in sent[1][1]
    assert "CORRECTION REQUIREMENTS" not in sent[1][1]
