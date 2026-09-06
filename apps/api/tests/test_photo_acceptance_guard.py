"""Synthetic-only checks for the opt-in paid-photo execution guard."""

import base64
from concurrent.futures import ProcessPoolExecutor
import importlib.util
from io import BytesIO
import json
import multiprocessing
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest


SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
spec = importlib.util.spec_from_file_location("photo_guard", SCRIPTS / "photo_acceptance_guard.py")
guard = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SCRIPTS))
try:
    spec.loader.exec_module(guard)
finally:
    sys.path.remove(str(SCRIPTS))


def _png():
    stream = BytesIO()
    Image.new("RGB", (24, 32), "blue").save(stream, format="PNG")
    return stream.getvalue()


def _responses(model="gpt-5.6-sol"):
    return {"json": {"model": model, "max_output_tokens": 16000, "store": False,
                     "input": "Synthetic story, no real person."}}


def _image():
    return {"data": {"model": "gpt-image-2", "prompt": "A fictional blue bird.",
                     "n": "1", "size": "768x1024", "quality": "medium"},
            "files": {"image[]": ("synthetic.png", _png(), "image/png")}}


@pytest.fixture
def config(tmp_path, monkeypatch):
    policy = {"llm_model": "gpt-5.6-sol", "photo_analysis_model": "gpt-6-astra",
              "image_model": "gpt-image-2", "max_budget_usd": 10,
              "llm_request_reservation_usd": 0.1, "image_request_reservation_usd": 0.2,
              "private_evidence": "private-policy-must-not-enter-journal"}
    policy_path, journal = tmp_path / "policy.json", tmp_path / "usage.jsonl"
    policy_path.write_text(json.dumps(policy))
    policy_path.chmod(0o600)
    journal.touch(mode=0o600)
    values = {
        "LIVE_PHOTO_POLICY_FILE": str(policy_path), "LIVE_ACCEPTANCE_JOURNAL": str(journal),
        "LLM_PROVIDER": "openai", "LLM_MODEL": policy["llm_model"],
        "PHOTO_ANALYSIS_PROVIDER": "openai", "PHOTO_ANALYSIS_MODEL": policy["photo_analysis_model"],
        "IMAGE_PROVIDER": "openai", "IMAGE_MODEL": policy["image_model"],
        "OPENAI_IMAGE_QUALITY": "medium",
        "PHOTO_PROCESSING_ENABLED": "true", "ILLUSTRATION_QUALITY_ENABLED": "true",
        "LIVE_ACCEPTANCE_PAGE_COUNT": "12",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(httpx.AsyncClient, "post", httpx.AsyncClient.post)
    monkeypatch.setattr(httpx.Client, "post", httpx.Client.post)
    return SimpleNamespace(policy=policy, policy_path=policy_path, journal=journal)


@pytest.fixture
def installed(config):
    guard.install()
    return config


@pytest.mark.parametrize("value", [True, False, None, "0.1", 0, -1, 10.01,
                                        float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", guard.MONEY_FIELDS)
def test_non_numeric_unbounded_or_nonpositive_policy_reservations_rejected(config, field, value):
    config.policy[field] = value
    with pytest.raises(RuntimeError, match="LIVE_PHOTO_INVALID_MONEY"):
        guard.validate_policy(config.policy)


def test_policy_model_allowlist_exact_matching_and_reservation_within_budget(config):
    for field in guard.MODEL_FIELDS:
        changed = dict(config.policy, **{field: config.policy[field] + "-other"})
        with pytest.raises(RuntimeError, match="MODEL_SELECTION"):
            guard.validate_policy(changed)
    with pytest.raises(RuntimeError, match="INVALID_MONEY"):
        guard.validate_policy(dict(config.policy, max_budget_usd=0.15))
    assert "private_evidence" not in guard.validate_policy(config.policy)


@pytest.mark.parametrize("name,value", [
    ("LLM_PROVIDER", "anthropic"), ("LLM_MODEL", "gpt-6-astra"),
    ("PHOTO_ANALYSIS_PROVIDER", "mock"), ("PHOTO_ANALYSIS_MODEL", "gpt-5.6-sol"),
    ("IMAGE_PROVIDER", "gemini"), ("IMAGE_MODEL", "gpt-image-2-other"),
    ("OPENAI_IMAGE_QUALITY", "high"),
    ("PHOTO_PROCESSING_ENABLED", "false"), ("ILLUSTRATION_QUALITY_ENABLED", "false"),
    ("LIVE_ACCEPTANCE_PAGE_COUNT", "8"),
])
def test_install_fails_before_client_patch_when_runtime_disagrees(config, monkeypatch, name, value):
    original_async, original_sync = httpx.AsyncClient.post, httpx.Client.post
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="CONFIGURATION_MISMATCH"):
        guard.install()
    assert httpx.AsyncClient.post is original_async and httpx.Client.post is original_sync
    assert config.journal.read_text() == ""


def test_private_policy_and_journal_required_and_duplicate_json_rejected(config):
    config.policy_path.chmod(0o644)
    with pytest.raises(RuntimeError, match="PRIVATE_FILE"):
        guard.install()
    config.policy_path.chmod(0o600)
    config.journal.chmod(0o644)
    with pytest.raises(RuntimeError, match="PRIVATE_FILE"):
        guard.install()
    config.journal.chmod(0o600)
    config.policy_path.write_text('{"max_budget_usd":10,"max_budget_usd":1}')
    with pytest.raises(RuntimeError, match="INVALID_JSON"):
        guard.install()


@pytest.mark.asyncio
async def test_failed_requests_share_global_analysis_writing_review_and_image_limits(installed):
    calls = []

    def reject(request):
        events = list(map(json.loads, installed.journal.read_text().splitlines()))
        assert events[-1]["kind"] == "request"  # Reservation exists before transport.
        calls.append(request)
        return httpx.Response(429, json={"error": "private-provider-body"})

    for number in range(16):
        # Both configured text models consume the same global 16-request pool.
        model = "gpt-6-astra" if number % 2 else "gpt-5.6-sol"
        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            assert (await client.post(guard.RESPONSES_URL, **_responses(model))).status_code == 429
    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        with pytest.raises(RuntimeError, match="REQUEST_LIMIT"):
            client.post(guard.RESPONSES_URL, **_responses())
        for _ in range(17):
            assert client.post(guard.IMAGE_URL, **_image()).status_code == 429
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        with pytest.raises(RuntimeError, match="REQUEST_LIMIT"):
            await client.post(guard.IMAGE_URL, **_image())
    assert len(calls) == 33
    raw = installed.journal.read_text()
    assert "private-provider-body" not in raw
    assert "private-policy" not in raw
    requests = [e for e in map(json.loads, raw.splitlines()) if e["kind"] == "request"]
    assert requests[-1]["reserved_total_usd"] == 5.0


def test_photo_request_pool_includes_portrait_and_full_book_repair_allowance():
    from src.services.illustration_policy import book_image_request_limit

    assert guard.REQUEST_LIMITS["image"] == 1 + book_image_request_limit(12) == 17


@pytest.mark.asyncio
async def test_usage_dimensions_and_transport_errors_never_record_private_content(installed):
    sentinel = "private-child-prompt-secret-provider-error"
    encoded = base64.b64encode(_png()).decode()

    def success(_request):
        return httpx.Response(200, json={"data": [{"b64_json": encoded, "revised_prompt": sentinel}],
            "usage": {"input_tokens": 12, "output_tokens": True, "total_tokens": -1,
                      "input_tokens_details": {"cached_tokens": 3, "text_tokens": 4, "private": sentinel}},
            "private": sentinel})

    payload = _image()
    payload["data"]["prompt"] = sentinel
    async with httpx.AsyncClient(transport=httpx.MockTransport(success)) as client:
        await client.post(guard.IMAGE_URL, headers={"Authorization": sentinel}, **payload)
    response = json.loads(installed.journal.read_text().splitlines()[1])
    assert response["usage"] == {"input_tokens": 12, "input_tokens_details": {"cached_tokens": 3, "text_tokens": 4}}
    assert response["image_dimensions"] == [{"width": 24, "height": 32}]
    assert response["image_dimensions_complete"] is True
    assert response["estimated_usage_usd"] is None  # A boolean is not output-token usage.

    def timeout(request):
        raise httpx.ReadTimeout(sentinel, request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(httpx.ReadTimeout):
            client.post(guard.RESPONSES_URL, **_responses())
    raw = installed.journal.read_text()
    assert sentinel not in raw and encoded not in raw and "https://" not in raw
    events = list(map(json.loads, raw.splitlines()))
    assert events[-1]["failed"] is True
    assert sum(e["kind"] == "request" for e in events) == 2


@pytest.mark.parametrize("url,changes,options", [
    ("https://untrusted.example/responses", {}, {}),
    (guard.RESPONSES_URL + "?secret=private", {}, {}),
    ("https://api.openai.com/v1/chat/completions", {}, {}),
    (guard.RESPONSES_URL, {"model": "gpt-5.6"}, {}),
    (guard.RESPONSES_URL, {"max_output_tokens": 16001}, {}),
    (guard.RESPONSES_URL, {"max_output_tokens": True}, {}),
    (guard.RESPONSES_URL, {"store": True}, {}),
    (guard.RESPONSES_URL, {"background": True}, {}),
    (guard.RESPONSES_URL, {"stream": True}, {}),
    (guard.RESPONSES_URL, {"tools": [{"type": "web_search"}]}, {}),
    (guard.RESPONSES_URL, {"service_tier": "priority"}, {}),
    (guard.RESPONSES_URL, {}, {"params": {"private": "secret"}}),
    (guard.RESPONSES_URL, {}, {"follow_redirects": True}),
])
def test_bad_response_options_rejected_before_reservation_or_network(installed, url, changes, options):
    def forbidden(_request):
        pytest.fail("Rejected requests cannot reach the transport")
    request = _responses()
    request["json"].update(changes)
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(RuntimeError, match="LIVE_PHOTO"):
            client.post(url, **request, **options)
    assert installed.journal.read_text() == ""


@pytest.mark.parametrize("mutation", ["n", "size", "quality", "prompt", "model", "mime", "malformed", "huge", "multiple", "generation"])
def test_image_edit_requires_bounded_decodable_inline_references(installed, mutation):
    payload, url = _image(), guard.IMAGE_URL
    if mutation == "n":
        payload["data"]["n"] = 2
    elif mutation == "size":
        payload["data"]["size"] = "4096x4096"
    elif mutation == "quality":
        payload["data"]["quality"] = "high"
    elif mutation == "prompt":
        payload["data"]["prompt"] = "x" * 5001
    elif mutation == "model":
        payload["data"]["model"] = "gpt-image-1"
    elif mutation == "mime":
        payload["files"]["image[]"] = ("image.jpg", _png(), "image/jpeg")
    elif mutation == "malformed":
        payload["files"]["image[]"] = ("image.png", b"not-an-image", "image/png")
    elif mutation == "huge":
        payload["files"]["image[]"] = ("image.png", b"x" * guard.MAX_IMAGE_BYTES, "image/png")
    elif mutation == "multiple":
        payload["files"]["second"] = payload["files"]["image[]"]
    else:
        url = "https://api.openai.com/v1/images/generations"
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("No transport"))) as client:
        with pytest.raises(RuntimeError, match="LIVE_PHOTO"):
            client.post(url, **payload)
    assert installed.journal.read_text() == ""


def test_two_references_are_one_billed_image_attempt_and_never_enter_journal(installed):
    payload = _image()
    first = payload["files"]["image[]"]
    payload["files"] = [("image[]", first), ("image[]", ("owned-cover.png", _png(), "image/png"))]
    calls = []

    def accept(request):
        calls.append(request)
        assert request.content.count(b'name="image[]"') == 2
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_png()).decode()}]})

    with httpx.Client(transport=httpx.MockTransport(accept)) as client:
        client.post(guard.IMAGE_URL, **payload)
    events = list(map(json.loads, installed.journal.read_text().splitlines()))
    assert len(calls) == 1
    assert [(e["role"], e["request_index"]) for e in events if e["kind"] == "request"] == [("image", 1)]
    assert events[0]["reservation_usd"] == installed.policy["image_request_reservation_usd"]
    assert "owned-cover" not in installed.journal.read_text()


