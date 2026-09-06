"""Real repair helper/adapters with inert HTTP responses and local byte storage."""

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from src.services.image_quality import BookIllustrationReview
from src.services.structured_output import provider_output_schema

PRIVATE = "private-child-fixture-never-in-report"


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import run_saved_illustration_repair
    return run_saved_illustration_repair


def png(color):
    output = BytesIO()
    Image.new("RGB", (896, 1200), color).save(output, format="PNG")
    return output.getvalue()


def fixture_book():
    images = {page: (png(color), "image/png")
              for page, color in enumerate(["white", "red", "green", "yellow", "purple"])}
    inputs = {"title": "모의 책 " + PRIVATE,
              "page_texts": {page: "친구와 책을 정리해요 " + PRIVATE for page in range(5)},
              "image_prompts": {page: "Two fictional children with distinct clothing, blank books" for page in range(5)},
              "images": images}
    manifest = {"source": "docs/acceptance/inert-source", "book_sha256": "a" * 64,
                "illustrations": [{"page_number": page, "sha256": hashlib.sha256(data).hexdigest()}
                                  for page, (data, _mime) in images.items()]}
    return inputs, manifest


def completed_review(*, issues, issue_pages=(2,)):
    payload = {"pages": [{"page_number": page, "issues": issues if page in issue_pages else []} for page in range(5)]}
    return {"status": "completed", "error": None, "incomplete_details": None,
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(payload)},
            ]}], "usage": {"input_tokens": 1000, "output_tokens": 2000}}


@pytest.mark.asyncio
@pytest.mark.parametrize("recheck_fails", [False, True])
async def test_production_helper_repairs_one_page_once_and_preserves_source(
    monkeypatch, tmp_path, tool, recheck_fails,
):
    inputs, manifest = fixture_book()
    monkeypatch.setattr(tool, "load_book", lambda _directory: (inputs, manifest))
    calls = []
    review_count = 0
    repaired = png("blue")

    async def post(self, url, **kwargs):
        nonlocal review_count
        calls.append(str(url))
        if str(url) == tool.REVIEW_URL:
            review_count += 1
            body = completed_review(issues=["printed_instructions", "readable_text"]
                                    if review_count == 1 or recheck_fails else [])
        else:
            assert str(url) == tool.IMAGE_URL
            parts = kwargs["json"]["contents"][0]["parts"]
            assert [base64.b64decode(part["inline_data"]["data"])
                    for part in parts if "inline_data" in part] == [
                        inputs["images"][2][0], inputs["images"][0][0],
                    ]
            assert "IMAGE1 is the generated page to edit" in parts[0]["text"]
            assert "IMAGE2 is the book cover" in parts[0]["text"]
            body = {"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "image/png", "data": base64.b64encode(repaired).decode(),
            }}]}}], "usageMetadata": {
                "promptTokenCount": 1000, "candidatesTokenCount": 1200, "thoughtsTokenCount": 20,
            }}
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = SimpleNamespace(llm_provider="openai", llm_model="gpt-5.6-sol", llm_api_key="inert-key",
                             image_provider="gemini", image_model="gemini-3-pro-image",
                             image_api_key="inert-image", llm_timeout=90, image_timeout=90)
    report = await tool.run_repair(inputs, manifest, tmp_path, config)
    assert calls == [tool.REVIEW_URL, tool.IMAGE_URL, tool.REVIEW_URL]
    assert report["status"] == ("failed" if recheck_fails else "passed")
    assert len(report["reviews"]) == 2 and len(report["regenerated_files"]) == 1
    assert report["source_unchanged"] is True
    assert report["published"] is report["real_postgres"] is report["real_s3"] is report["real_celery"] is False
    assert report["source_photo_used"] is False
    assert report["estimates_usd"] == pytest.approx({"llm": 0.088, "image": 0.1376})
    assert [item["step"] for item in report["progress"]] == [
        "verify_illustrations", "repair_illustrations", "verify_illustrations"]
    if not recheck_fails:
        assert report["changed_pages"] == report["repaired_pages"] == [2]
        assert report["image_budget_used"] == 1
        assert report["visual_briefs_before_sha256"] == report["visual_briefs_after_sha256"]
    assert [event["full_original_visual_brief_preserved"] for event in report["requests"]
            if event["role"] == "image"] == [True]
    before = {item["page_number"]: item["sha256"] for item in manifest["illustrations"]}
    changed = [item["page_number"] for item in report["candidate_after_not_published"]
               if item["sha256"] != before[item["page_number"]]]
    assert changed == [2]
    assert inputs["images"][2][0] != repaired
    assert httpx.AsyncClient.post is post, "Restore both layers of HTTP instrumentation"
    assert PRIVATE not in json.dumps(report)
    for path in tmp_path.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if path.suffix != ".png":
            assert PRIVATE not in path.read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["identity", "flagged_cover"])
