"""No paid calls: bounded repair requests and response-based image cost evidence."""

import asyncio
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from src.services.illustration_policy import book_image_request_limit
from tests.test_live_acceptance_guard import guard, write_cost_fixture

PRIVATE = "private-child-name-key-and-signed-image-query"
IMAGE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image:generateContent"


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import run_live_book_acceptance as book
    import run_live_quality_matrix as matrix
    return book, matrix


def install_guard(monkeypatch, path, *, pages="4", enabled="true"):
    path.touch(mode=0o600)
    monkeypatch.setenv("LIVE_ACCEPTANCE_JOURNAL", str(path))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("IMAGE_MODEL", "gemini-3-pro-image")
    monkeypatch.setenv("LIVE_ACCEPTANCE_PAGE_COUNT", pages)
    monkeypatch.setenv("ILLUSTRATION_QUALITY_ENABLED", enabled)
    monkeypatch.setattr(httpx.AsyncClient, "post", httpx.AsyncClient.post)
    guard.install()


def image_part(*, snake=False):
    output = BytesIO()
    Image.new("RGB", (896, 1200), "white").save(output, format="PNG")
    return {"inline_data" if snake else "inlineData": {
        "mime_type" if snake else "mimeType": "image/png",
        "data": base64.b64encode(output.getvalue()).decode(),
    }}


@pytest.mark.asyncio
@pytest.mark.parametrize("pages,limit", [(4, 7), (8, 11), (12, 16)])
async def test_normal_failures_and_repairs_share_one_bounded_image_counter(
    monkeypatch, tmp_path, pages, limit,
):
    path = tmp_path / "journal.jsonl"
    # Arbitrary budget-like environment values cannot raise the owned limit.
    monkeypatch.setenv("LIVE_ACCEPTANCE_IMAGE_LIMIT", "999999")
    install_guard(monkeypatch, path, pages=str(pages))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": PRIVATE})

    async def attempt():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            try:
                return (await client.post(IMAGE_URL, json={})).status_code
            except RuntimeError as error:
                assert str(error) == "LIVE_ACCEPTANCE_REQUEST_LIMIT"
                return "blocked"

    results = await asyncio.gather(*(attempt() for _ in range(limit + 3)))
    assert results.count(429) == limit and results.count("blocked") == 3
    assert len(calls) == limit
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert sum(entry["kind"] == "request" for entry in events) == limit
    assert PRIVATE not in path.read_text()