@pytest.mark.parametrize("mutation", ["empty", "three", "wrong_field", "bad_second", "large_second", "stream"])
def test_invalid_secondary_reference_rejected_before_reservation_or_network(installed, mutation):
    payload = _image()
    first = payload["files"]["image[]"]
    files = [("image[]", first), ("image[]", first)]
    if mutation == "empty":
        files = []
    elif mutation == "three":
        files.append(("image[]", first))
    elif mutation == "wrong_field":
        files[1] = ("mask", first)
    elif mutation == "bad_second":
        files[1] = ("image[]", ("second.jpg", _png(), "image/jpeg"))
    elif mutation == "large_second":
        files[1] = ("image[]", ("second.png", b"x" * guard.MAX_IMAGE_BYTES, "image/png"))
    else:
        files = iter(files)
    payload["files"] = files
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("No transport"))) as client:
        with pytest.raises(RuntimeError, match="LIVE_PHOTO"):
            client.post(guard.IMAGE_URL, **payload)
    assert installed.journal.read_text() == ""


def test_encoded_response_payload_and_client_default_options_are_bounded(installed, monkeypatch):
    assert guard.MAX_RESPONSE_BYTES == 40 * 1024 * 1024
    monkeypatch.setattr(guard, "MAX_RESPONSE_BYTES", 1024)
    payload = _responses()
    payload["json"]["input"] = "가" * 1024
    transport = httpx.MockTransport(lambda _: pytest.fail("No transport"))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(RuntimeError, match="PAYLOAD_LIMIT"):
            client.post(guard.RESPONSES_URL, **payload)
    for options in ({"params": {"private": "secret"}}, {"follow_redirects": True}):
        with httpx.Client(transport=transport, **options) as client:
            with pytest.raises(RuntimeError, match="UNEXPECTED_POST"):
                client.post(guard.RESPONSES_URL, **_responses())
    assert installed.journal.read_text() == ""