async def test_saved_repair_preserves_identity_and_never_spreads_unreviewed_cover(
    monkeypatch, tmp_path, tool, scope,
):
    inputs, manifest = fixture_book()
    monkeypatch.setattr(tool, "load_book", lambda _directory: (inputs, manifest))
    review_count = 0
    sent = []
    repaired = png("blue")

    async def post(self, url, **kwargs):
        nonlocal review_count
        if str(url) == tool.REVIEW_URL:
            review_count += 1
            body = completed_review(
                issues=(["identity_swap"] if scope == "identity" else ["readable_text"])
                if review_count == 1 else [],
                issue_pages=(2,) if scope == "identity" else (0, 2),
            )
        else:
            assert str(url) == tool.IMAGE_URL
            parts = kwargs["json"]["contents"][0]["parts"]
            sent.append([base64.b64decode(part["inline_data"]["data"])
                         for part in parts if "inline_data" in part])
            body = {"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "image/png", "data": base64.b64encode(repaired).decode(),
            }}]}}], "usageMetadata": {
                "promptTokenCount": 1000, "candidatesTokenCount": 1200, "thoughtsTokenCount": 20,
            }}
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = SimpleNamespace(llm_provider="openai", llm_model="gpt-5.6-sol", llm_api_key="inert-key",
                             image_provider="gemini", image_model="gemini-3-pro-image",
                             image_api_key="inert-image", llm_timeout=90, image_timeout=90)
    report = await tool.run_repair(inputs, manifest, tmp_path, config)
    assert report["status"] == "passed"
    assert review_count == 2
    assert sent == ([[inputs["images"][0][0]]] if scope == "identity" else [
        [inputs["images"][0][0]], [inputs["images"][2][0]],
    ])
    assert all(repaired not in references for references in sent)
    assert report["changed_pages"] == ([2] if scope == "identity" else [0, 2])
    assert report["image_budget_used"] == len(sent)
    assert report["source_unchanged"] is True


@pytest.mark.parametrize("defect", ["endpoint", "schema", "store", "model", "tokens", "remote_image"])
def test_review_outer_guard_rejects_expanded_scope(tool, defect):
    from src.services.openai_contract import openai_request

    inputs, _ = fixture_book()
    owned = tool.inline_images(inputs["images"])
    schema = provider_output_schema(BookIllustrationReview.model_json_schema(), provider="openai")
    url, payload = openai_request("gpt-5.6-sol", user_prompt="fixture", max_tokens=2048,
                                 image_urls=[next(iter(owned))] * 5,
                                 response_schema=BookIllustrationReview.model_json_schema())
    if defect == "endpoint":
        url += "?key=" + PRIVATE
    elif defect == "schema":
        payload["text"]["format"]["schema"] = {"description": PRIVATE}
    elif defect == "store":
        payload["store"] = True
    elif defect == "model":
        payload["model"] = "gpt-6-astra"
    elif defect == "tokens":
        payload["max_output_tokens"] = 6145
    else:
        payload["input"][0]["content"][2]["image_url"] = "https://example.invalid/" + PRIVATE
    with pytest.raises(ValueError) as caught:
        tool.validate_repair_request(url, payload, follow_redirects=False, schema=schema,
                                     cover=inputs["images"][0], owned_images=owned)
    assert PRIVATE not in str(caught.value)


def test_image_outer_guard_requires_only_the_known_generated_cover(tool):
    inputs, _ = fixture_book()
    cover = inputs["images"][0]
    body = {"contents": [{"parts": [{"text": "identity reference"}, {"inline_data": {
        "mime_type": cover[1], "data": base64.b64encode(cover[0]).decode(),
    }}, {"text": "corrected illustration"}]}], "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "3:4"},
    }}
    assert tool.validate_repair_request(tool.IMAGE_URL, body, follow_redirects=False,
                                       schema={}, cover=cover,
                                       owned_images=tool.inline_images(inputs["images"])) == "image"
    body["contents"][0]["parts"][1]["inline_data"]["data"] = base64.b64encode(png("red")).decode()
    with pytest.raises(ValueError, match="REFERENCE_ORDER_REQUIRED"):
        tool.validate_repair_request(tool.IMAGE_URL, body, follow_redirects=False,
                                     schema={}, cover=cover,
                                     owned_images=tool.inline_images(inputs["images"]))


@pytest.mark.parametrize("defect", [None, "reverse", "other_owned_page", "extra", "unowned", "long_prompt"])
def test_image_guard_allows_only_exact_page_then_qa_accepted_cover(tool, defect):
    inputs, _ = fixture_book()
    cover, current = inputs["images"][0], inputs["images"][2]
    refs = [current, cover]

    def inline(value):
        return {"inline_data": {"mime_type": value[1], "data": base64.b64encode(value[0]).decode()}}

    parts = [{"text": "page then accepted cover"}, inline(current), inline(cover), {"text": "correct the local defect"}]
    if defect == "reverse":
        parts[1:3] = list(reversed(parts[1:3]))
    elif defect == "other_owned_page":
        parts[1] = inline(inputs["images"][3])
    elif defect == "extra":
        parts.insert(3, inline(inputs["images"][1]))
    elif defect == "unowned":
        refs = [(png("blue"), "image/png"), cover]
        parts[1] = inline(refs[0])
    elif defect == "long_prompt":
        parts[-1]["text"] = "x" * 5000
    body = {"contents": [{"parts": parts}], "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "3:4"},
    }}
    kwargs = dict(follow_redirects=False, schema={}, cover=cover,
                  expected_references=refs, owned_images=tool.inline_images(inputs["images"]))
    if defect is None:
        assert tool.validate_repair_request(tool.IMAGE_URL, body, **kwargs) == "image"
    else:
        with pytest.raises(ValueError) as caught:
            tool.validate_repair_request(tool.IMAGE_URL, body, **kwargs)
        assert PRIVATE not in str(caught.value)
