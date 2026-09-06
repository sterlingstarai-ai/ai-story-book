"""Serialize at most two owned visual references without network or provider calls."""

import asyncio
import base64
from email import policy
from email.parser import BytesParser
import json
from types import SimpleNamespace

import httpx
import pytest

from src.core.config import settings
from src.core.errors import ErrorCode, StoryBookError
from src.models.dto import ImagePrompt
from src.services import image, storage
from src.services.image_correction import CORRECTION_INSTRUCTIONS, image_correction_scope


AVATAR = "https://owned.invalid/jobs/inert/avatar.png"
COVER = "https://owned.invalid/jobs/inert/cover.png"
PAGE = "https://owned.invalid/jobs/inert/page-7.png"
OTHER_COVER = "https://owned.invalid/jobs/other/cover.png"


def scene_prompt():
    return ImagePrompt(
        page=7, positive_prompt="An illustrated child fills a watering can.",
        negative_prompt="text, letters", seed=7,
    )


@pytest.fixture(params=["openai", "gemini"])
def wire(monkeypatch, request):
    provider = request.param
    objects = {
        url: (image._mock_png_bytes(seed), "image/png")
        for seed, url in enumerate([AVATAR, COVER, PAGE, OTHER_COVER], start=100)
    }
    loaded, sent, consumed = [], [], []

    async def object_bytes(key):
        loaded.append(key)
        await asyncio.sleep(0)
        if objects[key] is None:
            raise FileNotFoundError("inert test fixture")
        return objects[key]

    def respond(request):
        assert request.method == "POST"
        if provider == "openai":
            assert request.url.path == "/v1/images/edits"
            message = BytesParser(policy=policy.default).parsebytes(
                b"MIME-Version: 1.0\r\nContent-Type: "
                + request.headers["content-type"].encode("ascii")
                + b"\r\n\r\n" + request.content
            )
            parts = list(message.iter_parts())
            files = [p for p in parts if p.get_param("name", header="content-disposition") == "image[]"]
            fields = {p.get_param("name", header="content-disposition"): p for p in parts if p not in files}
            assert fields["n"].get_payload(decode=True) == b"1"
            assert fields["quality"].get_payload(decode=True) == b"medium"
            assert fields["model"].get_payload(decode=True) == b"gpt-image-2"
            assert "input_fidelity" not in fields
            assert all(p.get_content_type() == "image/png" for p in files)
            refs = [p.get_payload(decode=True) for p in files]
            text = fields["prompt"].get_payload(decode=True).decode("utf-8")
        else:
            assert request.url.path.endswith(":generateContent")
            body = json.loads(request.content)
            assert body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
            parts = body["contents"][0]["parts"]
            inline = [p["inline_data"] for p in parts if "inline_data" in p]
            assert all(p["mime_type"] == "image/png" for p in inline)
            refs = [base64.b64decode(p["data"]) for p in inline]
            text = "\n".join(p["text"] for p in parts if "text" in p)
        assert 1 <= len(refs) <= 2
        sent.append((refs, text))
        # Observe actual HTTPX serialization and stop before output persistence.
        return httpx.Response(500, json={})

    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=client))
    monkeypatch.setattr(image, "consume_image_request", lambda: consumed.append(True))
    monkeypatch.setattr(storage, "key_from_public_url", lambda url: url if url in objects else None)
    monkeypatch.setattr(storage, "get_object_bytes", object_bytes)
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_model", "gpt-image-2" if provider == "openai" else "gemini-3-pro-image")
    monkeypatch.setattr(settings, "image_api_key", "test-only-not-real")
    monkeypatch.setattr(settings, "openai_image_quality", "medium")
    return SimpleNamespace(objects=objects, loaded=loaded, sent=sent, consumed=consumed)


async def observe_request(primary=AVATAR, prompt=None):
    with pytest.raises(StoryBookError) as raised:
        await image.generate_image(prompt or scene_prompt(), reference_image_url=primary)
    assert raised.value.code == ErrorCode.IMAGE_FAILED
    assert "500" in raised.value.message