def _reserve_in_process(args):
    path, policy, role = args
    try:
        guard.reserve_request(path, policy, role, policy["llm_model" if role == "llm" else "image_model"])
        return True
    except RuntimeError as error:
        assert str(error) == "LIVE_PHOTO_BUDGET_LIMIT"
        return False


def test_separate_processes_atomically_reserve_one_shared_exact_budget(config):
    policy = dict(config.policy, max_budget_usd=0.7,
                  llm_request_reservation_usd=0.1, image_request_reservation_usd=0.2)
    args = [(str(config.journal), policy, "llm" if n % 2 else "image") for n in range(32)]
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("fork")) as pool:
        outcomes = list(pool.map(_reserve_in_process, args))
    events = list(map(json.loads, config.journal.read_text().splitlines()))
    assert sum(outcomes) == len(events)
    assert sum(guard._money(e["reservation_usd"]) for e in events) == guard._money(0.7)
    assert events[-1]["reserved_total_usd"] == 0.7


def test_corrupt_or_changed_policy_journal_fails_closed_and_install_is_idempotent(installed):
    original = httpx.AsyncClient.post
    guard.install()
    assert httpx.AsyncClient.post is original
    guard.reserve_request(installed.journal, installed.policy, "llm", "gpt-5.6-sol")
    with pytest.raises(RuntimeError, match="INVALID_JOURNAL"):
        guard.reserve_request(installed.journal, dict(installed.policy, max_budget_usd=9), "llm", "gpt-5.6-sol")
    with installed.journal.open("a") as stream:
        stream.write("incomplete-journal-line\n")
    with pytest.raises(RuntimeError, match="INVALID_JOURNAL"):
        guard.reserve_request(installed.journal, installed.policy, "llm", "gpt-5.6-sol")


