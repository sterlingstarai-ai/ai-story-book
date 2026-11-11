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
from src.services import image, image_request_budget as request_budget, storage
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
    loaded, sent, consumed, clients = [], [], [], []
    replies = []

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
        return replies.pop(0) if replies else httpx.Response(500, json={})

    def client(**kwargs):
        instance = httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=client))
    monkeypatch.setattr(image, "consume_image_request", lambda: consumed.append(True))
    monkeypatch.setattr(storage, "key_from_public_url", lambda url: url if url in objects else None)
    monkeypatch.setattr(storage, "get_object_bytes", object_bytes)
    monkeypatch.setattr(settings, "image_provider", provider)
    monkeypatch.setattr(settings, "image_model", "gpt-image-2" if provider == "openai" else "gemini-3-pro-image")
    monkeypatch.setattr(settings, "image_api_key", "test-only-not-real")
    monkeypatch.setattr(settings, "openai_image_quality", "medium")
    return SimpleNamespace(
        objects=objects, loaded=loaded, sent=sent, consumed=consumed, clients=clients, replies=replies,
    )


async def observe_request(primary=AVATAR, prompt=None):
    with pytest.raises(StoryBookError) as raised:
        await image.generate_image(prompt or scene_prompt(), reference_image_url=primary)
    assert raised.value.code == ErrorCode.IMAGE_FAILED
    assert "500" in raised.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("has_time", [True, False])