@pytest.mark.asyncio
async def test_avatar_then_cover_are_serialized_with_separate_roles(wire):
    with image.image_book_reference_scope(COVER):
        await observe_request()
    assert wire.loaded == [AVATAR, COVER]
    refs, text = wire.sent[0]
    assert refs == [wire.objects[AVATAR][0], wire.objects[COVER][0]]
    assert "IMAGE1 fixes the approved character" in text
    assert "IMAGE2 is the book cover" in text
    assert "Never transfer cover characters, outfits" in text
    assert "Current story, action and cast override cover composition" in text
    assert "props into the new scene" not in text
    assert wire.consumed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("issue", list(CORRECTION_INSTRUCTIONS))
async def test_repair_sends_current_page_or_identity_reference_before_cover(wire, issue):
    with image.image_book_reference_scope(COVER), image_correction_scope(
        page_text="The watering can fills through its top opening.",
        issues=[issue], source_image_url=PAGE,
    ):
        await observe_request()
    local = issue not in {"identity_swap", "duplicate_character"}
    expected_primary = PAGE if local else AVATAR
    assert wire.loaded == [expected_primary, COVER]
    refs, text = wire.sent[0]
    assert refs == [wire.objects[expected_primary][0], wire.objects[COVER][0]]
    assert ("IMAGE1 is the generated page to edit" in text) is local
    assert ("IMAGE1 fixes the approved character" in text) is not local
    assert "IMAGE2 is the book cover" in text
    assert CORRECTION_INSTRUCTIONS[issue] in text


@pytest.mark.asyncio
@pytest.mark.parametrize("primary", [None, COVER])
async def test_cover_only_preserves_current_cast_identity_and_objects_once(wire, primary):
    with image.image_book_reference_scope(COVER):
        await observe_request(primary)
    assert wire.loaded == [COVER]
    refs, text = wire.sent[0]
    assert refs == [wire.objects[COVER][0]]
    assert "The sole reference is the book cover" in text
    assert "preserve each character's own face" in text
    assert "outfit and garment colors" in text
    assert "omit absent cover cast" in text
    assert "recurring object design, material, structure" in text
    assert "Never transfer cover characters" not in text


@pytest.mark.asyncio
async def test_page_equal_to_cover_dedupes_without_changing_local_repair_role(wire):
    with image.image_book_reference_scope(COVER), image_correction_scope(
        page_text="Rain enters the small screened inlet.", issues=["action_mismatch"],
        source_image_url=COVER,
    ):
        await observe_request()
    assert wire.loaded == [COVER]
    assert wire.sent[0][0] == [wire.objects[COVER][0]]
    assert "EDIT THE GENERATED STORYBOOK PAGE" in wire.sent[0][1]
    assert "IMAGE2" not in wire.sent[0][1]


@pytest.mark.asyncio
async def test_portrait_never_inherits_cover_even_if_cover_is_unavailable(wire):
    wire.objects[COVER] = None
    with image.image_book_reference_scope(COVER), image.portrait_conversion_scope():
        await observe_request()
    assert wire.loaded == [AVATAR]
    assert wire.sent[0][0] == [wire.objects[AVATAR][0]]
    assert "initial conversion into a storybook character" in wire.sent[0][1]
    assert "IMAGE2" not in wire.sent[0][1]
    assert "book cover" not in wire.sent[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "empty", "mime"])
async def test_secondary_fetch_failure_precedes_paid_request_and_budget(wire, failure):
    wire.objects[COVER] = {
        "missing": None, "empty": (b"", "image/png"), "mime": (b"inert", "text/plain"),
    }[failure]
    with image.image_book_reference_scope(COVER), pytest.raises(StoryBookError) as raised:
        await image.generate_image(scene_prompt(), AVATAR)
    assert raised.value.code == ErrorCode.IMAGE_FAILED
    assert wire.loaded == [AVATAR, COVER]
    assert wire.sent == [] and wire.consumed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("openai", "dall-e-3"), ("replicate", "sdxl"), ("fal", "flux")])