@pytest.mark.parametrize("body", [{"data": [{"url": "https://private.example/image"}]},
    {"data": [{"b64_json": "not base64"}]}, {"data": []}, {"data": [{}, {}]}])
def test_output_dimensions_never_fetch_external_urls_or_guess_on_invalid_bytes(body):
    assert guard.image_dimensions(body) == ([], False)


@pytest.mark.parametrize("model,usage,expected", [
    ("gpt-5.6-sol", {"input_tokens": 1000, "output_tokens": 2000}, 0.044),
    ("gpt-image-2", {"input_tokens": 1000, "output_tokens": 2000}, 0.068),
    ("gpt-6-astra", {"input_tokens": 1000, "output_tokens": 2000}, None),
    ("gpt-image-2", {"input_tokens": 1000}, None),
    ("gpt-image-2", {"input_tokens": 1000, "output_tokens": "2000"}, None),
    ("gpt-5.6-sol", {"input_tokens": 0, "output_tokens": 0}, 0),
])
def test_usage_estimates_only_use_reported_numeric_tokens_and_known_rates(model, usage, expected):
    assert guard.estimate_usage_usd(model, usage) == expected


def test_completed_usage_estimate_stops_new_requests_even_if_reservations_remain(installed):
    def expensive(_request):
        return httpx.Response(200, json={"usage": {"input_tokens": 2_500_000, "output_tokens": 1}})
    with httpx.Client(transport=httpx.MockTransport(expensive)) as client:
        client.post(guard.RESPONSES_URL, **_responses())
        with pytest.raises(RuntimeError, match="USAGE_ESTIMATE_LIMIT"):
            client.post(guard.RESPONSES_URL, **_responses())
    events = list(map(json.loads, installed.journal.read_text().splitlines()))
    assert len(events) == 2
    assert events[0]["reserved_total_usd"] == 0.1
    assert events[1]["estimated_usage_usd"] > installed.policy["max_budget_usd"]