@pytest.mark.asyncio
async def test_vision_and_generation_share_the_unchanged_sixteen_llm_limit(monkeypatch, tmp_path):
    path = tmp_path / "journal.jsonl"
    install_guard(monkeypatch, path)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"usage": {"input_tokens": 2000, "output_tokens": 1000}})

    for index in range(17):
        payload = {"model": "gpt-5.6-sol", "max_output_tokens": 6144, "store": False}
        if index in {6, 7}:
            payload["text"] = {"format": {"type": "json_schema", "name": "book_illustration_review", "strict": True}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if index == 16:
                with pytest.raises(RuntimeError, match="REQUEST_LIMIT"):
                    await client.post("https://api.openai.com/v1/responses", json=payload)
            else:
                await client.post("https://api.openai.com/v1/responses", json=payload)
    assert len(calls) == 16


@pytest.mark.parametrize("pages,enabled", [
    ("6", "true"), ("12", "false"), ("100", "true"), ("4.0", "true"),
    ("4", "1"), ("4", "unbounded"), ("4", "TRUE"),
])
def test_unbounded_or_ambiguous_guard_configuration_is_rejected(monkeypatch, tmp_path, pages, enabled):
    with pytest.raises(RuntimeError, match="INVALID_BOOK_SELECTION"):
        install_guard(monkeypatch, tmp_path / "journal.jsonl", pages=pages, enabled=enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("snake", [False, True])
async def test_response_records_all_generated_dimensions_without_pixels_or_text(monkeypatch, tmp_path, snake):
    path = tmp_path / "journal.jsonl"
    install_guard(monkeypatch, path)
    first, second = image_part(snake=snake), image_part()
    body = {
        "candidates": [
            {"content": {"parts": [{"text": PRIVATE}, first]}},
            {"content": {"parts": [second, {"thoughtSignature": PRIVATE}]}},
        ],
        "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 2240,
                          "thoughtsTokenCount": 0, "totalTokenCount": 2270, "private": PRIVATE},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        response = await client.post(IMAGE_URL, json={"contents": PRIVATE})
    assert response.json() == body, "Instrumentation must not change the provider response"
    raw = path.read_text()
    event = json.loads(raw.splitlines()[1])
    assert event["journal_version"] == 2
    assert event["image_dimensions_complete"] is True
    assert event["image_dimensions"] == [{"width": 896, "height": 1200}] * 2
    assert PRIVATE not in raw
    assert "iVBOR" not in raw and "inlineData" not in raw and "https://" not in raw


@pytest.mark.parametrize("defect", ["bad_base64", "bad_image", "wrong_mime", "bad_parts"])
def test_malformed_response_images_cannot_claim_complete_dimension_evidence(defect):
    part = image_part()
    if defect == "bad_base64":
        part["inlineData"]["data"] = PRIVATE
    elif defect == "bad_image":
        part["inlineData"]["data"] = base64.b64encode(PRIVATE.encode()).decode()
    elif defect == "wrong_mime":
        part["inlineData"]["mimeType"] = "image/jpeg"
    body = {"candidates": [{"content": {"parts": PRIVATE if defect == "bad_parts" else [part]}}]}
    sizes, complete = guard.image_dimensions(body)
    assert sizes == [] and complete is False
    assert PRIVATE not in json.dumps([sizes, complete])


def test_replaced_and_rejected_images_are_priced_even_without_final_files(tmp_path, scripts):
    _, matrix = scripts
    result, events = write_cost_fixture(tmp_path)
    result.update(provider_journal_version=2, images=[])
    image_event = events[-1]
    image_event.update(image_dimensions=[{"width": 896, "height": 1200}], image_dimensions_complete=True)
    # Five original outputs + two replacements. No final file is needed to price them.
    events = [events[0], *[deepcopy(image_event) for _ in range(7)]]
    (tmp_path / "result.json").write_text(json.dumps(result))
    (tmp_path / "provider-usage.jsonl").write_text("\n".join(map(json.dumps, events)))
    assert matrix.costs(tmp_path) == pytest.approx((0.044, 7 * 0.1376))


def test_multiple_images_in_one_response_and_text_only_response_are_both_charged(tmp_path, scripts):
    _, matrix = scripts
    result, events = write_cost_fixture(tmp_path)
    result.update(provider_journal_version=2, images=[])
    event = events[-1]
    event.update(image_dimensions=[{"width": 896, "height": 1200}] * 2, image_dimensions_complete=True)
    event["usage"]["candidatesTokenCount"] = 2300
    text_only = deepcopy(event)
    text_only.update(image_dimensions=[])
    text_only["usage"]["candidatesTokenCount"] = 100
    events.append(text_only)
    (tmp_path / "result.json").write_text(json.dumps(result))
    (tmp_path / "provider-usage.jsonl").write_text("\n".join(map(json.dumps, events)))
    # Output image tokens are counted once per returned image; remaining output/thoughts are text.
    expected = (2000 * 2 + 2240 * 120 + (60 + 20 + 100 + 20) * 12) / 1e6
    assert matrix.costs(tmp_path) == pytest.approx((0.044, expected))


@pytest.mark.parametrize("defect", ["missing", "incomplete", "unsupported", "malformed", "mixed"])
def test_new_dimension_evidence_never_falls_back_to_legacy_final_files(tmp_path, scripts, defect):
    _, matrix = scripts
    result, events = write_cost_fixture(tmp_path)
    result["provider_journal_version"] = 2
    events[-1].update(image_dimensions=[{"width": 896, "height": 1200}], image_dimensions_complete=True)
    if defect == "missing":
        events[-1].pop("image_dimensions")
    elif defect == "incomplete":
        events[-1]["image_dimensions_complete"] = False
    elif defect == "unsupported":
        events[-1]["image_dimensions"][0]["width"] = 900
    elif defect == "malformed":
        events[-1]["image_dimensions"] = PRIVATE
    else:
        legacy = deepcopy(events[-1])
        legacy.pop("image_dimensions")
        legacy.pop("image_dimensions_complete")
        events.append(legacy)
        result.pop("provider_journal_version")
    (tmp_path / "result.json").write_text(json.dumps(result))
    (tmp_path / "provider-usage.jsonl").write_text("\n".join(map(json.dumps, events)))
    with pytest.raises(RuntimeError, match="COST_IMAGE_DIMENSIONS") as caught:
        matrix.costs(tmp_path)
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("pages,expected", [(4, 7), (8, 11), (12, 16)])
def test_paid_harness_forces_quality_flag_and_owned_limits(scripts, pages, expected):
    book, _ = scripts
    config = SimpleNamespace(llm_provider="openai", llm_model="gpt-5.6-sol")
    assert book.quality_gate_environment(pages, config) == {
        "ILLUSTRATION_QUALITY_ENABLED": "true", "LIVE_ACCEPTANCE_PAGE_COUNT": str(pages),
    }
    assert book.request_limits(pages, True) == {"llm": 16, "image": expected}
    assert expected == book_image_request_limit(pages)
    with pytest.raises(RuntimeError, match="REQUIRES_VERIFIED_OPENAI"):
        book.quality_gate_environment(pages, SimpleNamespace(llm_provider="anthropic", llm_model="claude-sonnet-5"))


@pytest.mark.parametrize("pages,limit,capture", [(4, 7, False), (12, 16, True)])
def test_one_book_runtime_and_result_carry_the_same_gate_and_limits(monkeypatch, tmp_path, scripts, pages, limit, capture):
    book, _ = scripts
    root = tmp_path / "repository"
    api = root / "apps/api"
    for folder in ("src", "alembic", "assets"):
        (api / folder).mkdir(parents=True)
    (api / "alembic.ini").write_text("inert fixture")
    (root / "scripts").mkdir()
    (root / "scripts/live_acceptance_guard.py").write_text("# inert snapshot fixture\n")
    (root / "scripts/fictional_review_capture.py").write_text("# inert snapshot fixture\n")
    output = root / "docs/acceptance/run"
    monkeypatch.setattr(book, "ROOT", root)
    monkeypatch.setattr(book, "require_ignored_path", lambda _path: None)
    monkeypatch.setattr(book, "load_reader_profile", lambda *_args: None)
    config = SimpleNamespace(llm_provider="openai", llm_model="gpt-5.6-sol", llm_api_key="inert-test-key",
                             image_provider="gemini", image_model="gemini-3-pro-image", image_api_key="inert-test-image")
    monkeypatch.setattr(book, "load_runtime_config", lambda _args: config)
    monkeypatch.setattr(book, "clean_environment", lambda: {"DOCKER_HOST": "unix:///inert-socket"})
    runtimes = []
    monkeypatch.setattr(book, "run", lambda *_args, **kwargs: runtimes.append(kwargs["env"]) or "")
    monkeypatch.setattr(book, "port_for", lambda *_args: 12345)
    monkeypatch.setattr(book, "free_port", lambda: 12346)
    monkeypatch.setattr(book.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(book.subprocess, "Popen", lambda *_args, **kwargs: SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(book, "stop_process_group", lambda _process: None)
    monkeypatch.setattr(book.httpx, "get", lambda *_args, **_kwargs: SimpleNamespace(status_code=200))
    monkeypatch.setattr(book, "journey", lambda *_args: None)
    args = SimpleNamespace(output_dir=output, reader_profile_file=None, age="5-7", case=1, page_count=pages,
                           hold_seconds=0, retain_fictional_review_evidence=capture)
    assert book.run_acceptance(args) == 0
    runtime = next(value for value in runtimes if "LIVE_ACCEPTANCE_PAGE_COUNT" in value)
    assert runtime["LIVE_ACCEPTANCE_PAGE_COUNT"] == str(pages)
    assert runtime["ILLUSTRATION_QUALITY_ENABLED"] == "true"
    assert runtime["AUDIO_FEATURE_ENABLED"] == runtime["PURCHASES_ENABLED"] == runtime["POD_ORDERING_ENABLED"] == "false"
    report = json.loads((output / "result.json").read_text())
    assert report["illustration_quality_enabled"] is True
    assert report["provider_journal_version"] == 2
    assert report["request_limits"] == {"llm": 16, "image": limit}
    assert (runtime.get("LIVE_FICTIONAL_REVIEW_CAPTURE") == "true") is capture
    assert "inert-test-key" not in json.dumps(report)


def test_twelve_page_text_run_rejects_private_reader_profile_before_setup(tmp_path, scripts):
    book, _ = scripts
    output = tmp_path / "acceptance"
    args = SimpleNamespace(output_dir=output, reader_profile_file=tmp_path / "private.json", page_count=12)
    with pytest.raises(book.GateFailure, match="TWELVE_PAGE_RUN_REQUIRES_FICTIONAL_INPUT"):
        book.run_acceptance(args)
    assert not output.exists()


@pytest.mark.parametrize("error,expected", [
    ({"code": "IMAGE_QUALITY_FAILED", "message": PRIVATE}, "IMAGE_QUALITY_FAILED"),
    ({"code": "LLM_JSON_INVALID", "message": PRIVATE}, "LLM_JSON_INVALID"),
    ({"code": "UNKNOWN", "message": PRIVATE}, "UNKNOWN"),
    ({"code": "PRIVATE_CHILD_VALUE", "message": PRIVATE}, None),
    ({"code": [PRIVATE]}, None), ({"code": None}, None), ({"code": True}, None),
    ({"code": "IMAGE_QUALITY_FAILED\n" + PRIVATE}, None), (PRIVATE, None),
])
def test_job_error_report_accepts_only_nested_known_codes(scripts, error, expected):
    book, _ = scripts
    assert book.job_error_code({"error": error, "error_code": PRIVATE}) == expected


def test_reported_error_codes_match_the_current_public_job_contract(scripts):
    from src.core.errors import ErrorCode

    book, _ = scripts
    assert book._JOB_ERROR_CODES == {code.value for code in ErrorCode}


def test_failed_journey_records_current_step_and_nested_code_without_private_message(monkeypatch, tmp_path, scripts):
    book, _ = scripts
    states = iter([
        {"status": "running", "progress": 86, "current_step": "verify_illustrations"},
        {"status": "failed", "progress": 88, "current_step": "verify_illustrations",
         "error": {"code": "IMAGE_QUALITY_FAILED", "message": PRIVATE},
         "error_code": PRIVATE, "step": PRIVATE, "step_name": PRIVATE},
    ])

    def respond(request):
        if request.url.path == "/v1/characters/from-text":
            return httpx.Response(200, json={"character_id": "fixture"})
        if request.url.path == "/v1/books":
            return httpx.Response(200, json={"job_id": "fixture"})
        if request.url.path == "/v1/books/fixture":
            return httpx.Response(200, json=next(states))
        return httpx.Response(200, json={})

    original = httpx.Client
    monkeypatch.setattr(book.httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(book.time, "sleep", lambda _: None)
    report = {}
    with pytest.raises(RuntimeError, match="did not complete"):
        book.journey("http://api.invalid", tmp_path, "7-9", report, page_count=4)
    assert report["job_error_code"] == "IMAGE_QUALITY_FAILED"
    assert [stage["state"]["current_step"] for stage in report["stages"]] == ["verify_illustrations"] * 2
    assert PRIVATE not in json.dumps(report)