async def test_unsupported_provider_with_cover_only_fails_before_fetch(monkeypatch, provider, model):
    called = []

    async def no_fetch(*args):
        called.append("fetch")
        raise AssertionError("unsupported references must fail first")

    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_model", model)
    monkeypatch.setattr(image, "_required_reference_image", no_fetch)
    monkeypatch.setattr(image, "consume_image_request", lambda: called.append("consume"))
    with image.image_book_reference_scope(COVER), pytest.raises(StoryBookError) as raised:
        await image.generate_image(scene_prompt())
    assert raised.value.code == ErrorCode.IMAGE_FAILED
    assert called == []


@pytest.mark.asyncio
async def test_concurrent_cover_scopes_do_not_cross_serialized_requests(wire):
    async def run(cover):
        with image.image_book_reference_scope(cover):
            await asyncio.sleep(0)
            await observe_request()

    await asyncio.gather(run(COVER), run(OTHER_COVER))
    assert sorted(refs[1] for refs, _ in wire.sent) == sorted([
        wire.objects[COVER][0], wire.objects[OTHER_COVER][0],
    ])
    assert all(refs[0] == wire.objects[AVATAR][0] for refs, _ in wire.sent)
    await observe_request()
    assert wire.sent[-1][0] == [wire.objects[AVATAR][0]]
    assert "IMAGE2" not in wire.sent[-1][1]


def test_nested_clear_and_error_unwinding_restore_outer_book_scope():
    assert image._book_reference_url.get() is None
    with image.image_book_reference_scope(COVER):
        with image.image_book_reference_scope(None):
            assert image._reference_urls(AVATAR) == [AVATAR]
        with pytest.raises(RuntimeError), image.image_book_reference_scope(OTHER_COVER):
            assert image._reference_urls(AVATAR) == [AVATAR, OTHER_COVER]
            raise RuntimeError("inert")
        assert image._reference_urls(AVATAR) == [AVATAR, COVER]
    assert image._book_reference_url.get() is None


@pytest.mark.parametrize("value", ["", " ", 1, [COVER]])
def test_scope_rejects_invalid_or_multiple_cover_inputs(value):
    with pytest.raises(StoryBookError):
        with image.image_book_reference_scope(value):
            pytest.fail("invalid scope entered")
    assert image._book_reference_url.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("issues", [list(CORRECTION_INSTRUCTIONS), ["action_mismatch"]])
async def test_full_schema_brief_and_bounded_correction_fit_two_reference_wire(wire, issues):
    tail = "The librarian has gray hair in a bun, wire glasses and a long brown skirt."
    original = scene_prompt().model_copy(update={
        "positive_prompt": "A" * (1200 - len(tail)) + tail,
        "negative_prompt": "n" * 600,
    })
    narrative = "The child fills the watering can through its top opening. ".ljust(600, "x")
    assert len(narrative) == 600
    with image.image_book_reference_scope(COVER), image_correction_scope(
        page_text=narrative, issues=issues, source_image_url=PAGE,
    ):
        await observe_request(prompt=original)
    text = wire.sent[0][1]
    assert len(text) <= 5000
    assert original.positive_prompt in text and narrative in text
    assert text.endswith(original.negative_prompt)


@pytest.mark.asyncio
async def test_oversized_wire_is_rejected_before_fetch_or_budget(wire):
    expanded = scene_prompt().model_copy(update={"positive_prompt": "x" * 5000})
    with image.image_book_reference_scope(COVER), pytest.raises(StoryBookError) as raised:
        await image.generate_image(expanded, AVATAR)
    assert raised.value.code == ErrorCode.IMAGE_QUALITY_FAILED
    assert wire.loaded == [] and wire.sent == [] and wire.consumed == []