async def test_provider_rate_limit_pauses_same_book_without_spending_requests(wire, monkeypatch, has_time):
    now = 100.0
    waited = []

    async def sleep(delay):
        nonlocal now
        assert len(wire.consumed) == 1
        waited.append(delay)
        now += delay

    monkeypatch.setattr(request_budget, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(request_budget, "asyncio", SimpleNamespace(sleep=sleep))
    wire.replies.append(httpx.Response(429, headers={"Retry-After": "11"}, json={}))
    with request_budget.image_request_budget(3, now + (40 if has_time else 10)):
        with pytest.raises(StoryBookError) as limited:
            await image.generate_image(scene_prompt(), reference_image_url=AVATAR)
        assert limited.value.code == ErrorCode.IMAGE_RATE_LIMIT
        assert limited.value.details["retry_after"] == 11
        if has_time:
            await asyncio.gather(observe_request(), observe_request())
            assert waited == [11]
            assert len(wire.consumed) == 3
        else:
            with pytest.raises(StoryBookError) as exhausted:
                await image.generate_image(scene_prompt(), reference_image_url=AVATAR)
            assert exhausted.value.code == ErrorCode.IMAGE_QUALITY_FAILED
            assert waited == []
            assert len(wire.consumed) == 1


@pytest.mark.asyncio
async def test_provider_quota_exhaustion_bypasses_transient_image_retry(wire):
    from src.services.orchestrator import generate_image_with_retry

    wire.replies.append(httpx.Response(429, headers={"Retry-After": "11"},
                                       json={"error": {"code": "insufficient_quota"}}))
    with request_budget.image_request_budget(3, request_budget.time.monotonic() + 40) as budget:
        with pytest.raises(StoryBookError) as unavailable:
            await generate_image_with_retry(scene_prompt(), "inert-job", 7, reference_image_url=AVATAR)
        assert unavailable.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE
        assert budget.retry_not_before == 0
        assert len(wire.consumed) == 1


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
    assert "Follow the current brief's viewpoint, subject scale and placement independently of the cover" in text
    assert "props into the new scene" not in text
    assert wire.consumed == [True]


@pytest.mark.asyncio
async def test_sole_cover_preserves_cast_without_overriding_the_page_framing(wire):
    prompt = scene_prompt().model_copy(update={
        "positive_prompt": "Low view with the seedling in the foreground and both friends behind it.",
    })
    with image.image_book_reference_scope(COVER):
        await observe_request(primary=COVER, prompt=prompt)
    references, text = wire.sent[0]
    assert references == [wire.objects[COVER][0]]
    assert "preserve each character's own face, hair, proportions, outfit and garment colors" in text
    assert "viewpoint, subject scale and placement from scratch" in text
    assert prompt.positive_prompt in text


@pytest.mark.asyncio
async def test_dual_references_overlap_but_keep_provider_order(wire, monkeypatch):
    cover_ready = asyncio.Event()

    async def read(key):
        if key == AVATAR:
            await cover_ready.wait()
        else:
            assert key == COVER
            cover_ready.set()
        return wire.objects[key]

    monkeypatch.setattr(storage, "get_object_bytes", read)
    with image.image_book_reference_scope(COVER):
        await asyncio.wait_for(observe_request(), timeout=1)
    assert wire.sent[0][0] == [wire.objects[AVATAR][0], wire.objects[COVER][0]]


@pytest.mark.asyncio
async def test_failed_reference_drains_other_read_without_provider_call(wire, monkeypatch):
    cover_started = asyncio.Event()
    avatar_missing = asyncio.Event()
    cover_finished = asyncio.Event()

    async def read(key):
        if key == AVATAR:
            await cover_started.wait()
            avatar_missing.set()
            raise FileNotFoundError("missing test avatar")
        assert key == COVER
        cover_started.set()
        await avatar_missing.wait()
        await asyncio.sleep(0)
        cover_finished.set()
        return wire.objects[key]

    monkeypatch.setattr(storage, "get_object_bytes", read)
    with image.image_book_reference_scope(COVER), pytest.raises(StoryBookError) as raised:
        await asyncio.wait_for(image.generate_image(scene_prompt(), AVATAR), timeout=1)
    assert raised.value.code == ErrorCode.IMAGE_FAILED
    assert cover_finished.is_set()
    assert not wire.consumed and not wire.sent


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
    assert ("IMAGE1 is the generated page" in text) is local
    assert ("IMAGE1 fixes the approved character" in text) is not local
    assert "IMAGE2 is the book cover" in text
    assert CORRECTION_INSTRUCTIONS[issue] in text
    if issue == 'action_mismatch':
        assert 'Replace any contradicted action, actor' in text
        assert 'Preserve its composition' not in text


@pytest.mark.asyncio
async def test_cover_and_cast_notes_can_replace_an_incorrect_prior_scene(wire):
    notes = "CAST LOOKS: Haru = brown bear, yellow hat; Dami = white rabbit, purple scarf"
    narrative = "Dami places the pebble on the ground beside the flowerpot."
    prompt = scene_prompt().model_copy(update={
        "positive_prompt": "Haru drops a pebble inside the flowerpot.",
        "guidance_notes": notes,
    })
    with image.image_book_reference_scope(COVER), image_correction_scope(
        page_text=narrative, issues=["action_mismatch"], source_image_url=PAGE,
    ):
        await observe_request(None, prompt)
    refs, text = wire.sent[0]
    assert refs == [wire.objects[PAGE][0], wire.objects[COVER][0]]
    assert f"CURRENT PAGE NARRATIVE: {narrative}" in text and notes in text
    assert prompt.positive_prompt not in text


@pytest.mark.asyncio
async def test_action_repair_sends_supporting_character_wardrobe_to_image_provider(wire):
    appearance = "Haru = white rabbit, blue vest; Keeper = gray badger, navy cap, orange jacket"
    prior_scene = "Haru already holds the litter grabber in the opening picnic scene."
    prompt = scene_prompt().model_copy(update={
        "positive_prompt": f"ACTION FOCUS: Haru looks at the silver glint.\nCAST DETAILS: {appearance}\n{prior_scene}",
        "guidance_notes": "CAST LOOKS: Haru = white rabbit; Keeper = gray badger",
    })
    with image.image_book_reference_scope(COVER), image_correction_scope(
        page_text="Haru sees a silver glint under the bush while Keeper watches.",
        issues=["action_mismatch"], source_image_url=PAGE, use_prompt_action_focus=True,
    ):
        await observe_request(None, prompt)
    assert wire.loaded == [PAGE, COVER]
    assert len(wire.sent) == 1
    text = wire.sent[0][1]
    assert appearance in text and prior_scene not in text
    assert "navy cap" in text and len(text) <= 5000


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
        page_text="Rain enters the small screened inlet.", issues=["readable_text"],
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
        async with image.book_image_connection_scope():
            with image.image_book_reference_scope(cover):
                await asyncio.gather(observe_request(), observe_request())

    await asyncio.gather(run(COVER), run(OTHER_COVER))
    assert sorted(refs[1] for refs, _ in wire.sent) == sorted([
        wire.objects[COVER][0], wire.objects[OTHER_COVER][0],
    ] * 2)
    assert len(wire.clients) == 2 and all(client.is_closed for client in wire.clients)
    assert wire.consumed == [True] * 4
    assert all(refs[0] == wire.objects[AVATAR][0] for refs, _ in wire.sent)
    await observe_request()
    assert len(wire.clients) == 3 and wire.clients[-1].is_closed
    assert wire.sent[-1][0] == [wire.objects[AVATAR][0]]
    assert "IMAGE2" not in wire.sent[-1][1]


@pytest.mark.asyncio
async def test_text_only_page_batch_downloads_each_own_cover_once(wire):
    async def run(cover):
        async with image.book_image_connection_scope():
            with image.image_book_reference_scope(cover), image.generated_cover_download_scope(cover):
                await asyncio.gather(*(observe_request(primary=cover) for _ in range(6)))

    await asyncio.gather(run(COVER), run(OTHER_COVER))
    assert sorted(wire.loaded) == sorted([COVER, OTHER_COVER])
    assert sorted(refs[0] for refs, _ in wire.sent) == sorted(
        [wire.objects[COVER][0]] * 6 + [wire.objects[OTHER_COVER][0]] * 6
    )
    assert all(len(refs) == 1 for refs, _ in wire.sent)

    replacement = image._mock_png_bytes(404)
    wire.objects[COVER] = (replacement, "image/png")
    with image.image_book_reference_scope(COVER):
        await observe_request(primary=COVER)
    assert wire.loaded[-1] == COVER
    assert wire.sent[-1][0] == [replacement]


@pytest.mark.asyncio
async def test_generated_cover_cache_does_not_retain_failed_download(wire):
    valid = wire.objects[COVER]
    wire.objects[COVER] = None
    with image.generated_cover_download_scope(COVER):
        with image.image_book_reference_scope(COVER), pytest.raises(StoryBookError):
            await image.generate_image(scene_prompt(), reference_image_url=COVER)
        assert wire.sent == [] and wire.consumed == []
        wire.objects[COVER] = valid
        with image.image_book_reference_scope(COVER):
            await observe_request(primary=COVER)
            await observe_request(primary=COVER)

    assert wire.loaded == [COVER, COVER]
    assert all(refs == [valid[0]] for refs, _ in wire.sent)


@pytest.mark.asyncio
async def test_cancelled_book_closes_provider_client(wire):
    entered = asyncio.Event()

    async def run():
        async with image.book_image_connection_scope():
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(run())
    await entered.wait()
    assert len(wire.clients) == 1 and not wire.clients[0].is_closed
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert wire.clients[0].is_closed


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