def test_completed_usage_settles_its_reservation_and_duplicate_response_is_counted_once(config):
    config.policy.update(max_budget_usd=0.5, llm_request_reservation_usd=0.4,
                         image_request_reservation_usd=0.12)
    config.policy_path.write_text(json.dumps(config.policy))
    guard.install()

    def complete(_request):
        return httpx.Response(200, json={"usage": {"input_tokens": 1000, "output_tokens": 2000}})

    with httpx.Client(transport=httpx.MockTransport(complete)) as client:
        client.post(guard.RESPONSES_URL, **_responses())
        first_response = json.loads(config.journal.read_text().splitlines()[-1])
        guard.append_event(config.journal, first_response)
        client.post(guard.RESPONSES_URL, **_responses())
        client.post(guard.RESPONSES_URL, **_responses())
        with pytest.raises(RuntimeError, match="BUDGET_LIMIT"):
            client.post(guard.RESPONSES_URL, **_responses())
    requests = [e for e in map(json.loads, config.journal.read_text().splitlines()) if e["kind"] == "request"]
    assert len(requests) == 3  # Historical reservations total 1.20; settled usage is lower.
    assert requests[-1]["completed_estimated_usd"] == 0.088
    assert requests[-1]["unsettled_reserved_usd"] == 0.4
    assert requests[-1]["reserved_total_usd"] == 0.488


@pytest.mark.parametrize("completed_without_usage", [False, True])
def test_inflight_or_unknown_usage_keeps_full_reservation(config, completed_without_usage):
    policy = dict(config.policy, max_budget_usd=0.5,
                  llm_request_reservation_usd=0.4, image_request_reservation_usd=0.12)
    reservation = guard.reserve_request(config.journal, policy, "llm", "gpt-5.6-sol")
    if completed_without_usage:
        event = {key: reservation[key] for key in ("role", "model", "provider", "request_index", "journal_version")}
        guard.append_event(config.journal, {**event, "kind": "response", "http_status": 429,
                                           "usage": {}, "estimated_usage_usd": None})
    with pytest.raises(RuntimeError, match="BUDGET_LIMIT"):
        guard.reserve_request(config.journal, policy, "llm", "gpt-5.6-sol")


def test_provider_auth_diagnostic_records_only_owned_enums_not_key_echo(installed):
    secret = "private-api-key-and-child-content"
    def reject(_request):
        return httpx.Response(401, json={"error": {
            "code": "invalid_api_key", "type": "invalid_request_error", "param": secret,
            "message": "Incorrect API key provided: " + secret,
        }})
    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        assert client.post(guard.IMAGE_URL, **_image()).status_code == 401
    response = json.loads(installed.journal.read_text().splitlines()[-1])
    assert response["provider_error"] == {"code": "invalid_api_key", "type": "invalid_request_error"}
    assert secret not in installed.journal.read_text() and "message" not in response["provider_error"]
    assert guard.safe_provider_error({"error": {"code": secret, "type": secret, "param": secret}}) == {}
